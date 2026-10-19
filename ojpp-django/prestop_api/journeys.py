"""Journey planning through OTP `planConnection`, which applies realtime delays and
cancellations, supports native via points and a minimum transfer slack."""
import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import abroad, driving, geometry, journey_legs, sharing, leg_alerts, mapping, platforms, predictions, roads, stopfix, tracks, transfer_walk
from . import geometry as geometry_lib
from . import operators as companies
from .upstream import UpstreamError

logger = logging.getLogger(__name__)

MODES = {'walk', 'bus', 'rail', 'bike', 'scooter', 'car', 'carPark'}  # car: drive all the way; carPark: drive, park, ride
RIDE_MODES = {'bike', 'scooter'}
CAR_MODES = {'car', 'carPark'}
COST_PRESETS = ('fastest', 'balanced', 'cheapest')
# 2026-10-18, 6 bike rides in 4 towns: SAFE_STREETS (OTP's default) 26 % on cycle paths, SHORTEST_DURATION 6 % (-10 % time).
RIDE_OPTIMIZATION = 'SAFE_STREETS'
FUELS = ('petrol', 'diesel', 'lpg', 'electric')
PRICE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,47}')
PROFILE_LIMITS = {'cards': 12, 'bikeMemberships': 24, 'scooterPasses': 8}
ROAD_WAIT = 1.5  # s a search waits for leg shapes still being matched (roads.py); later legs keep the feed's shape
TRANSIT = {'bus': ['BUS', 'COACH', 'TROLLEYBUS'], 'rail': ['RAIL', 'TRAM', 'SUBWAY', 'MONORAIL', 'FUNICULAR']}
MAX_OPERATORS = 80
# Insane mode optimises for arrival time only: no per-transfer penalty, OTP's highest transfer limits,
# no transfer slack, and transfers walked at a brisk pace (m/s; OTP's default is 1.33). The rider may
# even allow -1 min (the next vehicle leaves up to a minute before they could reach it, betting on a
# delay or a hold); OTP refuses negative slack, so that is a second pass (see bet_on_delays).
INSANE_WALK_SPEED = 1.75
INSANE_MAX_TRANSFERS = (29, 30)  # OTP's maximum: transfers, additional transfers over the best
MAX_TRANSFERS_LIMIT = 5  # the rider's "at most N transfers" filter goes up to this
INSANE_MIN_SLACK = -60           # s
RISKY_TRANSFER = 120             # s: an Insane transfer with less spare time than this is labelled tight
# OTP picks its own search window (70 min for Kropa → Ljubljana); a sparse route's next connection can be hours later,
# and the answer is then empty (NO_TRANSIT_CONNECTION_IN_SEARCH_WINDOW). A short answer is asked again with the window
# stretched to the edge of the service day, which ends at 04:00 local as on boards (sources.SERVICE_DAY_ENDS_HOUR).
SERVICE_DAY_ENDS_HOUR = 4
MAX_SEARCH_WINDOW = 24 * 3600  # s: OTP refuses longer windows
LOCAL = ZoneInfo('Europe/Ljubljana')

PLAN_Q = '''query($origin: PlanLabeledLocationInput!, $destination: PlanLabeledLocationInput!, $via: [PlanViaLocationInput!],
  $dateTime: PlanDateTimeInput, $modes: PlanModesInput, $preferences: PlanPreferencesInput, $first: Int, $last: Int,
  $before: String, $after: String, $searchWindow: Duration) {
  planConnection(origin: $origin, destination: $destination, via: $via, dateTime: $dateTime, modes: $modes, first: $first,
    last: $last, before: $before, after: $after, preferences: $preferences, searchWindow: $searchWindow) {
    routingErrors { code description }
    pageInfo { startCursor endCursor hasPreviousPage hasNextPage searchWindowUsed }
    edges { node { walkTime
      legs { mode realtimeState transitLeg interlineWithPreviousLeg duration distance rentedBike
        start { scheduledTime estimated { time } } end { scheduledTime estimated { time } }
        from { name lat lon stop { gtfsId platformCode } vehicleRentalStation { stationId rentalNetwork { networkId } }
          rentalVehicle { vehicleId vehicleType { formFactor } rentalNetwork { networkId } } }
        to { name lat lon stop { gtfsId platformCode } vehicleRentalStation { stationId rentalNetwork { networkId } } vehicleParking { name } }
        route { gtfsId shortName longName mode agency { gtfsId } } headsign trip { gtfsId tripHeadsign blockId departureStoptime { scheduledDeparture } }
        legGeometry { points } alerts { id } intermediatePlaces { name lat lon stop { gtfsId } } } } } } }'''


class RequestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _place(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise RequestError('INVALID_REQUEST', f'{field} must be a place')
    lat, lon = value.get('latitude'), value.get('longitude')
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise RequestError('INVALID_REQUEST', f'{field} needs valid coordinates')
    if not isinstance(value.get('name'), str) or not value['name']:
        raise RequestError('INVALID_REQUEST', f'{field} needs a name')
    town = value.get('stopIds')
    if town is not None and (not isinstance(town, list) or len(town) > MAX_TOWN_STOPS or not all(isinstance(s, str) and ':' in s for s in town)):
        raise RequestError('INVALID_REQUEST', f'{field}.stopIds must be up to {MAX_TOWN_STOPS} stop ids')
    return value


MAX_TOWN_STOPS = 8


def town_stops(place: dict) -> set[str]:
    """Every feed stop of a town's main stations (sources.search_stations: Kranj's railway and bus station as one
    place); empty for any other place."""
    ids = place.get('stopIds') or []
    if len(ids) < 2:
        return set()
    from .sources import stop_group
    return {m for s in ids for m in stop_group(s)}


def _price_profile(value) -> dict:
    """The rider's tickets and car from the request body (src/contracts/transit.ts priceProfileSchema). Used for this
    answer only: never stored or logged."""
    if value is None:
        return {'cards': [], 'bikeMemberships': [], 'scooterPasses': [], 'car': None}
    if not isinstance(value, dict):
        raise RequestError('INVALID_REQUEST', 'priceProfile must be an object')
    profile = {}
    for key, limit in PROFILE_LIMITS.items():
        ids = value.get(key) or []
        if not isinstance(ids, list) or len(ids) > limit or not all(isinstance(i, str) and PRICE_ID.fullmatch(i) for i in ids):
            raise RequestError('INVALID_REQUEST', f'priceProfile.{key} must be up to {limit} ids')
        profile[key] = list(dict.fromkeys(ids))
    car = value.get('car')
    if car is not None:
        per_100 = car.get('litresPer100km') if isinstance(car, dict) else None
        if (not isinstance(car, dict) or car.get('fuel') not in FUELS or not isinstance(car.get('vignette'), bool)
                or isinstance(per_100, bool) or not isinstance(per_100, (int, float)) or not 0.5 <= per_100 <= 40):
            raise RequestError('INVALID_REQUEST', 'priceProfile.car needs fuel, litresPer100km (0.5–40) and vignette')
        car = {'fuel': car['fuel'], 'litresPer100km': float(per_100), 'vignette': car['vignette']}
    profile['car'] = car
    return profile


def parse_request(body: dict, insane_enabled: bool) -> dict:
    if not isinstance(body, dict):
        raise RequestError('INVALID_REQUEST', 'Expected a JSON object')
    via = body.get('via') or []
    if not isinstance(via, list) or len(via) > 3:
        raise RequestError('INVALID_REQUEST', 'Up to three stops along the way')
    try:
        when = datetime.fromisoformat(str(body.get('dateTime')).replace('Z', '+00:00'))
    except ValueError:
        raise RequestError('INVALID_REQUEST', 'dateTime must be an ISO timestamp with offset')
    if when.tzinfo is None:
        raise RequestError('INVALID_REQUEST', 'dateTime must include a UTC offset')
    modes = body.get('modes') or []
    if not isinstance(modes, list) or not modes or not set(modes) <= MODES:
        raise RequestError('INVALID_REQUEST', 'Unknown or missing modes')
    if not set(modes) & (set(TRANSIT) | RIDE_MODES | CAR_MODES):
        raise RequestError('NO_MODES', 'Choose at least one public transport mode.')
    risk = body.get('riskMode', 'normal')
    if risk == 'insane' and not insane_enabled:
        raise RequestError('FEATURE_UNAVAILABLE', 'Insane mode is not available yet.')
    slack = body.get('minTransferSeconds', 180)
    low = INSANE_MIN_SLACK if risk == 'insane' else 0
    if not isinstance(slack, int) or not low <= slack <= 1800:
        raise RequestError('INVALID_REQUEST', f'minTransferSeconds must be {low}–1800')
    if body.get('timeMode') not in ('departAt', 'arriveBy'):
        raise RequestError('INVALID_REQUEST', 'timeMode must be departAt or arriveBy')
    cursor, direction = body.get('pageCursor'), body.get('pageDirection', 'later')
    if cursor is not None and (not isinstance(cursor, str) or not 0 < len(cursor) <= 2000):
        raise RequestError('INVALID_REQUEST', 'pageCursor must be a cursor from an earlier response')
    if direction not in ('earlier', 'later'):
        raise RequestError('INVALID_REQUEST', 'pageDirection must be earlier or later')
    operators = body.get('operators') or []
    if not isinstance(operators, list) or len(operators) > MAX_OPERATORS or not all(isinstance(o, str) and ':' in o for o in operators):
        raise RequestError('INVALID_REQUEST', 'operators must be a list of operator ids')
    max_transfers = body.get('maxTransfers')
    if max_transfers is not None and (not isinstance(max_transfers, int) or isinstance(max_transfers, bool) or not 0 <= max_transfers <= MAX_TRANSFERS_LIMIT):
        raise RequestError('INVALID_REQUEST', f'maxTransfers must be 0–{MAX_TRANSFERS_LIMIT}')
    show_prices = body.get('showPrices', True)
    if not isinstance(show_prices, bool):
        raise RequestError('INVALID_REQUEST', 'showPrices must be true or false')
    preset = body.get('costPreset', 'fastest')
    if preset not in COST_PRESETS:
        raise RequestError('INVALID_REQUEST', 'costPreset must be fastest, balanced or cheapest')
    profile = _price_profile(body.get('priceProfile'))
    return {
        'origin': _place(body.get('origin'), 'origin'), 'destination': _place(body.get('destination'), 'destination'),
        'via': [_place(v, f'via[{i}]') for i, v in enumerate(via)], 'dateTime': when, 'timeMode': body['timeMode'],
        # Insane: no buffer, or the rider's negative allowance.
        'modes': set(modes), 'minTransferSeconds': min(0, slack) if risk == 'insane' else slack, 'riskMode': risk,
        'operators': list(dict.fromkeys(operators)), 'pageCursor': cursor, 'pageDirection': direction,
        'maxTransfers': max_transfers,
        # Every plan is priced (2026-10-19); showPrices is still accepted (and checked) but no longer turns prices off.
        'showPrices': True, 'costPreset': preset, 'priceProfile': profile,
    }


def _merged(stop_id: str) -> bool:
    from .sources import stop_group
    return len(stop_group(stop_id)) > 1


def _location(place: dict) -> dict:
    # A merged station is several feed stops, a town two stations: start from its position so OTP may use any of
    # them (build_journeys drops the walk to a town's station).
    if place.get('stopId') and not place.get('stopIds') and not _merged(place['stopId']):
        return {'label': place['name'], 'location': {'stopLocation': {'stopLocationId': place['stopId']}}}
    return {'label': place['name'], 'location': {'coordinate': {'latitude': place['latitude'], 'longitude': place['longitude']}}}


def otp_variables(req: dict) -> dict:
    street = ['WALK']
    if 'bike' in req['modes']:
        street.append('BICYCLE_RENTAL')
    elif 'scooter' in req['modes']:
        # OTP takes one rental kind per search ("only one or two modes for a leg"): with bikes too, scooters are an
        # extra search (extra_searches).
        street.append('SCOOTER_RENTAL')
    transit = [{'mode': m} for key in ('bus', 'rail') if key in req['modes'] for m in TRANSIT[key]]
    agencies = companies.expand(req.get('operators') or [])  # every feed's id of each chosen company
    if 'rail' in req['modes'] and 'bus' not in req['modes']:
        # Rail only still means SŽ's replacement buses (nadomestni prevoz) when they run instead of trains:
        # add buses, limited to the rail operator (or the user's choice of it).
        rail_agencies = [a for a in agencies if a in mapping.REPLACEMENT_AGENCIES] if agencies else list(mapping.REPLACEMENT_AGENCIES)
        if rail_agencies:
            transit += [{'mode': 'BUS'}, {'mode': 'COACH'}]
            agencies = rail_agencies
    via = []
    for v in req['via']:
        visit = {'label': v['name'], 'minimumWaitTime': 'PT0S'}
        if v.get('stopId'):
            from .sources import stop_group
            visit['stopLocationIds'] = sorted(town_stops(v)) or stop_group(v['stopId'])
        else:
            visit['coordinate'] = {'latitude': v['latitude'], 'longitude': v['longitude']}
        via.append({'visit': visit})
    stamp = req['dateTime'].isoformat()
    insane = req.get('riskMode') == 'insane' or req.get('wider')
    transfer = {'slack': f'PT{0 if insane else max(0, req["minTransferSeconds"])}S'}
    # Bikes and scooters keep to cycle paths and quiet streets (OTP's SAFE_STREETS; e-scooters must use cycle
    # infrastructure, ZPrCP 97.a), said outright so a change of OTP's default cannot move riders onto main roads.
    preferences: dict = {'transit': {'transfer': transfer}, 'street': {'bicycle': {'optimization': {'type': RIDE_OPTIMIZATION}},
                                                                       'scooter': {'optimization': {'type': RIDE_OPTIMIZATION}}}}
    if insane:
        transfer.update(cost=0, maximumTransfers=INSANE_MAX_TRANSFERS[0], maximumAdditionalTransfers=INSANE_MAX_TRANSFERS[1])
        preferences['street']['walk'] = {'speed': INSANE_WALK_SPEED}
    if req.get('maxTransfers') is not None:
        # The rider's limit; OTP stops searching beyond it.
        transfer['maximumTransfers'] = req['maxTransfers']
    if agencies:
        # Only trips run by the chosen companies; walking and rentals are unaffected.
        preferences['transit']['filters'] = [{'include': [{'agencies': agencies}]}]
    count = 6 if insane else 5
    variables = {
        'origin': _location(req['origin']), 'destination': _location(req['destination']), 'via': via,
        'dateTime': {'latestArrival': stamp} if req['timeMode'] == 'arriveBy' else {'earliestDeparture': stamp},
        'modes': {'direct': street, **({'transit': {'access': street, 'egress': street, 'transfer': ['WALK'], 'transit': transit}} if transit else {'directOnly': True})},
        'preferences': preferences, 'first': count,
    }
    # Earlier / later connections: OTP pages with the cursors of the previous response.
    if req.get('pageCursor') and req.get('pageDirection') == 'earlier':
        del variables['first']
        variables.update(before=req['pageCursor'], last=count)
    elif req.get('pageCursor'):
        variables['after'] = req['pageCursor']
    return variables


def _seconds(duration: Optional[str]) -> int:
    """An ISO 8601 duration as OTP writes it (PT1H10M, PT86400S) in seconds; 0 when missing."""
    m = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', duration or '')
    if not m or not duration:
        return 0
    days, hours, minutes, seconds = m.groups()
    return int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes or 0) * 60 + round(float(seconds or 0))


def day_window(req: dict) -> int:
    """Seconds of the service day (04:00 to 04:00 local) left after the departure time, or gone before the arrival
    time. In the small hours a departure runs on to the end of the day that is starting, an arrival back to the
    start of the day that is ending."""
    when = req['dateTime'].astimezone(LOCAL)
    day_start = when.replace(hour=SERVICE_DAY_ENDS_HOUR, minute=0, second=0, microsecond=0)
    if req['timeMode'] == 'departAt':
        seconds = (day_start + timedelta(days=1)).timestamp() - when.timestamp()
    else:
        if when.hour < SERVICE_DAY_ENDS_HOUR:
            day_start -= timedelta(days=1)
        seconds = when.timestamp() - day_start.timestamp()
    return int(min(max(seconds, 3600), MAX_SEARCH_WINDOW))


def _edges(data: dict) -> list[dict]:
    return [e for e in (data.get('planConnection') or {}).get('edges') or [] if e['node'].get('legs')]


MAX_EXTRA_SEARCHES = 2   # per plan request, on top of the main search
MAX_OTP_QUERIES = 4      # per plan request in all (shared rules); extra searches get what the main search left
EXTRA_TTL = 300          # s an extra search's answer is reused
_extra_cache: dict[str, tuple[float, dict]] = {}


MEMBER_NEAR = 1000  # m: the rider's bike network is searched when one of its stations is this close to the start or end


def member_networks(req: dict) -> list[str]:
    """The rider's bike-share memberships with a station near the start or the end (all of them while the station list
    is not loaded yet): a BicikeLJ member going from Kranj to Bled needs no search for one."""
    members = (req.get('priceProfile') or {}).get('bikeMemberships') or []
    from . import sources
    snap = sources.rentals.peek()
    if not members or not snap or not snap.value:
        return members
    ends = [[p['longitude'], p['latitude']] for p in (req['origin'], req['destination'])]
    near = {s['id'].partition(':')[0] for s in snap.value if s['id'].partition(':')[0] in members
            and any(geometry.distance([s['longitude'], s['latitude']], end) <= MEMBER_NEAR for end in ends)}
    return [m for m in members if m in near]


def extra_searches(req: dict) -> list[tuple[str, dict]]:
    """(kind, OTP variables) of the searches OTP cannot fold into the main one, most useful first, at most
    MAX_EXTRA_SEARCHES: driving all the way, drive + park + ride, scooters when bikes are asked for too, and the rider's
    own bike networks where they have a station (BicikeLJ, its first hour free with a membership, before a Bolt bike),
    with Bike off too: pricing.member_rides keeps those rides only when they compete."""
    if req.get('pageCursor'):
        return []
    base = otp_variables(req)
    street = lambda modes: {**base['modes'], 'direct': modes, **({'transit': {**base['modes']['transit'], 'access': modes, 'egress': modes}} if 'transit' in base['modes'] else {})}
    drive = lambda modes: {**base, 'modes': {'direct': modes, 'directOnly': True}, 'first': 1}
    out = []
    if 'car' in req['modes'] and not req['via']:
        out.append(('car', drive(['CAR'])))
    if 'carPark' in req['modes']:
        out.append(('carPark', {}))  # park_and_ride makes its own searches
    if 'bike' in req['modes'] and 'scooter' in req['modes']:
        out.append(('scooter', {**base, 'modes': street(['WALK', 'SCOOTER_RENTAL'])}))
    if (req['modes'] & ({'bike'} | set(TRANSIT))) and (members := member_networks(req)):
        prefs = {**base['preferences'], 'street': {**base['preferences']['street'],
                                                   'bicycle': {**base['preferences']['street']['bicycle'], 'rental': {'allowedNetworks': sorted(members)}}}}
        out.append(('memberBikes', {**base, 'modes': street(['WALK', 'BICYCLE_RENTAL']), 'preferences': prefs}))
    return out[:MAX_EXTRA_SEARCHES]


def fallback_search(kind: str, req: dict) -> Optional[dict]:
    """A second try for an extra search that found nothing: a drive that cannot reach a car-free place (Prešernov trg)
    parks at the nearest car park OTP knows and walks from there."""
    if kind != 'car':
        return None
    return {**otp_variables(req), 'modes': {'direct': ['CAR_PARKING'], 'directOnly': True}, 'first': 1}


PARK_SECONDS = 120     # s from stopping the car to walking off (drive + park + ride)
DRIVE_TTL = 12 * 3600  # s a drive is reused: OTP drives without traffic, the same at any hour
CAR_FREE_WALK = 1000   # m: a start in a car-free zone walks at most this far to a car park
PARK_RIDES = 10        # connections asked for: OTP drives to a stop and rides on (those that only walk and ride are dropped)
PARK_CAR_RELUCTANCE = 1.0  # a minute driven weighs as much as a minute ridden (OTP's default, 2, left the drive out of most answers)
PARK_LEAD = 240        # s a departing search starts after the time asked: parking and the walk to the stop come before the ride
# OTP's own window (40-70 min) often held no train at midday (Bled 11:20: none to drive to); two hours cost little more.
PARK_WINDOW = 'PT2H'
PARK_KEEP = 4          # drive + park + ride connections kept, taking turns between the places they park at
TOWN_SPEED = 7         # m/s from where OTP stops the car to the car park
WALK_DETOUR = 1.3      # a walk to a car park is this much longer than the straight line
_drive_cache: dict[str, tuple[float, dict]] = {}


def _spot(place: dict) -> dict:
    return {'label': place['name'], 'location': {'coordinate': {'latitude': place['latitude'], 'longitude': place['longitude']}}}


def _retime(legs: list[dict], start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
    """Raw OTP street legs moved in time to start at `start` or end at `end` (a drive is the same at any hour)."""
    delta = _ts(start) - _ts(legs[0]['start']['scheduledTime']) if start else _ts(end) - _ts(legs[-1]['end']['scheduledTime'])
    return [{**l, 'start': {'scheduledTime': _shift(l['start']['scheduledTime'], delta)}, 'end': {'scheduledTime': _shift(l['end']['scheduledTime'], delta)}} for l in legs]


def _drive(req: dict, origin: dict, destination: dict, ask, tried: bool = False) -> Optional[list[dict]]:
    """The raw legs of a drive (one OTP search, cached for DRIVE_TTL). From a start in a car-free zone (Prešernov trg:
    OTP finds no drive) a walk to the nearest car park within CAR_FREE_WALK and the drive from there; `tried`: the
    drive from the origin itself is known to find nothing."""
    from . import parking
    stamp = req['dateTime'].isoformat()
    starts = [] if tried else [origin]
    if (car_park := parking.nearest_drivable(origin, CAR_FREE_WALK)) and geometry.distance(
            [origin['longitude'], origin['latitude']], [car_park['lon'], car_park['lat']]) > 30:
        starts.append({'name': car_park['name'] or origin['name'], 'latitude': car_park['lat'], 'longitude': car_park['lon']})
    for start in starts:
        variables = {'origin': _spot(start), 'destination': _spot(destination), 'dateTime': {'earliestDeparture': stamp},
                     'modes': {'direct': ['CAR'], 'directOnly': True}, 'first': 1}
        key = json.dumps([round(start['latitude'], 4), round(start['longitude'], 4), round(destination['latitude'], 4), round(destination['longitude'], 4)])
        answer = ask('drive', variables, key=key, cache=_drive_cache, ttl=DRIVE_TTL)
        if answer is None:
            return None
        found = _edges(answer)
        if not found:
            continue
        legs = found[0]['node']['legs']
        if start is origin:
            return legs
        meters = geometry.distance([origin['longitude'], origin['latitude']], [start['longitude'], start['latitude']]) * WALK_DETOUR
        first = legs[0]['start']['scheduledTime']
        walk = {'mode': 'WALK', 'transitLeg': False, 'duration': meters / WALK_SPEED, 'distance': meters,
                'start': {'scheduledTime': _shift(first, -meters / WALK_SPEED)}, 'end': {'scheduledTime': first},
                'from': {'name': origin['name'], 'lat': origin['latitude'], 'lon': origin['longitude']},
                'to': {'name': start['name'], 'lat': start['latitude'], 'lon': start['longitude']}}
        return [walk, *legs]
    return None


def drive_all_the_way(req: dict, ask) -> Optional[dict]:
    """Driving all the way, as a planConnection: the drive is the same at any hour, so it is asked once per pair of
    places (cached for DRIVE_TTL) and moved to the time asked. From a start in a car-free zone it walks to the nearest
    car park first (_drive); to a car-free place OTP parks at its nearest car park and walks (fallback_search, cached
    the same way). None when OTP could not be asked."""
    legs = _drive(req, req['origin'], req['destination'], ask)
    if not legs:
        o, d = req['origin'], req['destination']
        key = json.dumps(['park', round(o['latitude'], 4), round(o['longitude'], 4), round(d['latitude'], 4), round(d['longitude'], 4)])
        answer = ask('car', fallback_search('car', req), key=key, cache=_drive_cache, ttl=DRIVE_TTL)
        if answer is None:
            return None
        found = _edges(answer)
        if not found:
            return {'planConnection': {'edges': []}}
        legs = found[0]['node']['legs']
    stamp = req['dateTime'].isoformat()
    legs = _retime(legs, end=stamp) if req['timeMode'] == 'arriveBy' else _retime(legs, start=stamp)
    return {'planConnection': {'edges': [{'node': {'walkTime': round(sum(l.get('duration') or 0 for l in legs if l['mode'] == 'WALK')), 'legs': legs}}]}}


def park_and_ride(req: dict, ask, spare: int = 2) -> list[dict]:
    """Drive + park + ride. OTP drives to a stop and rides on (CAR_DROP_OFF access), weighing every stop's real drive
    and departures at once, in two searches side by side: by bus or train, and by train only (left to itself OTP
    seldom drives past a bus stop to a station with a faster train: Kropa → Podnart), the first alone when the budget
    has `spare` queries for only one. A stop it drives to counts when the car can park there (_dropped_off); each
    connection then parks (_parked), and at most PARK_KEEP are kept, taking turns between the places. Until spec
    2026-10-19 C4 each place cost a drive and a search of the 4-query budget, so a cold plan tried one place, picked by
    a straight-line guess. A trip shorter than parking.MIN_TRIP has none."""
    from . import parking
    o, d = req['origin'], req['destination']
    if geometry.distance([o['longitude'], o['latitude']], [d['longitude'], d['latitude']]) < parking.MIN_TRIP:
        return []
    # Car + transit alone (or with the car chip) still rides buses and trains.
    modes = req['modes'] if req['modes'] & set(TRANSIT) else req['modes'] | set(TRANSIT)
    when = req['dateTime'] if req['timeMode'] == 'arriveBy' else req['dateTime'] + timedelta(seconds=PARK_LEAD)

    def variables(modes: set) -> dict:
        v = otp_variables({**req, 'modes': modes, 'via': [], 'dateTime': when, 'pageCursor': None})
        # OTP drives to a stop only together with walking ("CAR_PICKUP needs to be combined with WALK").
        v['modes'] = {**v['modes'], 'transit': {**v['modes']['transit'], 'access': ['WALK', 'CAR_DROP_OFF']}}
        v['preferences'] = {**v['preferences'], 'street': {**v['preferences']['street'], 'car': {'reluctance': PARK_CAR_RELUCTANCE}}}
        return {**v, 'first': PARK_RIDES, 'searchWindow': PARK_WINDOW}
    searches = [variables(modes)]
    if {'bus', 'rail'} <= modes and spare > 1:
        searches.append(variables(modes - {'bus'}))  # trains, and the buses that replace them
    with ThreadPoolExecutor(max_workers=len(searches), thread_name_prefix='park-search') as pool:
        answers = list(pool.map(lambda v: _closing_db(ask, 'carPark', v), searches))
    places: dict[str, Optional[dict]] = {}  # stop -> its place to park, None where the car cannot park
    by_place: dict[int, list[dict]] = {}
    seen = set()
    for answer in answers:
        for node, k, place in _dropped_off(answer, places, req):
            if (key := _leg_key(node)) not in seen:
                seen.add(key)
                by_place.setdefault(id(place), []).append(_parked(node, k, place))
    turns, out = list(by_place.values()), []
    while turns and len(out) < PARK_KEEP:
        out += [t.pop(0) for t in turns][:PARK_KEEP - len(out)]
        turns = [t for t in turns if t]
    return out


def _dropped_off(answer: Optional[dict], places: dict, req: dict) -> list[tuple[dict, int, dict]]:
    """(connection, index of its first ride, place) of a drop-off search's connections that drive to a stop where the
    car can park: MIN_DRIVE to MAX_DRIVE from the origin, with a public car park in walking distance, or a railway
    station (parking.place_at). Those that walk to their first stop are plain public transport. `places` keeps each
    stop's place for the next answer."""
    from . import parking
    origin = [req['origin']['longitude'], req['origin']['latitude']]
    out = []
    for edge in _edges(answer) if answer else []:
        legs = edge['node']['legs']
        k = next((i for i, l in enumerate(legs) if l.get('transitLeg')), None)
        if not k or not any(l['mode'] == 'CAR' for l in legs[:k]):
            continue
        board = legs[k]['from']
        stop_id = (board.get('stop') or {}).get('gtfsId')
        if stop_id not in places:
            stop = {'id': stop_id, 'name': board['name'], 'latitude': board['lat'], 'longitude': board['lon']}
            far = geometry.distance(origin, [board['lon'], board['lat']])
            places[stop_id] = parking.place_at(stop, 'rail' if legs[k]['mode'] == 'RAIL' else 'bus') if parking.MIN_DRIVE <= far <= parking.MAX_DRIVE else None
        if places[stop_id]:
            out.append((edge['node'], k, places[stop_id]))
    return out


def _parked(node: dict, k: int, place: dict) -> dict:
    """A drop-off connection that parks: OTP's drive to the stop carries on to the place's car park (at TOWN_SPEED),
    PARK_SECONDS before a walk from there reaches the stop when OTP's own walk did."""
    from . import parking
    legs = node['legs']
    park, board = place['parking'], legs[k]['from']
    reach = legs[k - 1]['end']['scheduledTime']
    meters = geometry.distance([park['lon'], park['lat']], [board['lon'], board['lat']]) * WALK_DETOUR
    walk = {'mode': 'WALK', 'transitLeg': False, 'duration': meters / WALK_SPEED, 'distance': meters,
            'start': {'scheduledTime': _shift(reach, -meters / WALK_SPEED)}, 'end': {'scheduledTime': reach},
            'from': {'name': park['name'], 'lat': park['lat'], 'lon': park['lon']}, 'to': board}
    last = max(i for i in range(k) if legs[i]['mode'] == 'CAR')
    car = legs[last]
    stopped, there = [car['to']['lon'], car['to']['lat']], [park['lon'], park['lat']]
    extra = geometry.distance(stopped, there) * parking.DETOUR
    line = mapping.decode_polyline((car.get('legGeometry') or {}).get('points') or '') or [[car['from']['lon'], car['from']['lat']], stopped]
    car = {**car, 'duration': (car.get('duration') or 0) + extra / TOWN_SPEED, 'distance': (car.get('distance') or 0) + extra,
           'end': {'scheduledTime': _shift(car['end']['scheduledTime'], extra / TOWN_SPEED)},
           'legGeometry': {'points': mapping.encode_polyline([*line, there])},
           'to': {**car['to'], 'name': park['name'], 'lat': park['lat'], 'lon': park['lon'], 'vehicleParking': {'name': park['name']}}}
    drive = _retime([*legs[:last], car], end=_shift(walk['start']['scheduledTime'], -PARK_SECONDS))
    out = [*drive, walk, *legs[k:]]
    return {'node': {**node, 'walkTime': round(sum(l.get('duration') or 0 for l in out if l['mode'] == 'WALK')), 'legs': out}}


def _leg_key(node: dict) -> str:
    return '|'.join(f"{l.get('mode')}:{(l.get('trip') or {}).get('gtfsId')}@{l['start']['scheduledTime']}" for l in node.get('legs') or [])


def _closing_db(fn, *args):
    """fn(*args) in a pool thread, closing any database connection the thread opened (Django keeps one per thread)."""
    from django.db import connections
    try:
        return fn(*args)
    finally:
        connections.close_all()


def with_extras(data: dict, req: dict, query, budget: int = MAX_OTP_QUERIES) -> dict:
    """The main search's answer with the connections of extra_searches added after OTP's own (repeats dropped).
    `budget`: OTP queries left for this request; a cached answer costs none. A failed extra search only loses its
    connections. Drive + park + ride is park_and_ride's own two searches (OTP's own car park search knows few car
    parks)."""
    searches = extra_searches(req)
    if not searches:
        return data
    edges = list(_edges(data))
    seen = {_leg_key(e['node']) for e in edges}
    left = [budget]
    lock = threading.Lock()  # the searches run side by side and share the budget

    def ask(kind: str, variables: dict, key: Optional[str] = None, cache: dict = _extra_cache, ttl: float = EXTRA_TTL) -> Optional[dict]:
        key = key or hashlib.sha1(json.dumps(variables, sort_keys=True).encode()).hexdigest()
        with lock:
            hit = cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
            if left[0] <= 0:
                return None
            left[0] -= 1
        try:
            answer = query(PLAN_Q, variables)
        except UpstreamError as e:
            logger.info('Extra %s search failed: %r', kind, e)
            return None
        with lock:
            cache[key] = (time.monotonic(), answer)
            if len(cache) > 500:
                for k, _ in sorted(cache.items(), key=lambda kv: kv[1][0])[:250]:
                    cache.pop(k, None)
        return answer

    def run(kind: str, variables: dict) -> Optional[dict]:
        if kind == 'car':  # one drive per pair of places, at any hour
            return drive_all_the_way(req, ask)
        if kind == 'carPark':
            return {'planConnection': {'edges': park_and_ride(req, ask, spare=left[0])}}
        return ask(kind, variables)

    if len(searches) == 1:
        found = [run(*searches[0])]
    else:  # independent: side by side, their connections still in this order
        with ThreadPoolExecutor(max_workers=len(searches), thread_name_prefix='extra-search') as pool:
            found = list(pool.map(lambda s: _closing_db(run, *s), searches))
    for extra in found:
        if extra is None:
            continue
        for e in _edges(extra):
            if _leg_key(e['node']) not in seen:
                seen.add(_leg_key(e['node']))
                edges.append(e)
    connection = dict(data.get('planConnection') or {})
    connection['edges'] = edges
    return {**data, 'planConnection': connection}


def search(req: dict, query) -> dict:
    """OTP's connections for the request. Fewer than asked for, from a window shorter than the rest of the day: ask
    again over the whole day, so every connection that day counts, the nearest to the time first (OTP keeps the
    earliest departures, or the latest arrivals). A page of earlier or later connections keeps its cursor's window.
    `searchShift` (s, journey_legs.search_gain): OTP is asked that much earlier (departing) or later (arriving), for
    trains whose replacement bus leaves later or arrives earlier than the train would; within_time drops the rest.
    When that leaves less than a page (a city trip near the station fills OTP's page before the asked time), the
    search at the asked time is made too and comes first: on 20 Oct Tivoli → Fužine at 08:00 was otherwise empty."""
    variables = otp_variables(req)
    shift = 0 if req.get('pageCursor') else round(req.get('searchShift') or 0)
    shifted = None
    if shift:
        moved = req['dateTime'] + timedelta(seconds=shift if req['timeMode'] == 'arriveBy' else -shift)
        shifted = query(PLAN_Q, {**variables, 'dateTime': {'latestArrival' if req['timeMode'] == 'arriveBy' else 'earliestDeparture': moved.isoformat()}})
        if _in_time(shifted, req) >= variables['first']:
            return shifted
    data = query(PLAN_Q, variables)
    if req.get('pageCursor'):
        return data
    used = _seconds(((data.get('planConnection') or {}).get('pageInfo') or {}).get('searchWindowUsed'))
    window = day_window(req)
    if used and window > used and len(_edges(data)) < variables['first']:
        data = query(PLAN_Q, {**variables, 'searchWindow': f'PT{window}S'})
    if shifted is None:
        return data
    edges = list(_edges(data))
    seen = {_leg_key(e['node']) for e in edges}
    edges += [e for e in _edges(shifted) if _leg_key(e['node']) not in seen]
    return {**data, 'planConnection': {**(data.get('planConnection') or {}), 'edges': edges}}


def _in_time(data: dict, req: dict) -> int:
    """How many of OTP's connections keep to the asked time with their own times (within_time; a train its bus
    replaces may still turn out to fit)."""
    asked = req['dateTime'].timestamp()
    if req['timeMode'] == 'arriveBy':
        return sum(_when(e['node']['legs'][-1]['end']) <= asked + TIME_SLACK for e in _edges(data))
    return sum(_when(e['node']['legs'][0]['start']) >= asked - TIME_SLACK for e in _edges(data))


ROUND_TRIP_METERS = 300  # a destination this close to the start (with stops between) is a round trip
ROUND_TRIP_RETURNS = 12  # return connections planned to pair with the outbound ones


def _same_place(a: dict, b: dict) -> bool:
    if a.get('stopId') and b.get('stopId'):
        from .sources import stop_group
        if a['stopId'] == b['stopId'] or b['stopId'] in stop_group(a['stopId']):
            return True
    return geometry.distance([a['longitude'], a['latitude']], [b['longitude'], b['latitude']]) <= ROUND_TRIP_METERS


WIDER_CURSOR = 'wider:'  # a page of connections found with wider limits: its earlier and later pages keep them


def plan(req: dict, query) -> dict:
    """OTP's planConnection for the request (see _plan). Nothing within the usual limits that day: ask again as Insane
    mode would (brisk walking, so a station further away is in reach, any number of transfers, no transfer slack) and
    mark the answer `wider`; its transfers are still rated against the rider's buffer (build_journeys). Kropa →
    Ljubljana after the last bus (17:29) is then a walk to the train at Otoče instead of nothing."""
    if not set(req['modes']) & (set(TRANSIT) | RIDE_MODES):
        return {'planConnection': {'edges': [], 'pageInfo': {}}}
    cursor = req.get('pageCursor') or ''
    if cursor.startswith(WIDER_CURSOR):
        return {**_plan({**req, 'pageCursor': cursor[len(WIDER_CURSOR):], 'wider': True}, query), 'wider': True}
    data = _plan(req, query)
    if _edges(data) or req.get('riskMode') == 'insane' or cursor:
        return data
    wider = _plan({**req, 'wider': True}, query)
    return {**wider, 'wider': True} if _edges(wider) else data


def _plan(req: dict, query) -> dict:
    """OTP's planConnection for the request. Repeated places are fine: a round trip (back to where it starts, through stops
    on the way) is planned in two parts, since OTP sees a trip to its own start and plans nothing
    ("trivial distance"): to the last stop, then back; each connection there gets the first return
    it can make (the last that fits, arriving by a time). Paging follows the part that is paged."""
    # A stop at the place just before it (or at the destination) adds nothing, and OTP refuses
    # legs of trivial length: leave it out.
    via, last = [], req['origin']
    for v in req['via']:
        if not _same_place(last, v):
            via.append(v)
            last = v
    if via and _same_place(via[-1], req['destination']):
        via.pop()
    req = {**req, 'via': via}
    if not req['via'] or not _same_place(req['origin'], req['destination']):
        return search(req, query)
    turn = req['via'][-1]
    out_req = {**req, 'destination': turn, 'via': req['via'][:-1]}
    back_req = {**req, 'origin': turn, 'via': []}
    slack = max(0, req['minTransferSeconds'])
    edges = _edges
    start = lambda node: _when(node['legs'][0]['start'])
    end = lambda node: _when(node['legs'][-1]['end'])

    def join(first: dict, second: dict) -> dict:
        return {'node': {**first, 'walkTime': (first.get('walkTime') or 0) + (second.get('walkTime') or 0), 'legs': first['legs'] + second['legs']}}

    if req['timeMode'] == 'arriveBy':
        paged = search(back_req, query)
        backs = edges(paged)
        if not backs:
            return paged
        latest = max(start(e['node']) for e in backs) - slack
        out_vars = otp_variables({**out_req, 'pageCursor': None, 'dateTime': datetime.fromtimestamp(latest, req['dateTime'].tzinfo)})
        out_vars['first'] = ROUND_TRIP_RETURNS
        outs = [e['node'] for e in edges(query(PLAN_Q, out_vars))]
        joined = []
        for back in backs:
            fits = [o for o in outs if end(o) + slack <= start(back['node'])]
            if fits:
                joined.append(join(max(fits, key=start), back['node']))
    else:
        paged = search(out_req, query)
        outs = edges(paged)
        if not outs:
            return paged
        earliest = min(end(e['node']) for e in outs) + slack
        back_vars = otp_variables({**back_req, 'pageCursor': None, 'dateTime': datetime.fromtimestamp(earliest, req['dateTime'].tzinfo)})
        back_vars['first'] = ROUND_TRIP_RETURNS
        backs = [e['node'] for e in edges(query(PLAN_Q, back_vars))]
        joined = []
        for out in outs:
            fits = [b for b in backs if start(b) >= end(out['node']) + slack]
            if fits:
                joined.append(join(out['node'], min(fits, key=end)))
    return {'planConnection': {**paged['planConnection'], 'edges': joined}}


def page_info(data: dict) -> dict:
    """Cursors for the connections before and after these (null when OTP has none)."""
    info = (data.get('planConnection') or {}).get('pageInfo') or {}
    mark = WIDER_CURSOR if data.get('wider') else ''
    return {'previous': mark + info['startCursor'] if info.get('hasPreviousPage') and info.get('startCursor') else None,
            'next': mark + info['endCursor'] if info.get('hasNextPage') and info.get('endCursor') else None}


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _placed_leg(l: dict, updates: dict) -> dict:
    """OTP's transit leg `l` with the live times of the trip update about its run (mapping.update_run): OTP puts one
    that names no start date on the trip's run of its own day, so just after midnight last night's late train had
    its timetable and tonight's run its delay."""
    trip = l.get('trip') or {}
    first = (trip.get('departureStoptime') or {}).get('scheduledDeparture')
    update = updates.get(trip.get('gtfsId'))
    if not update or not isinstance(first, int):
        return l
    start, end = _ts(l['start']['scheduledTime']), _ts(l['end']['scheduledTime'])
    begin = int(datetime.fromtimestamp(start - first, LOCAL).replace(hour=0, minute=0, second=0).timestamp()) + first
    about = mapping.update_day(update, begin, int(end))
    if about == -1:
        times = (None, None)
    elif about != 0 or (l['start'].get('estimated') or {}).get('time'):
        return l
    else:
        at_stop = {u.get('stopId'): mapping.believable(mapping.update_delay(u), False) for u in update.get('updates') or []}
        board, alight = (at_stop.get((l[k].get('stop') or {}).get('gtfsId')) for k in ('from', 'to'))
        if board is None:
            return l
        times = (start + board, end + (board if alight is None else alight))
    return {**l, **{k: {**l[k], 'estimated': {'time': datetime.fromtimestamp(t, LOCAL).isoformat()} if t is not None else None}
                    for k, t in zip(('start', 'end'), times)}}


def _leg_mode(leg: dict) -> str:
    if leg.get('transitLeg'):
        return mapping.mode_of((leg.get('route') or {}).get('mode') or leg.get('mode'))
    return {'BICYCLE': 'bike', 'SCOOTER': 'scooter', 'CAR': 'car'}.get(leg.get('mode'), 'walk')


def _leg_place(end: dict, override: Optional[dict]) -> dict:
    stop = end.get('stop') or {}
    lat, lon = stopfix.position(stop.get('gtfsId'), end['lat'], end['lon'])
    place = {'name': (override or {}).get('name') or end.get('name') or 'Location', 'latitude': lat, 'longitude': lon,
             'kind': 'station' if stop.get('gtfsId') else (override or {}).get('kind', 'address')}
    if stop.get('gtfsId'):
        place['stopId'] = place['id'] = stop['gtfsId']
    return place


def _headsign(leg: dict) -> Optional[str]:
    """Where the vehicle goes. SŽ headsigns repeat the route ("Ljubljana - Ilirska Bistrica"): keep the end."""
    text = (leg.get('headsign') or (leg.get('trip') or {}).get('tripHeadsign') or '').strip()
    end = text.split(' - ')[-1].strip() or None if text else None
    if abroad.is_abroad_stop(end):
        return abroad.place(end)
    if mapping.mode_of((leg.get('route') or {}).get('mode')) == 'rail':  # an international train: its end abroad
        return abroad.train_ends(mapping.route_name(leg.get('route') or {}), None, end)[1] or end
    return end


def _stop_names(raw: dict) -> set[str]:
    return {mapping.fold(s['name']) for s in [raw['from'], *(raw.get('intermediatePlaces') or []), raw['to']] if s.get('name')}


def _matched_alerts(raw: dict, leg: dict, alerts: list[dict]) -> list[str]:
    """Notices that concern this ride: its route or a stop it uses, or (SŽ notices without entities, replacement
    notices for replacement buses) a section it travels. See leg_alerts.match."""
    stops = [raw['from'], *(raw.get('intermediatePlaces') or []), raw['to']]
    stop_ids = {(s.get('stop') or {}).get('gtfsId') for s in stops} - {None}
    stop_names = _stop_names(raw)
    context = {**leg, '_start': _ts(leg['effectiveDeparture']), '_end': _ts(leg['effectiveArrival'])}
    return leg_alerts.match(context, stop_ids, stop_names, alerts)


REPLACEMENT_WALK = (30, 1500)  # m: a replacement stop closer than this is "at the station"; further is not its stop
WALK_SPEED = 1.2              # m/s, with luggage and a station to cross


def _shift(stamp: str, seconds: float) -> str:
    return (datetime.fromisoformat(stamp) + timedelta(seconds=round(seconds))).isoformat()


def _replacement_stop(place: dict) -> Optional[dict]:
    """Where SŽ's replacement buses leave from at this station, when that is beside it (stop_overrides.csv)."""
    if not place.get('stopId'):
        return None
    from .sources import stop_group
    here = [place['longitude'], place['latitude']]
    for r in stopfix.replacement_stops(stop_group(place['stopId'])):
        d = geometry.distance(here, [r['lon'], r['lat']])
        if REPLACEMENT_WALK[0] < d <= REPLACEMENT_WALK[1]:
            return {'place': {'name': stopfix.stop_name(r['label'], place['name']), 'latitude': r['lat'], 'longitude': r['lon'], 'kind': 'station',
                              'stopId': place['stopId'], 'id': place['stopId']}, 'seconds': d / WALK_SPEED}
    return None


def _known_stop(place: dict, at: Optional[dict]) -> Optional[dict]:
    """The spot a bus leg already knows it stops at (journey_legs.py), as a walk from the station when it is beside it."""
    if not at or at.get('lat') is None:
        return None
    d = geometry.distance([place['longitude'], place['latitude']], [at['lon'], at['lat']])
    if not REPLACEMENT_WALK[0] < d <= REPLACEMENT_WALK[1]:
        return None
    name = stopfix.stop_name(at['replacementLabel'], place['name']) if at.get('replacementLabel') else (f'{place["name"]} · {at["bay"]}' if at.get('bay') else place['name'])
    return {'place': {'name': name, 'latitude': at['lat'], 'longitude': at['lon'], 'kind': 'station',
                      **({'stopId': place['stopId'], 'id': place['stopId']} if place.get('stopId') else {})}, 'seconds': d / WALK_SPEED}


def _walk_leg(base_id: str, origin: dict, destination: dict, start: str, seconds: float) -> dict:
    return {'id': base_id, 'mode': 'walk', 'operatorId': None, 'routeId': None, 'tripId': None, 'routeName': '', 'headsign': None,
            'origin': origin, 'destination': destination,
            'scheduledDeparture': start, 'scheduledArrival': _shift(start, seconds), 'effectiveDeparture': start, 'effectiveArrival': _shift(start, seconds),
            'geometry': [[origin['longitude'], origin['latitude']], [destination['longitude'], destination['latitude']]],
            'delaySeconds': None, 'delayProvenance': None, 'canceled': False, 'alertIds': []}


def _walk_meta(seconds: float) -> dict:
    return {'transit': False, 'interline': False, 'duration': seconds, 'realtime': False, 'platform': None}


def replacement_walks(legs: list[dict], meta: list[dict]) -> tuple[list[dict], list[dict]]:
    """Replacement buses that stop beside the station (not where OTP puts them, at the station itself):
    the bus leg starts or ends at that stop, and the walk between it and the station is its own leg
    (or joins the walk already there)."""
    out, out_meta = [], []
    for leg, m in zip(legs, meta):
        leg = dict(leg)
        board_at, alight_at = leg.pop('_boardAt', None), leg.pop('_alightAt', None)
        replacement = leg.get('replacement')
        board = (_known_stop(leg['origin'], board_at) if board_at else _replacement_stop(leg['origin'])) if replacement else None
        alight = (_known_stop(leg['destination'], alight_at) if alight_at else _replacement_stop(leg['destination'])) if replacement else None
        if board:
            station = leg['origin']
            leg = {**leg, 'origin': board['place'], 'geometry': [[board['place']['longitude'], board['place']['latitude']], *leg['geometry']]}
            start = _shift(leg['effectiveDeparture'], -board['seconds'])
            out.append(_walk_leg(f'{leg["id"]}-to', station, board['place'], start, board['seconds']))
            out_meta.append(_walk_meta(board['seconds']))
        follow = None
        if alight:
            station = leg['destination']
            leg = {**leg, 'destination': alight['place'], 'geometry': [*leg['geometry'], [alight['place']['longitude'], alight['place']['latitude']]]}
            follow = (_walk_leg(f'{leg["id"]}-from', alight['place'], station, leg['effectiveArrival'], alight['seconds']), _walk_meta(alight['seconds']))
        out.append(leg)
        out_meta.append(m)
        if follow:
            out.append(follow[0])
            out_meta.append(follow[1])
    # A walk that now meets another walk at the station is one walk.
    merged, merged_meta = [], []
    for leg, m in zip(out, out_meta):
        if merged and leg['mode'] == 'walk' and merged[-1]['mode'] == 'walk':
            merged[-1], merged_meta[-1] = _joined_walk(merged[-1], merged_meta[-1], leg, m, ride_before=len(merged) > 1)
            continue
        merged.append(leg)
        merged_meta.append(m)
    return merged, merged_meta


def _joined_walk(first: dict, first_meta: dict, second: dict, second_meta: dict, ride_before: bool) -> tuple[dict, dict]:
    """Two walks meeting at a station as one. It goes straight to the replacement stop where the walk to the station
    passes it (Podnart: the bus stop's walk went up to the station and our walk came back down 60 m to the stop
    beside it), or from it where the walk on passes it. It lasts as long as the walking does: the wait for the bus
    comes after it, not inside it (after a ride it starts when the ride ends, else it ends when the next one leaves;
    joined end to end, a 2-minute walk read "1 h 39 min" while the replacement bus was an hour away)."""
    a, b = first['geometry'], second['geometry']
    seconds_a, seconds_b = first_meta['duration'], second_meta['duration']
    coords = [*a, *b[1:]]
    if second['id'].endswith('-to') and len(a) >= 2:  # station -> its replacement stop, after a walk to the station
        stop = second['destination']
        cum = geometry.cumulative(a)
        along, off = geometry.project_stops(a, [{'lat': stop['latitude'], 'lon': stop['longitude']}])[0]
        if cum[-1] and along + off < cum[-1] + geometry.distance(a[-1], b[-1]):
            coords = [*geometry.slice_between(a, cum, 0, along), [stop['longitude'], stop['latitude']]]
            seconds_a, seconds_b = seconds_a * along / cum[-1], off / WALK_SPEED
    elif first['id'].endswith('-from') and len(b) >= 2:  # replacement stop -> station, then a walk on from the station
        stop = first['origin']
        cum = geometry.cumulative(b)
        along, off = geometry.project_stops(b, [{'lat': stop['latitude'], 'lon': stop['longitude']}])[0]
        if cum[-1] and off + cum[-1] - along < geometry.distance(a[0], a[-1]) + cum[-1]:
            coords = [[stop['longitude'], stop['latitude']], *geometry.slice_between(b, cum, along, cum[-1])]
            seconds_a, seconds_b = off / WALK_SPEED, seconds_b * (cum[-1] - along) / cum[-1]
    seconds = seconds_a + seconds_b
    times = {}
    for kind in ('scheduled', 'effective'):
        if ride_before:
            start = first[f'{kind}Departure']
            times.update({f'{kind}Departure': start, f'{kind}Arrival': _shift(start, seconds)})
        else:
            end = second[f'{kind}Arrival']
            times.update({f'{kind}Departure': _shift(end, -seconds), f'{kind}Arrival': end})
    return {**first, 'destination': second['destination'], 'geometry': coords, **times}, {**first_meta, 'duration': seconds}


SNAP_METERS = 120     # a walk between two points this close ...
SNAP_DETOUR = 3       # ... over a path this many times longer (and SNAP_EXTRA m more) is a bad link in OTP's street graph
SNAP_EXTRA = 100
SNAP_FACTOR = 1.4     # the snapped walk's length: the straight line and a little


def sane_walks(legs: list[dict], meta: list[dict]) -> None:
    """Walks OTP routes around a station's link in its street graph: Lesce-Bled's station and the Lesce ŽP stop in
    front of it are 47 m apart, and OTP walked 298 m, down the road and back. A walk between points SNAP_METERS
    apart over more than SNAP_DETOUR times that is drawn straight and timed as SNAP_FACTOR times it (rule of the
    spec 2026-10-19 A2: a transfer walk over 3x the straight distance is a bug). Longer walks keep OTP's path."""
    for n, (leg, m) in enumerate(zip(legs, meta)):
        if leg['mode'] != 'walk' or len(leg['geometry']) < 2:
            continue
        ends = [[leg['origin']['longitude'], leg['origin']['latitude']], [leg['destination']['longitude'], leg['destination']['latitude']]]
        straight, path = geometry.distance(*ends), geometry.cumulative(leg['geometry'])[-1]
        if straight > SNAP_METERS or path < SNAP_DETOUR * straight or path - straight < SNAP_EXTRA:
            continue
        seconds = max(30.0, straight * SNAP_FACTOR / WALK_SPEED)
        legs[n] = {**leg, 'geometry': ends}
        if all(l['mode'] == 'walk' for l in legs[:n]):
            for kind in ('scheduled', 'effective'):  # before the first ride: leave later, not wait longer
                legs[n][f'{kind}Departure'] = _shift(leg[f'{kind}Arrival'], -seconds)
        else:
            for kind in ('scheduled', 'effective'):
                legs[n][f'{kind}Arrival'] = _shift(leg[f'{kind}Departure'], seconds)
        meta[n] = {**m, 'duration': seconds}


def _when(end: dict) -> float:
    return _ts((end.get('estimated') or {}).get('time') or end['scheduledTime'])


def bet_on_delays(data: dict, req: dict, query, tries: int = 3) -> dict:
    """Insane mode with a negative allowance: for the first transfer of the best few connections, plan
    again from the transfer stop starting `allowance` before the rider could make it there, and add the
    result when it arrives sooner. Its first transfer then leaves up to a minute "too early"; it is
    labelled with its exact slack (build_journeys). One extra OTP request per connection tried."""
    allowance = req['minTransferSeconds']
    if req.get('riskMode') != 'insane' or allowance >= 0 or req['timeMode'] != 'departAt':
        return data
    edges = (data.get('planConnection') or {}).get('edges') or []
    extra = []
    for edge in edges[:tries]:
        legs = edge['node'].get('legs') or []
        transit = [i for i, l in enumerate(legs) if l.get('transitLeg')]
        if len(transit) < 2:
            continue
        k = transit[0]
        stop = (legs[k]['to'].get('stop') or {}).get('gtfsId')
        if not stop:
            continue
        arrive = _when(legs[k]['end'])
        walk = sum(l.get('duration') or 0 for l in legs[k + 1:transit[1]])
        start = datetime.fromtimestamp(arrive + walk + allowance, tz=req['dateTime'].tzinfo)
        sub_req = {**req, 'origin': {'name': legs[k]['to'].get('name') or 'Stop', 'stopId': stop, 'latitude': legs[k]['to']['lat'],
                                     'longitude': legs[k]['to']['lon']},
                   'via': [], 'dateTime': start, 'pageCursor': None}
        try:
            sub = query(PLAN_Q, otp_variables(sub_req))
        except Exception:  # noqa: BLE001 - the bet is optional; the normal results stand
            continue
        nodes = [e['node'] for e in (sub.get('planConnection') or {}).get('edges') or [] if e['node'].get('legs')]
        best = min(nodes, key=lambda n: _when(n['legs'][-1]['end']), default=None)
        if not best or _when(best['legs'][-1]['end']) >= _when(legs[-1]['end']):
            continue
        boards = next((l for l in best['legs'] if l.get('transitLeg')), None)
        if boards and _when(boards['start']) < arrive + walk:  # really uses the minute OTP would not
            extra.append({'node': {'walkTime': (edge['node'].get('walkTime') or 0) + (best.get('walkTime') or 0), 'legs': legs[:k + 1] + best['legs']}})
    if extra:
        data = {**data, 'planConnection': {**data['planConnection'], 'edges': edges + extra}}
    return data


TIME_SLACK = 60  # s a journey may start before (or end after) the asked time, as OTP's own rounding does


def within_time(journeys: list[dict], req: dict) -> list[dict]:
    """The journeys that leave at or after the asked time (departing) or arrive by it (arriving), once replacement
    buses ride with their own times: a bus leaving 20 minutes before its train cannot be caught by someone who
    leaves at the train's time, and one arriving after the asked time is late. Only those with a replacement bus,
    and every one when the search was widened (searchShift); pages of earlier or later connections are left as
    they are (they lie outside the time on purpose)."""
    if req.get('pageCursor'):
        return journeys
    widened = bool(req.get('searchShift'))
    asked = req['dateTime'].timestamp()

    def fits(j: dict) -> bool:
        if not widened and not any(l.get('replacement') for l in j['legs']):
            return True
        if req['timeMode'] == 'arriveBy':
            return _ts(j['effectiveArrival']) <= asked + TIME_SLACK
        return _ts(j['effectiveDeparture']) >= asked - TIME_SLACK
    return [j for j in journeys if fits(j)]


def by_arrival(journeys: list[dict]) -> list[dict]:
    """Insane order: earliest arrival first, then the latest departure."""
    return sorted(journeys, key=lambda j: (_ts(j['effectiveArrival']), -_ts(j['effectiveDeparture'])))


def build_journeys(data: dict, req: dict, alerts: list[dict], plan_for=None) -> list[dict]:
    """`plan_for(when)`: the replacement plan of the service day at `when` (scheduled.plan_at); with it,
    train legs over a stretch a bus replaces that day ride the bus there (journey_legs.py)."""
    canonical = {alias: a['id'] for a in alerts for alias in a.get('_aliases', [a['id']])}
    alert_titles = {a['id']: a['title'] for a in alerts}
    by_id = {a['id']: a for a in alerts}
    journeys = []
    deadline = time.monotonic() + ROAD_WAIT
    seen_bays: dict = {}  # station -> its PlatformSeen rows, read once per request
    from_town, to_town = town_stops(req['origin']), town_stops(req['destination'])
    from . import trainlive
    updates = trainlive.trip_updates()
    for edge in (data.get('planConnection') or {}).get('edges') or []:
        node = edge['node']
        raw = node.get('legs') or []
        if not raw:
            continue
        # A town (Kranj: railway and bus station) is planned from between its stations: the journey starts at the
        # one it leaves from, and ends at the one it arrives at, without the walk from or to that middle.
        trimmed = 0.0
        if len(raw) > 1 and not raw[0].get('transitLeg') and (raw[0]['to'].get('stop') or {}).get('gtfsId') in from_town:
            trimmed += raw[0].get('duration') or 0
            raw = raw[1:]
        if len(raw) > 1 and not raw[-1].get('transitLeg') and (raw[-1]['from'].get('stop') or {}).get('gtfsId') in to_town:
            trimmed += raw[-1].get('duration') or 0
            raw = raw[:-1]
        # Still a walk from or to the middle: the journey uses another stop ("Kranj Globus"), not the town's stations.
        stray = len(raw) > 1 and ((from_town and not raw[0].get('transitLeg')) or (to_town and not raw[-1].get('transitLeg')))
        key = hashlib.sha1('|'.join(f'{(l.get("trip") or {}).get("gtfsId")}@{l["start"]["scheduledTime"]}' for l in raw).encode()).hexdigest()[:16]
        legs, meta = [], []
        raw = [_placed_leg(l, updates) if l.get('transitLeg') else l for l in raw]
        for i, l in enumerate(raw):
            transit = bool(l.get('transitLeg'))
            start_est, end_est = (l['start'].get('estimated') or {}).get('time'), (l['end'].get('estimated') or {}).get('time')
            route = l.get('route') or {}
            geometry = mapping.decode_polyline((l.get('legGeometry') or {}).get('points') or '')
            if transit and _leg_mode(l) == 'bus':
                stops = [l['from'], *(l.get('intermediatePlaces') or []), l['to']]
                # An SŽ replacement bus comes with the railway's shape: route it on the roads.
                geometry, _ = roads.repair(geometry, [s for s in stops if s.get('lat') is not None], deadline,
                                           road_only=mapping.is_replacement(route))
            if transit and _leg_mode(l) == 'rail':
                geometry = geometry_lib.trim_spurs(geometry)
            geometry = mapping.thin(geometry)
            if len(geometry) < 2:
                geometry = [[l['from']['lon'], l['from']['lat']], [l['to']['lon'], l['to']['lat']]]
            legs.append({
                'id': f'leg:{key}-{i}', 'mode': _leg_mode(l),
                'operatorId': (route.get('agency') or {}).get('gtfsId') if transit else None,
                'routeId': route.get('gtfsId') if transit else None,
                'tripId': (l.get('trip') or {}).get('gtfsId') if transit else None,
                'routeName': mapping.route_name(route) if transit else '',
                'headsign': _headsign(l) if transit else None,
                # A town's station keeps its own name ("Kranj AP"), not the town's.
                'origin': _leg_place(l['from'], req['origin'] if i == 0 and not from_town else None),
                'destination': _leg_place(l['to'], req['destination'] if i == len(raw) - 1 and not to_town else None),
                'scheduledDeparture': l['start']['scheduledTime'], 'scheduledArrival': l['end']['scheduledTime'],
                'effectiveDeparture': start_est or l['start']['scheduledTime'], 'effectiveArrival': end_est or l['end']['scheduledTime'],
                'geometry': geometry,
                'delaySeconds': round(_ts(start_est) - _ts(l['start']['scheduledTime'])) if transit and start_est else None,
                'delayProvenance': 'predicted' if transit and start_est else None,
                'canceled': l.get('realtimeState') == 'CANCELED',
                'stopCount': len(l.get('intermediatePlaces') or []) + 1 if transit else None,
                **({'rental': rental} if (rental := sharing.leg_rental(l)) else {}),
                **({'car': driving.leg_car(l, geometry)} if l.get('mode') == 'CAR' else {}),
                'alertIds': [canonical.get(f'alert:{a["id"]}', f'alert:{a["id"]}') for a in l.get('alerts') or []],
            })
            if transit and mapping.is_replacement(route):
                legs[-1]['replacement'] = True
            if transit:
                legs[-1]['alertIds'].extend(_matched_alerts(l, legs[-1], alerts))
                # OTP attaches a route's notices for their whole window and the whole line; keep those for
                # this ride's days and section.
                start, end = _ts(legs[-1]['effectiveDeparture']), _ts(legs[-1]['effectiveArrival'])
                names = _stop_names(l)
                legs[-1]['alertIds'] = [i for i in legs[-1]['alertIds'] if i not in by_id or leg_alerts.concerns(by_id[i], start, end, names)]
            # Notices OTP knows that the alert list leaves out (expired, merged) can't be shown: don't count them.
            legs[-1]['alertIds'] = [i for i in legs[-1]['alertIds'] if i in by_id]
            legs[-1]['alertIds'] = list(dict.fromkeys(legs[-1]['alertIds']))
            if legs[-1]['stopCount'] is None:
                del legs[-1]['stopCount']
            platform = (l['from'].get('stop') or {}).get('platformCode')
            board = (l['from'].get('stop') or {}).get('gtfsId')
            usual = False
            if transit and not platform and board in platforms.STATIONS:
                # Bus station bays, as the station's board announced them (platforms.learn), else the
                # bay the destination usually leaves from (marked as such).
                if board not in seen_bays:
                    seen_bays[board] = platforms.station_seen(board)
                platform, usual = platforms.platform_for(board, _ts(l['start']['scheduledTime']), _headsign(l) or '', seen_bays[board])
            elif transit and not platform and legs[-1]['mode'] == 'rail':
                # The train's track at the station it is boarded (tracks.py).
                platform, usual = tracks.tracks.track(legs[-1]['routeName'], board or '', _ts(l['start']['scheduledTime']))
            if platform:
                legs[-1]['platform'] = platform
                if usual:
                    legs[-1]['platformUsual'] = True
            trip = l.get('trip') or {}
            meta.append({'transit': transit, 'interline': bool(l.get('interlineWithPreviousLeg')), 'duration': l.get('duration') or 0,
                         'realtime': bool(start_est), 'platform': platform, 'blockId': trip.get('blockId'),
                         'tripStart': (trip.get('departureStoptime') or {}).get('scheduledDeparture')})
        # Contract 2: live, the vehicle's previous trip, or how late the departure usually is (predictions.py).
        predictions.annotate(legs, raw)
        if plan_for:
            from . import scheduled
            rewritten = journey_legs.rewrite(legs, meta, plan_for, scheduled.road_shape_of)
            if rewritten is None:
                continue  # a bus runs instead of one of its trains that day and cannot make this journey
            legs, meta = rewritten
            journey_legs.unreplaced_notices(legs, plan_for, by_id)
            journey_legs.name_replaced_trains(legs, plan_for)
        walked = sum(m['duration'] for leg, m in zip(legs, meta) if leg['mode'] == 'walk')
        legs, meta = replacement_walks(legs, meta)
        sane_walks(legs, meta)
        # The walks added to replacement stops, joined or snapped (sane_walks) change how long the walking is.
        walked = sum(m['duration'] for leg, m in zip(legs, meta) if leg['mode'] == 'walk') - walked
        for leg in legs:
            if leg['mode'] != 'walk':
                leg.setdefault('predictedDelaySeconds', leg['delaySeconds'])
                leg.setdefault('predictionBasis', 'live' if leg['delaySeconds'] is not None else None)
        transfers, previous, previous_meta, walking, lpp_since = [], None, None, 0.0, None
        for leg, m in zip(legs, meta):
            if not m['transit']:
                walking += m['duration']
                continue
            if lpp_since is None and predictions.is_lpp(leg):
                lpp_since = _ts(leg['effectiveDeparture'])  # LPP's fare window runs from the first LPP boarding
            # Contract 3: the same vehicle goes on as the next line, as learned from the vehicles (stays.py); the rider
            # stays on, perhaps with a ticket to see to. `stayLevel` is on every ride after the first (null: a change).
            level = None
            if previous is not None:
                level = leg['stayLevel'] = predictions.stay_level(previous, previous_meta, leg, m, walking)
                if level:
                    note = leg['ticketNote'] = predictions.ticket_note(previous, leg, lpp_since)
                    leg['staysOnVehicle'], leg['newTicket'] = level == 'sure', note != 'none'  # older app builds
            # Every change of vehicle is rated, tied to the leg it boards (`legId`). A `sure` stay is none: the bus
            # can't leave without you. A `likely` one is timed like any change. A change SŽ holds (train to its
            # replacement bus and back) is rated comfortable and, as before, not counted: it is one ride.
            if previous is not None and level != 'sure':
                available = _ts(leg['effectiveDeparture']) - _ts(previous['effectiveArrival'])
                # The real walk (transfer_walk.py): OTP's, plus crossing the road, changing tracks or reaching the bay.
                track = tracks.tracks.track(previous['routeName'], previous['destination'].get('stopId') or '',
                                            _ts(previous['scheduledArrival']))[0] if previous['mode'] == 'rail' else None
                required, walk_kind = transfer_walk.walk(previous, leg, walking, track)
                safety = req['minTransferSeconds']
                if leg['canceled'] or previous['canceled']:
                    status, meets = 'unknown', None
                elif m.get('held'):  # held by SŽ
                    status, meets = 'safe', True
                elif req.get('riskMode') == 'insane':
                    # Within the rider's allowance (down to -1 min) is a bet, labelled tight when under 2 min spare.
                    # Predicted delays count as live ones do: a transfer the arriving bus's usual delay breaks is missed.
                    available += predictions.transfer_shift(previous, leg)
                    meets = available >= required + safety
                    status = 'missed' if available < required + min(0, safety) else ('tight' if available < required + RISKY_TRANSFER else 'safe')
                else:
                    status, meets, _ = transfer_walk.rate(available, required, safety)
                transfers.append({'requiredSeconds': required, 'safetySeconds': safety, 'availableSeconds': round(available),
                                  'platform': m['platform'] or None, 'meetsSafetyMargin': meets, 'status': status, 'legId': leg['id'],
                                  # A4: the walk on its own (minutes in the app), what it is, and comfortable or tight.
                                  'walkSeconds': required, 'walkKind': walk_kind,
                                  **({'rating': transfer_walk.rating_of(status)} if status != 'unknown' else {}),
                                  **({'held': True} if m.get('held') else {})})
            previous, previous_meta, walking = leg, m, 0.0
        notices = []
        for leg in legs:
            for alert_id in leg['alertIds']:
                title = alert_titles.get(alert_id)
                if title and title not in notices:
                    notices.append(title)
        in_journey = [by_id[i] for i in dict.fromkeys(i for leg in legs for i in leg['alertIds']) if i in by_id]
        in_journey.sort(key=lambda a: (a.get('kind') != 'replacement', a['_from']))
        journeys.append({
            'id': f'otp:{key}', 'legs': legs, 'alerts': [mapping.public_alert(a) for a in in_journey],
            'scheduledDeparture': legs[0]['scheduledDeparture'], 'scheduledArrival': legs[-1]['scheduledArrival'],
            'effectiveDeparture': legs[0]['effectiveDeparture'], 'effectiveArrival': legs[-1]['effectiveArrival'],
            'walkSeconds': max(0, round((node.get('walkTime') or 0) - trimmed + walked)), 'transferCount': sum(1 for t in transfers if not t.get('held')),
            'transfers': transfers,
            'notices': notices[:3], 'freshness': 'live' if any(m['realtime'] for m in meta) else 'scheduled',
            '_stray': stray,
        })
    # A town means its stations: journeys through another stop only when none leaves or arrives at them.
    if not all(j['_stray'] for j in journeys):
        journeys = [j for j in journeys if not j['_stray']]
    return [{k: v for k, v in j.items() if k != '_stray'} for j in journeys]

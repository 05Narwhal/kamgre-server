"""Journey planning through OTP `planConnection`, which applies realtime delays and
cancellations, supports native via points and a minimum transfer slack."""
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional

from . import geometry, journey_legs, leg_alerts, mapping, platforms, roads, stopfix, tracks
from . import geometry as geometry_lib
from . import operators as companies

MODES = {'walk', 'bus', 'rail', 'bike', 'scooter'}
ROAD_WAIT = 4.0
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

PLAN_Q = '''query($origin: PlanLabeledLocationInput!, $destination: PlanLabeledLocationInput!, $via: [PlanViaLocationInput!],
  $dateTime: PlanDateTimeInput, $modes: PlanModesInput, $preferences: PlanPreferencesInput, $first: Int, $last: Int,
  $before: String, $after: String) {
  planConnection(origin: $origin, destination: $destination, via: $via, dateTime: $dateTime, modes: $modes, first: $first,
    last: $last, before: $before, after: $after, preferences: $preferences) {
    routingErrors { code description }
    pageInfo { startCursor endCursor hasPreviousPage hasNextPage }
    edges { node { walkTime
      legs { mode realtimeState transitLeg interlineWithPreviousLeg duration
        start { scheduledTime estimated { time } } end { scheduledTime estimated { time } }
        from { name lat lon stop { gtfsId platformCode } } to { name lat lon stop { gtfsId platformCode } }
        route { gtfsId shortName longName mode agency { gtfsId } } headsign trip { gtfsId tripHeadsign }
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
    return value


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
    if not set(modes) & set(TRANSIT):
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
    return {
        'origin': _place(body.get('origin'), 'origin'), 'destination': _place(body.get('destination'), 'destination'),
        'via': [_place(v, f'via[{i}]') for i, v in enumerate(via)], 'dateTime': when, 'timeMode': body['timeMode'],
        # Insane: no buffer, or the rider's negative allowance.
        'modes': set(modes), 'minTransferSeconds': min(0, slack) if risk == 'insane' else slack, 'riskMode': risk,
        'operators': list(dict.fromkeys(operators)), 'pageCursor': cursor, 'pageDirection': direction,
        'maxTransfers': max_transfers,
    }


def _merged(stop_id: str) -> bool:
    from .sources import stop_group
    return len(stop_group(stop_id)) > 1


def _location(place: dict) -> dict:
    # A merged station is several feed stops: start from its position so OTP may use any of them.
    if place.get('stopId') and not _merged(place['stopId']):
        return {'label': place['name'], 'location': {'stopLocation': {'stopLocationId': place['stopId']}}}
    return {'label': place['name'], 'location': {'coordinate': {'latitude': place['latitude'], 'longitude': place['longitude']}}}


def otp_variables(req: dict) -> dict:
    street = ['WALK']
    if 'bike' in req['modes']:
        street.append('BICYCLE_RENTAL')
    if 'scooter' in req['modes']:
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
            visit['stopLocationIds'] = stop_group(v['stopId'])
        else:
            visit['coordinate'] = {'latitude': v['latitude'], 'longitude': v['longitude']}
        via.append({'visit': visit})
    stamp = req['dateTime'].isoformat()
    insane = req.get('riskMode') == 'insane'
    transfer = {'slack': f'PT{max(0, req["minTransferSeconds"])}S'}
    preferences: dict = {'transit': {'transfer': transfer}}
    if insane:
        transfer.update(cost=0, maximumTransfers=INSANE_MAX_TRANSFERS[0], maximumAdditionalTransfers=INSANE_MAX_TRANSFERS[1])
        preferences['street'] = {'walk': {'speed': INSANE_WALK_SPEED}}
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
        'modes': {'direct': street, 'transit': {'access': street, 'egress': street, 'transfer': ['WALK'], 'transit': transit}},
        'preferences': preferences, 'first': count,
    }
    # Earlier / later connections: OTP pages with the cursors of the previous response.
    if req.get('pageCursor') and req.get('pageDirection') == 'earlier':
        del variables['first']
        variables.update(before=req['pageCursor'], last=count)
    elif req.get('pageCursor'):
        variables['after'] = req['pageCursor']
    return variables


ROUND_TRIP_METERS = 300  # a destination this close to the start (with stops between) is a round trip
ROUND_TRIP_RETURNS = 12  # return connections planned to pair with the outbound ones


def _same_place(a: dict, b: dict) -> bool:
    if a.get('stopId') and b.get('stopId'):
        from .sources import stop_group
        if a['stopId'] == b['stopId'] or b['stopId'] in stop_group(a['stopId']):
            return True
    return geometry.distance([a['longitude'], a['latitude']], [b['longitude'], b['latitude']]) <= ROUND_TRIP_METERS


def plan(req: dict, query) -> dict:
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
        return query(PLAN_Q, otp_variables(req))
    turn = req['via'][-1]
    out_req = {**req, 'destination': turn, 'via': req['via'][:-1]}
    back_req = {**req, 'origin': turn, 'via': []}
    slack = max(0, req['minTransferSeconds'])
    edges = lambda data: [e for e in (data.get('planConnection') or {}).get('edges') or [] if e['node'].get('legs')]
    start = lambda node: _when(node['legs'][0]['start'])
    end = lambda node: _when(node['legs'][-1]['end'])

    def join(first: dict, second: dict) -> dict:
        return {'node': {**first, 'walkTime': (first.get('walkTime') or 0) + (second.get('walkTime') or 0), 'legs': first['legs'] + second['legs']}}

    if req['timeMode'] == 'arriveBy':
        paged = query(PLAN_Q, otp_variables(back_req))
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
        paged = query(PLAN_Q, otp_variables(out_req))
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
    return {'previous': info.get('startCursor') if info.get('hasPreviousPage') else None,
            'next': info.get('endCursor') if info.get('hasNextPage') else None}


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _leg_mode(leg: dict) -> str:
    if leg.get('transitLeg'):
        return mapping.mode_of((leg.get('route') or {}).get('mode') or leg.get('mode'))
    return {'BICYCLE': 'bike', 'SCOOTER': 'scooter'}.get(leg.get('mode'), 'walk')


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
    return text.split(' - ')[-1].strip() or None if text else None


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
            merged[-1] = {**merged[-1], 'destination': leg['destination'], 'geometry': [*merged[-1]['geometry'], *leg['geometry'][1:]],
                          'scheduledArrival': leg['scheduledArrival'], 'effectiveArrival': leg['effectiveArrival']}
            merged_meta[-1] = {**merged_meta[-1], 'duration': merged_meta[-1]['duration'] + m['duration']}
            continue
        merged.append(leg)
        merged_meta.append(m)
    return merged, merged_meta


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
    for edge in (data.get('planConnection') or {}).get('edges') or []:
        node = edge['node']
        raw = node.get('legs') or []
        if not raw:
            continue
        key = hashlib.sha1('|'.join(f'{(l.get("trip") or {}).get("gtfsId")}@{l["start"]["scheduledTime"]}' for l in raw).encode()).hexdigest()[:16]
        legs, meta = [], []
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
                'origin': _leg_place(l['from'], req['origin'] if i == 0 else None),
                'destination': _leg_place(l['to'], req['destination'] if i == len(raw) - 1 else None),
                'scheduledDeparture': l['start']['scheduledTime'], 'scheduledArrival': l['end']['scheduledTime'],
                'effectiveDeparture': start_est or l['start']['scheduledTime'], 'effectiveArrival': end_est or l['end']['scheduledTime'],
                'geometry': geometry,
                'delaySeconds': round(_ts(start_est) - _ts(l['start']['scheduledTime'])) if transit and start_est else None,
                'delayProvenance': 'predicted' if transit and start_est else None,
                'canceled': l.get('realtimeState') == 'CANCELED',
                'stopCount': len(l.get('intermediatePlaces') or []) + 1 if transit else None,
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
            meta.append({'transit': transit, 'interline': bool(l.get('interlineWithPreviousLeg')), 'duration': l.get('duration') or 0,
                         'realtime': bool(start_est), 'platform': platform})
        if plan_for:
            from . import scheduled
            legs, meta = journey_legs.rewrite(legs, meta, plan_for, scheduled.road_shape_of)
            journey_legs.unreplaced_notices(legs, plan_for, by_id)
            journey_legs.name_replaced_trains(legs, plan_for)
        legs, meta = replacement_walks(legs, meta)
        transfers, previous, walking = [], None, 0.0
        for leg, m in zip(legs, meta):
            if not m['transit']:
                walking += m['duration']
                continue
            if previous is not None and not m['interline']:
                available = _ts(leg['effectiveDeparture']) - _ts(previous['effectiveArrival'])
                required, safety = round(walking), req['minTransferSeconds']
                if leg['canceled'] or previous['canceled']:
                    status, meets = 'unknown', None
                elif req.get('riskMode') == 'insane':
                    # Within the rider's allowance (down to -1 min) is a bet, labelled tight when under 2 min spare.
                    meets = available >= required + safety
                    status = 'missed' if available < required + min(0, safety) else ('tight' if available < required + RISKY_TRANSFER else 'safe')
                else:
                    meets = available >= required + safety
                    status = 'missed' if available < required else ('safe' if meets else 'tight')
                transfers.append({'requiredSeconds': required, 'safetySeconds': safety, 'availableSeconds': round(available),
                                  'platform': m['platform'] or None, 'meetsSafetyMargin': meets, 'status': status})
            previous, walking = leg, 0.0
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
            'walkSeconds': max(0, round(node.get('walkTime') or 0)), 'transferCount': len(transfers), 'transfers': transfers,
            'notices': notices[:3], 'freshness': 'live' if any(m['realtime'] for m in meta) else 'scheduled',
        })
    return journeys

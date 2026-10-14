"""Pure translations from upstream payloads (OTP GraphQL, GTFS-RT JSON) to the
Prestop contract in `src/contracts/transit.ts`. No I/O here, so it is unit-tested
directly against recorded upstream shapes."""
import math
import re
import time
import unicodedata
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

RAIL_MODES = {'RAIL', 'TRAM', 'SUBWAY', 'MONORAIL', 'FUNICULAR', 'CABLE_CAR', 'GONDOLA'}
MAX_VEHICLE_AGE = 15 * 60
QUALIFIED = re.compile(r'^[^:]+:.+$')
FALLBACK_URLS = {'IJPP:1161': 'https://potniski.sz.si/', 'LPP': 'https://www.lpp.si/', 'MARPROM': 'https://www.marprom.si/'}


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(int(epoch), timezone.utc).isoformat().replace('+00:00', 'Z')


def mode_of(otp_mode: Optional[str]) -> str:
    return 'rail' if otp_mode in RAIL_MODES else 'bus'


def fold(text: str) -> str:
    return unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode().lower()


def qualify(value: str, prefix: str) -> str:
    return value if ':' in value else f'{prefix}:{value}'


# ---------------------------------------------------------------- stops & routes

def build_stops(otp_stops: Iterable[dict]) -> list[dict]:
    """Stops served by at least one route, with their modes and main operator."""
    out = []
    for s in otp_stops:
        routes = s.get('routes') or []
        if not routes or s.get('lat') is None or s.get('lon') is None:
            continue
        modes = sorted({mode_of(r.get('mode')) for r in routes})
        agencies = Counter((r.get('agency') or {}).get('gtfsId') for r in routes if r.get('agency'))
        rail_agencies = [(r.get('agency') or {}).get('gtfsId') for r in routes if mode_of(r.get('mode')) == 'rail' and r.get('agency')]
        operator = rail_agencies[0] if rail_agencies else (agencies.most_common(1)[0][0] if agencies else s['gtfsId'].split(':')[0] + ':unknown')
        out.append({
            'id': s['gtfsId'], 'name': s.get('name') or s['gtfsId'],
            'latitude': round(s['lat'], 6), 'longitude': round(s['lon'], 6),
            'modes': modes, 'operatorId': operator, 'operatorIds': sorted(a for a in agencies if a),
            'parentId': (s.get('parentStation') or {}).get('gtfsId'),
            'platform': s.get('platformCode') or None,
        })
    # Rail first so a country-wide map shows stations before thousands of bus stops.
    out.sort(key=lambda s: ('rail' not in s['modes'], s['id']))
    return out


def route_name(route: dict) -> str:
    return (route.get('shortName') or route.get('longName') or route.get('gtfsId', '')).strip()


def route_ends(route: dict) -> tuple[str, str]:
    """Best-effort origin/destination labels from a route's long name or first headsign."""
    for text in [route.get('longName')] + [p.get('headsign') for p in route.get('patterns') or []]:
        if text and re.search(r'\s[-–]\s', text):
            parts = re.split(r'\s[-–]\s', text)
            return parts[0].strip(), parts[-1].strip()
    headsigns = [p.get('headsign') for p in route.get('patterns') or [] if p.get('headsign')]
    return (headsigns[0], headsigns[-1]) if headsigns else ('', '')


def route_directions(route: dict) -> list[str]:
    ids = sorted({p.get('directionId') for p in route.get('patterns') or [] if p.get('directionId') in (0, 1)})
    return [str(i) for i in ids] or ['all']


def direction_key(direction_id: Any) -> str:
    return str(direction_id) if direction_id in (0, 1) else 'all'


# ---------------------------------------------------------------- realtime

def trip_update_index(entities: Iterable[dict]) -> dict[str, dict]:
    """tripId -> {'updates': [...], 'timestamp': int} from a GTFS-RT TripUpdates JSON list."""
    index = {}
    for e in entities:
        tu = e.get('tripUpdate') or {}
        trip_id = (tu.get('trip') or {}).get('tripId')
        if not trip_id:
            continue
        index[trip_id] = {
            'updates': tu.get('stopTimeUpdate') or [],
            'timestamp': int(tu.get('timestamp') or 0),
            'trip': tu.get('trip') or {},
        }
    return index


def _update_delay(update: dict) -> Optional[int]:
    for key in ('arrival', 'departure'):
        part = update.get(key) or {}
        if part.get('delay') is not None:
            return int(part['delay'])
    return None


def current_delay(trip_update: Optional[dict], stop_id: Optional[str], stop_sequence: Optional[int]) -> Optional[int]:
    """Delay at the vehicle's current/next stop, else the nearest following update."""
    if not trip_update:
        return None
    updates = trip_update['updates']
    for u in updates:
        if stop_id and u.get('stopId') == stop_id and _update_delay(u) is not None:
            return _update_delay(u)
    if stop_sequence is not None:
        later = [u for u in updates if (u.get('stopSequence') or 0) >= stop_sequence and _update_delay(u) is not None]
        if later:
            return _update_delay(min(later, key=lambda u: u.get('stopSequence') or 0))
    known = [u for u in updates if _update_delay(u) is not None]
    return _update_delay(known[-1]) if known else None


STAND_RADIUS = 12      # metres: reports this close together are the same place
MOVE_RADIUS = 25       # metres: a report this far from the previous one shows movement
STAND_EVIDENCE = 15    # seconds of reports in one place before a vehicle counts as standing
HISTORY_AGE = 5 * 60


def _metres(a: tuple, b: tuple) -> float:
    kx = 111_320 * math.cos(math.radians(a[1]))
    return math.hypot((b[2] - a[2]) * kx, (b[1] - a[1]) * 110_574)


def motion_state(history: list[tuple[float, float, float]], speed: Optional[float], status: Optional[str]) -> tuple[bool, Optional[float]]:
    """(stopped, stopped since epoch) from a vehicle's recent reports `(timestamp, lat, lon)`, oldest first.

    The feed's own status or speed decides when present. Otherwise reports at different
    timestamps that stay within a few metres for at least STAND_EVIDENCE seconds mean the
    vehicle is standing, since the first of them; a jump away clears it. Repeated reports
    (same timestamp) are not evidence."""
    reports: list[tuple[float, float, float]] = []
    for r in history:
        if not reports or r[0] > reports[-1][0]:
            reports.append(r)
    if not reports:
        return False, None
    latest = reports[-1]
    first = latest
    for r in reversed(reports[:-1]):
        if _metres(r, latest) > STAND_RADIUS or _metres(r, first) > MOVE_RADIUS:
            break
        first = r
    standing = latest[0] - first[0] >= STAND_EVIDENCE
    if status == 'STOPPED_AT' or (speed is not None and speed < 0.5):
        return True, first[0]
    return (True, first[0]) if standing else (False, None)


class MotionHistory:
    """Each vehicle's last few distinct reports, for `motion_state`."""

    def __init__(self, size: int = 6):
        self.size = size
        self._reports: dict[str, deque] = {}
        self._swept = 0.0

    def observe(self, vehicle_id: str, stamp: float, lat: float, lon: float, now: float) -> list[tuple[float, float, float]]:
        reports = self._reports.setdefault(vehicle_id, deque(maxlen=self.size))
        if not reports or stamp > reports[-1][0]:
            reports.append((stamp, lat, lon))
        while reports and reports[0][0] < now - HISTORY_AGE:
            reports.popleft()
        if now - self._swept > HISTORY_AGE:
            self._swept = now
            self._reports = {k: v for k, v in self._reports.items() if v and v[-1][0] >= now - HISTORY_AGE}
            self._reports.setdefault(vehicle_id, reports)
        return list(reports)


def build_vehicles(positions: Iterable[dict], trip_updates: dict, trips: dict, routes: dict, stop_names: dict,
                   now: Optional[float] = None, history: Optional[MotionHistory] = None) -> list[dict]:
    now = now or time.time()
    out = []
    seen = set()
    for e in positions:
        v = e.get('vehicle') or {}
        trip = v.get('trip') or {}
        trip_id, pos = trip.get('tripId'), v.get('position') or {}
        if not trip_id or pos.get('latitude') is None or pos.get('longitude') is None:
            continue
        stamp = int(v.get('timestamp') or 0)
        if now - stamp > MAX_VEHICLE_AGE:
            continue
        feed = trip_id.split(':', 1)[0]
        info = trips.get(trip_id) or {}
        route_id = info.get('routeId') or trip.get('routeId')
        route = routes.get(route_id) or {}
        if not route_id:
            continue
        descriptor = v.get('vehicle') or {}
        vehicle_id = qualify(descriptor.get('id') or e.get('id') or trip_id, feed)
        if vehicle_id in seen:
            continue
        seen.add(vehicle_id)
        bearing = pos.get('bearing')
        speed = pos.get('speed')
        speed = float(speed) if isinstance(speed, (int, float)) and 0 <= speed < 70 else None
        stop_id = v.get('stopId')
        report = (stamp, pos['latitude'], pos['longitude'])
        recent = history.observe(vehicle_id, *report, now=now) if history else [report]
        stopped, stopped_since = motion_state(recent, speed, v.get('currentStatus'))
        out.append({
            'id': vehicle_id,
            'name': (descriptor.get('label') or descriptor.get('licensePlate') or route_name(route) or vehicle_id).strip(),
            'latitude': round(pos['latitude'], 6), 'longitude': round(pos['longitude'], 6),
            'mode': mode_of(route.get('mode')),
            'operatorId': route.get('agencyId') or f'{feed}:unknown',
            'routeId': route_id, 'routeName': route_name(route) or '?',
            'destination': info.get('destination') or info.get('headsign') or '',
            'nextStop': stop_names.get(stop_id) if stop_id else None,
            'bearing': float(bearing) % 360 if isinstance(bearing, (int, float)) else None,
            'updatedAt': iso(stamp),
            'delaySeconds': current_delay(trip_updates.get(trip_id), stop_id, v.get('currentStopSequence')),
            'quality': 'observed',
            # Motion hints: the client predicts the position between reports along the trip's shape.
            # Some feeds send bare prefixes (Marprom: "MARPROM:"); only well-formed ids are passed on.
            'tripId': trip_id if QUALIFIED.match(trip_id) else None,
            'speed': round(speed, 2) if speed is not None else None,
            'nextStopId': stop_id if stop_id and QUALIFIED.match(stop_id) else None,
            'stopped': stopped,
            'stoppedSince': iso(stopped_since) if stopped and stopped_since else None,
        })
        if is_replacement(route):  # an SŽ replacement bus with its own GPS: same look as the timetable-placed ones
            out[-1]['replacement'] = True
    return out


# ---------------------------------------------------------------- boards

# SŽ is the only rail operator in the feeds; its BUS routes ("BUS 61706") are replacement transport.
REPLACEMENT_AGENCIES = ['IJPP:1161']


def is_replacement(route: dict) -> bool:
    """An SŽ bus that runs instead of a train (nadomestni prevoz). Not "AVT": that is the avtovlak, the car-carrying
    train through the Bohinj tunnel (Bohinjska Bistrica - Most na Soči), which runs on the railway."""
    agency = (route.get('agency') or {}).get('gtfsId') or route.get('agencyId')
    name = (route.get('shortName') or '').upper()
    return agency in REPLACEMENT_AGENCIES and (route.get('mode') in ('BUS', 'COACH') or name.startswith('BUS '))


def build_board(stop_id: str, stoptimes: Iterable[dict], kind: str, alerts: list[dict]) -> list[dict]:
    from . import stopfix
    out = []
    for st in stoptimes:
        trip = st.get('trip') or {}
        route = trip.get('route') or {}
        first = ((trip.get('departureStoptime') or {}).get('stop') or {}).get('gtfsId')
        last = ((trip.get('arrivalStoptime') or {}).get('stop') or {}).get('gtfsId')
        # Arrivals skip trips that start here; departures skip trips that end here.
        if kind == 'arrival' and (first == stop_id or st.get('dropoffType') == 'NONE'):
            continue
        if kind == 'departure' and (last == stop_id or st.get('pickupType') == 'NONE'):
            continue
        day = st['serviceDay']
        scheduled = day + (st['scheduledArrival'] if kind == 'arrival' else st['scheduledDeparture'])
        realtime = bool(st.get('realtime'))
        canceled = st.get('realtimeState') == 'CANCELED'
        effective = day + (st['realtimeArrival'] if kind == 'arrival' else st['realtimeDeparture'])
        end = ((trip.get('departureStoptime' if kind == 'arrival' else 'arrivalStoptime') or {}).get('stop') or {})
        other_end = stopfix.renamed(end.get('gtfsId'), end.get('name'))
        route_id = route.get('gtfsId') or f'{stop_id.split(":")[0]}:unknown'
        trip_id = trip.get('gtfsId') or f'{route_id}-{scheduled}'
        out.append({
            'id': f'{trip_id}@{day}/{st.get("stopPosition", 0)}',
            'stopId': stop_id, 'tripId': trip_id, 'routeId': route_id,
            'operatorId': (route.get('agency') or {}).get('gtfsId') or f'{route_id.split(":")[0]}:unknown',
            'routeName': route_name(route) or '?', 'mode': mode_of(route.get('mode')),
            'destination': other_end or st.get('headsign') or trip.get('tripHeadsign') or '',
            'scheduledAt': iso(scheduled),
            'effectiveAt': iso(effective) if realtime and not canceled else None,
            'updatedAt': iso(time.time()) if realtime else None,
            'quality': 'predicted' if realtime else None,
            'canceled': canceled,
            'platform': (st.get('stop') or {}).get('platformCode') or None,
            'alertIds': [a['id'] for a in alerts if (stop_id in a['stopIds'] or route_id in a['routeIds']) and alert_active(a, scheduled)],
        })
        if is_replacement(route):
            out[-1]['replacement'] = True
    return out


# ---------------------------------------------------------------- alerts

def _pick(translations: list[dict], language: str) -> tuple[Optional[str], bool]:
    """Text in `language`, else any; second value says whether the language matched."""
    for t in translations or []:
        if (t.get('language') or '').lower().startswith(language):
            return t.get('text'), True
    for t in translations or []:
        if t.get('text'):
            return t['text'], False
    return None, False


REPLACEMENT_WORDS = re.compile(r'nadomest|avtobusni prevoz|replacement bus|rail replacement')
# Contract 6 kinds, first match wins: a moved stop and a detour usually also mention the closed road behind them.
KIND_WORDS = [
    ('stop-moved', re.compile(r'(prestavljen|premaknjen|(prestavitev|ukinitev)\w* postajalisc|zacasn\w* postajalisc|nadomestn\w* postajalisc|ukinjen\w* postajalisc|'
                              r'postajalisc\w* (je |bo )?(prestavljen|ukinjen|zaprt)|stop (moved|relocated|closed))')),
    ('detour', re.compile(r'obvoz|preusmer|spremenjen\w* (potek|tras)|detour|diversion|divert')),
    ('delay', re.compile(r'zamud|zamik|delay')),
    ('closure', re.compile(r'zapora|zaprt|odpoved|ne vozi|ukinjen|prekinitev|dela na progi|track works|cancel|closed')),
]


def alert_kind(text: str) -> str:
    """'replacement' (buses instead of trains, as before), else contract 6: 'stop-moved', 'detour', 'delay', 'closure'
    or 'other'."""
    folded = fold(text)
    if REPLACEMENT_WORDS.search(folded):
        return 'replacement'
    return next((kind for kind, words in KIND_WORDS if words.search(folded)), 'other')


def build_alerts(otp_alerts: Iterable[dict], language: str, now: Optional[float] = None) -> list[dict]:
    now = now or time.time()
    candidates = []
    for a in otp_alerts:
        end = a.get('effectiveEndDate')
        if end and end < now:
            continue
        title, title_match = _pick(a.get('alertHeaderTextTranslations'), language)
        message, _ = _pick(a.get('alertDescriptionTextTranslations'), language)
        if not (title or message):
            continue
        stop_ids, route_ids, agencies = set(), set(), set()
        for ent in a.get('entities') or []:
            kind = ent.get('__typename')
            if kind in ('StopOnRoute', 'StopOnTrip'):
                # Affects this stop on that route (e.g. a stop on detour), not the whole route.
                if (ent.get('stop') or {}).get('gtfsId'):
                    stop_ids.add(ent['stop']['gtfsId'])
                route = ent.get('route') or (ent.get('trip') or {}).get('route') or {}
                if (route.get('agency') or {}).get('gtfsId'):
                    agencies.add(route['agency']['gtfsId'])
                continue
            if kind == 'Stop' and ent.get('gtfsId'):
                stop_ids.add(ent['gtfsId'])
            elif kind == 'Route' and ent.get('gtfsId'):
                route_ids.add(ent['gtfsId'])
                if (ent.get('agency') or {}).get('gtfsId'):
                    agencies.add(ent['agency']['gtfsId'])
            elif kind == 'Trip' and (ent.get('route') or {}).get('gtfsId'):
                route_ids.add(ent['route']['gtfsId'])
                if ((ent['route'].get('agency')) or {}).get('gtfsId'):
                    agencies.add(ent['route']['agency']['gtfsId'])
            elif kind == 'Agency' and ent.get('gtfsId'):
                agencies.add(ent['gtfsId'])
        operator = (a.get('agency') or {}).get('gtfsId') or (sorted(agencies)[0] if agencies else f'{a.get("feed") or "otp"}:unknown')
        url = a.get('alertUrl') or (a.get('agency') or {}).get('url') or FALLBACK_URLS.get(operator) or FALLBACK_URLS.get(a.get('feed') or '') or 'https://brezavta.si/'
        if not re.match(r'^https?://', url):
            url = 'https://' + url.lstrip('/')
        candidates.append(({
            'id': f'alert:{a["id"]}', 'title': (title or message).strip()[:300], 'message': (message or '').strip(),
            'operatorId': operator, 'stopIds': sorted(stop_ids), 'routeIds': sorted(route_ids),
            'validFrom': iso(a.get('effectiveStartDate') or now), 'validTo': iso(end) if end else None,
            'sourceUrl': url, 'kind': alert_kind(f'{title or ""} {message or ""}'),
            # Contract 6: where it comes from (SŽ's notices reach OTP as alerts of operator IJPP:1161) and when.
            'source': 'sz' if operator in REPLACEMENT_AGENCIES or 'SZ-OVIRA' in _decoded(a['id']) else 'feed',
            'from': iso(a.get('effectiveStartDate') or now), 'to': iso(end) if end else None,
            '_from': a.get('effectiveStartDate') or now, '_to': end, '_aliases': [f'alert:{a["id"]}'],
        }, title_match, (a.get('effectiveStartDate'), end, tuple(sorted(stop_ids | route_ids | agencies)))))
    # Some providers publish one alert per language (same window and entities). Keep the
    # requested language when a twin exists; keep single-language alerts otherwise.
    matched_keys = {key for _, match, key in candidates if match}
    kept = [alert for alert, match, key in candidates if match or key not in matched_keys]
    # Others publish the same notice once per stop or route; show it once, covering all of them.
    merged: dict[tuple, dict] = {}
    for alert in kept:
        key = (alert['title'], alert['message'], alert['operatorId'], alert['validFrom'], alert['validTo'])
        if key in merged:
            first = merged[key]
            first['stopIds'] = sorted(set(first['stopIds']) | set(alert['stopIds']))
            first['routeIds'] = sorted(set(first['routeIds']) | set(alert['routeIds']))
            first['_aliases'].extend(alert['_aliases'])
        else:
            merged[key] = alert
    return list(merged.values())


def _decoded(alert_id: str) -> str:
    import base64
    try:
        return base64.b64decode(alert_id + '=' * (-len(alert_id) % 4)).decode('utf-8', 'replace')
    except ValueError:
        return alert_id


def alert_active(alert: dict, at: float) -> bool:
    return alert['_from'] <= at and (alert['_to'] is None or at <= alert['_to'])


def public_alert(alert: dict) -> dict:
    return {k: v for k, v in alert.items() if not k.startswith('_')}


# ---------------------------------------------------------------- rentals

CAR_NETWORKS = re.compile(r'sharengo|avant2go|greengo|car', re.I)
PROVIDER_NAMES = {'jcdecaux_ljubljana': 'BicikeLJ', 'jcdecaux_maribor': 'MBajk', 'bolt_359': 'Bolt', 'kvik': 'Kvik', 'micikel': 'Micikel',
                  # Nomago Bikes systems run on nextbike; names from each feed's system_information.
                  'nextbike_cc': 'Bicikel (Nomago Bikes)', 'nextbike_cd': 'GO2GO Gorizia (Nomago Bikes)', 'nextbike_ce': 'GO2GO (Nomago Bikes)',
                  'nextbike_cf': 'Zanaprej (Nomago Bikes)', 'nextbike_cn': 'KolesCE (Nomago Bikes)', 'nextbike_cx': 'KoroBajk (Nomago Bikes)'}


def provider_name(provider_id: str) -> str:
    network = provider_id.split(':')[0]
    if network in PROVIDER_NAMES:
        return PROVIDER_NAMES[network]
    if network.startswith('nextbike'):
        return 'Nextbike'
    if network.startswith('scbikes_'):
        return network.removeprefix('scbikes_').title() + ' bikes'
    return network.replace('_', ' ').title()


FORM_FACTORS = {'BICYCLE': 'bike', 'CARGO_BICYCLE': 'bike', 'SCOOTER': 'scooter', 'SCOOTER_STANDING': 'scooter', 'SCOOTER_SEATED': 'scooter', 'MOPED': 'scooter'}


def _rental_mode(form_factors: Iterable[str]) -> Optional[str]:
    modes = [FORM_FACTORS[f] for f in form_factors if f in FORM_FACTORS]
    return Counter(modes).most_common(1)[0][0] if modes else None


ELECTRIC = {'ELECTRIC', 'ELECTRIC_ASSIST'}
NO_LIMIT = 100_000  # floating networks report "unlimited" spaces as INT_MAX


def _rack_details(s: dict) -> dict:
    """Capacity, free docks, e-bikes and the operator's app links; unknown values are left out (never 0)."""
    out = {}
    count = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < NO_LIMIT else None
    if count(s.get('capacity')) is not None:
        out['capacity'] = s['capacity']
    if count(s.get('spacesAvailable')) is not None:
        out['docksAvailable'] = s['spacesAvailable']
    by_type = (s.get('availableVehicles') or {}).get('byType') or []
    typed = [t for t in by_type if (t.get('vehicleType') or {}).get('propulsionType')]
    if typed:
        out['ebikesAvailable'] = sum(count(t.get('count')) or 0 for t in typed if t['vehicleType']['propulsionType'] in ELECTRIC)
    elif s.get('vehiclesAvailable') == 0:
        out['ebikesAvailable'] = 0
    uris = {k: v for k, v in (s.get('rentalUris') or {}).items() if k in ('web', 'android', 'ios') and isinstance(v, str) and v.startswith('http')}
    if uris:
        out['rentalUris'] = uris
    return out


def build_rentals(stations: Iterable[dict], vehicles: Iterable[dict], now: Optional[float] = None) -> list[dict]:
    now = now or time.time()
    out = []
    for s in stations:
        types = [((t.get('vehicleType') or {}).get('formFactor')) for t in ((s.get('availableVehicles') or {}).get('byType') or [])]
        types += [((t.get('vehicleType') or {}).get('formFactor')) for t in ((s.get('availableSpaces') or {}).get('byType') or [])]
        network = s.get('network') or s['stationId'].split(':')[0]
        # Stations without typed vehicles are docks; car-sharing networks have no bike/scooter mode.
        mode = _rental_mode(types) or ('bike' if not types and not CAR_NETWORKS.search(network) else None)
        if not mode or s.get('lat') is None or s.get('operative') is False:
            continue
        out.append({
            'id': qualify(s['stationId'], network), 'name': s.get('name') or network,
            'latitude': round(s['lat'], 6), 'longitude': round(s['lon'], 6), 'mode': mode,
            'providerId': f'{network}:{mode}',
            'availableCount': s.get('vehiclesAvailable') if isinstance(s.get('vehiclesAvailable'), int) and s['vehiclesAvailable'] >= 0 else None,
            'canPickup': bool(s.get('allowPickupNow', s.get('allowPickup'))) and (s.get('vehiclesAvailable') or 0) > 0,
            'canReturn': bool(s.get('allowDropoffNow', s.get('allowDropoff'))),
            'updatedAt': iso(s.get('lastUpdated') or now),
            **_rack_details(s),
        })
    for v in vehicles:
        mode = _rental_mode([(v.get('vehicleType') or {}).get('formFactor')])
        if not mode or v.get('lat') is None or v.get('operative') is False:
            continue
        network = (v.get('rentalNetwork') or {}).get('networkId') or v.get('network') or v['vehicleId'].split(':')[0]
        out.append({
            'id': qualify(v['vehicleId'], network), 'name': v.get('name') or network,
            'latitude': round(v['lat'], 6), 'longitude': round(v['lon'], 6), 'mode': mode,
            'providerId': f'{network}:{mode}', 'availableCount': 1,
            'canPickup': bool(v.get('allowPickupNow', True)), 'canReturn': True,
            'updatedAt': iso(now),
        })
    return out


# ---------------------------------------------------------------- geometry

def decode_polyline(points: str, precision: int = 5) -> list[list[float]]:
    """Google encoded polyline -> [[lon, lat], ...]."""
    coords, index, lat, lon, factor = [], 0, 0, 0, 10 ** precision
    while index < len(points):
        for is_lon in (False, True):
            shift = result = 0
            while True:
                b = ord(points[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += delta
            else:
                lat += delta
        coords.append([round(lon / factor, 6), round(lat / factor, 6)])
    return coords


def thin(coords: list, limit: int = 400) -> list:
    if len(coords) <= limit:
        return coords
    step = len(coords) / (limit - 1)
    return [coords[int(i * step)] for i in range(limit - 1)] + [coords[-1]]

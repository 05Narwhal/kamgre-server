"""Trips and lines for the vehicle and line screens.

A trip carries its shape (the road it drives, from the feed's GTFS shapes), every stop
with its distance along that shape, scheduled and live times, and the typical running
time to the next stop learned by the delay collector. The map uses this to predict where
a vehicle is between position reports. Static parts (shape, stops) are cached for hours,
live times for a few seconds.
"""
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import abroad, closures, mapping, platforms, roads, stopfix, stopgroups, supplement, tracks
from .geometry import MAX_POINTS, SHAPE_POINTS, cumulative, simplify, slice_between, stop_distances, trim_spurs  # noqa: F401
from .upstream import UpstreamError, otp

logger = logging.getLogger(__name__)
LJUBLJANA = ZoneInfo('Europe/Ljubljana')
STATIC_TTL = 6 * 3600
TIMES_TTL = 15
LINE_TTL = 15 * 60
PARTIAL_TTL = 30
# A trip from a bus station whose bay the board has not announced yet is rebuilt this often (s), so it
# moves to its own bay once the board shows it (platforms.learn polls every 3 min, ~50 min ahead).
BAY_PENDING_TTL = 180
BAY_HORIZON = 60 * 60
# How long a request waits for a shape the public router is still matching (s). Past it the trip is served
# provisional with the feed's shape: the vehicle page refetches every 20 s and the map refetches provisional
# trips, and the match goes on and is kept (roads.py). Waiting longer put the vehicle page over a second.
ROAD_WAIT = 1.0
# The line screen waits less: it shows the feed's shape at once and refetches a provisional line
# every 15 s, so its first view isn't held up by a shape the public router is still matching.
LINE_ROAD_WAIT = 0.6
CHUNK = 40
# Within this long after midnight a trip's run of the previous day is looked up too (load_trips) ...
OVERNIGHT = 6 * 3600
# ... and wins over today's while its last arrival is at most this long ago.
OVERNIGHT_GRACE = 15 * 60

STATIC_FIELDS = ('gtfsId directionId tripHeadsign route { gtfsId shortName longName mode color agency { gtfsId } } '
                 'pattern { code } tripGeometry { points } stoptimes { stopPosition stop { gtfsId name lat lon } }')
TIMES_FIELDS = ('stoptimesForDate(serviceDate: %s) { stopPosition scheduledArrival realtimeArrival scheduledDeparture '
                'realtimeDeparture realtime realtimeState serviceDay }')
LINE_Q = '''query($id: String!, $date: String!) { route(id: $id) { gtfsId shortName longName mode color agency { gtfsId name }
  patterns { code directionId headsign stops { gtfsId name lat lon } patternGeometry { points } tripsForDate(serviceDate: $date) { gtfsId
    departureStoptime(serviceDate: $date) { scheduledDeparture serviceDay } } } } }'''


# ---------------------------------------------------------------- service days

def service_day(day: Optional[str] = None) -> date:
    if day:
        return date.fromisoformat(day)
    return datetime.now(LJUBLJANA).date()


def _yyyymmdd(day: date) -> str:
    return day.strftime('%Y%m%d')


# ---------------------------------------------------------------- caches

class _Store:
    def __init__(self, ttl: float, size: int = 20_000):
        self.ttl, self.size = ttl, size
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        hit = self._data.get(key)
        return hit[1] if hit and time.time() < hit[0] else None

    def put(self, key, value, ttl: Optional[float] = None):
        with self._lock:
            if len(self._data) > self.size:
                now = time.time()
                self._data = {k: v for k, v in self._data.items() if now < v[0]}
            self._data[key] = (time.time() + (self.ttl if ttl is None else ttl), value)


_static = _Store(STATIC_TTL)
_times = _Store(TIMES_TTL)
_lines = _Store(LINE_TTL, 500)


def road_shape(raw: list, stops: list[dict], mode: str, deadline: Optional[float], replacement: bool = False, from_bay: bool = False) -> tuple[list, bool]:
    """The shape to draw and move vehicles on: bus shapes are repaired where the feed's is
    missing or wrong (see roads.py); an SŽ replacement bus's is routed on the roads between its
    stops, because the feed gives it the railway's; a bus leaving from a bay (platforms.py) drives
    out of it to its second stop; (geometry, complete)."""
    complete = True
    if mode == 'bus':
        raw, complete = roads.repair(raw, stops, deadline, road_only=replacement, reroute=(0,) if from_bay else ())
    elif mode == 'rail':
        raw = trim_spurs(raw)  # no sideways step onto the station's point (geometry.trim_spurs)
    if len(raw) < 2:
        raw = [[s['lon'], s['lat']] for s in stops]
    return simplify(raw, SHAPE_POINTS), complete


def in_slovenia(geometry: list, stops: list[dict], a: int, b: int) -> list:
    """The shape between a trip's first (`a`) and last (`b` - 1) stop in Slovenia (abroad.trim)."""
    if a == 0 and b == len(stops) or len(geometry) < 2:
        return geometry
    d = stop_distances(geometry, stops)
    return slice_between(geometry, cumulative(geometry), d[a], d[b - 1])


def _build_static(t: dict, deadline: Optional[float] = None) -> Optional[dict]:
    route = t.get('route') or {}
    stoptimes = sorted(t.get('stoptimes') or [], key=lambda s: s['stopPosition'])
    if not stoptimes:
        return None
    # A trip that runs abroad ends (starts) at its last (first) stop in Slovenia; the place abroad is text.
    a, b, comes, goes = abroad.trim(stoptimes, lambda s: s['stop'].get('name'))
    if a == b:
        return None
    if mapping.mode_of(route.get('mode')) == 'rail' and not (comes or goes):
        comes, goes = abroad.train_ends(mapping.route_name(route), stoptimes[0]['stop'].get('name'), stoptimes[-1]['stop'].get('name'))
    replacement = mapping.is_replacement(route)
    every = _corrected([s['stop'] for s in stoptimes], replacement)
    stops, stoptimes = every[a:b], stoptimes[a:b]
    mode = mapping.mode_of(route.get('mode'))
    bay = None
    departure = _first_departure(t)
    if mode == 'bus':  # leaving a big bus station: from its bay (platforms.py)
        stops, bay = platforms.place(stops, departure, stops[-1].get('name') or t.get('tripHeadsign') or '')
    origin = platforms.origin_area(bay['station'] if bay else stops[0].get('gtfsId') or '') if mode == 'bus' else None
    destination = platforms.origin_area(stops[-1].get('gtfsId') or '') if mode == 'bus' else None
    raw = t.get('shapeCoordinates') or mapping.decode_polyline((t.get('tripGeometry') or {}).get('points') or '')
    if (a, b) != (0, len(every)):  # the feed's shape runs on abroad: the part between the stops in Slovenia
        raw = in_slovenia(raw, every, a, b) if len(raw) > 1 else raw
    geometry, complete = road_shape(raw, stops, mode, deadline, replacement, from_bay=bool(bay))
    distances = stop_distances(geometry, stops)
    length = cumulative(geometry)[-1] if len(geometry) > 1 else 0.0
    return {
        'id': t['gtfsId'], 'routeId': route.get('gtfsId'), 'routeName': mapping.route_name(route) or '?',
        'operatorId': (route.get('agency') or {}).get('gtfsId') or f'{t["gtfsId"].split(":")[0]}:unknown',
        'mode': mapping.mode_of(route.get('mode')), 'color': f'#{route["color"]}' if route.get('color') else None,
        'destination': goes or stopfix.renamed(stops[-1].get('gtfsId'), stops[-1].get('name')) or t.get('tripHeadsign') or '', 'directionId': mapping.direction_key(t.get('directionId')),
        **({'comesFrom': comes} if comes else {}),
        'patternId': (t.get('pattern') or {}).get('code') or t['gtfsId'],
        'length': round(length, 1), 'geometry': geometry,
        'stops': [{'stopId': s['gtfsId'], 'name': stopfix.renamed(s['gtfsId'], s.get('name') or s['gtfsId']), 'latitude': round(s['lat'], 6), 'longitude': round(s['lon'], 6),
                   'distance': d, 'position': st['stopPosition'], **({'platform': s['bay'], 'platformUsual': s['bayUsual']} if s.get('bay') else {})}
                  for s, d, st in zip(stops, distances, stoptimes)],
        'complete': complete, 'replacement': replacement,
        # Where a bus waits before it leaves and parks after it arrives (a bus station's ground), and
        # whether its bay is still to be announced.
        **({'originArea': origin} if origin else {}),
        **({'destinationArea': destination} if destination else {}),
        # The other bays its departure may use (a range on the board): taken by another bus, it stands in one of these.
        **({'originBays': [{'platform': b['ref'], 'latitude': round(b['lat'], 7), 'longitude': round(b['lon'], 7),
                            **({'heading': round(b['heading'], 1)} if b.get('heading') is not None else {})}
                           for b in bay['alternates']]} if bay and bay.get('alternates') else {}),
        'bayPending': bool(origin) and (not bay or bay['usual']) and departure is not None,
        'departure': departure,
    }


def _static_ttl(static: dict) -> Optional[float]:
    """How long a built trip is kept: shorter while its shape is still being routed or its bay not announced."""
    ttl = None if static['complete'] else PARTIAL_TTL
    if _awaits_bay(static):
        ttl = min(ttl or BAY_PENDING_TTL, BAY_PENDING_TTL)
    return ttl


def _awaits_bay(static: dict, now: Optional[float] = None) -> bool:
    """A trip from a bus station whose bay the board will announce soon (it is due within BAY_HORIZON)."""
    departure = static.get('departure')
    return bool(static.get('bayPending')) and departure is not None and 0 < departure - (now or time.time()) < BAY_HORIZON



def _first_departure(t: dict) -> Optional[float]:
    """Scheduled departure (unix time) from the first stop, from the trip's times for the day."""
    times = sorted(t.get('stoptimesForDate') or [], key=lambda s: s['stopPosition'])
    if not times or times[0].get('serviceDay') is None or times[0].get('scheduledDeparture') is None:
        return None
    return times[0]['serviceDay'] + times[0]['scheduledDeparture']


def _corrected(stops: list[dict], replacement: bool = False) -> list[dict]:
    """Stops at their corrected positions (override table, road snap; see stopfix.py); a replacement
    bus's at the replacement stops beside the stations (closures.py)."""
    overrides, snaps = stopfix.tables()
    stops = stopfix.correct(stops, overrides, snaps)
    return closures.relocate(stops) if replacement else stops


def _query_trips(ids: list[str], day: date, with_static: set[str]) -> dict[str, dict]:
    """One aliased OTP query for many trips: live times for `day`, static parts where needed."""
    times = TIMES_FIELDS % json.dumps(_yyyymmdd(day))
    parts = []
    for i, trip_id in enumerate(ids):
        fields = f'{times} {STATIC_FIELDS}' if trip_id in with_static else f'gtfsId {times}'
        parts.append(f't{i}: trip(id: {json.dumps(trip_id)}) {{ {fields} }}')
    data = otp().query('{ ' + ' '.join(parts) + ' }', timeout=(5, 30))
    return {trip_id: data.get(f't{i}') for i, trip_id in enumerate(ids) if data.get(f't{i}')}


def _still_running(times: list[dict], now: float) -> bool:
    """A run (OTP's stoptimesForDate) whose last arrival, live when known, is at most OVERNIGHT_GRACE ago."""
    ends = [s['serviceDay'] + (s['realtimeArrival'] if s.get('realtime') and s.get('realtimeArrival') is not None else s['scheduledArrival'])
            for s in times if s.get('serviceDay') is not None and s.get('scheduledArrival') is not None]
    return bool(ends) and max(ends) + OVERNIGHT_GRACE >= now


def _after_midnight(day: date, now: float) -> bool:
    """`day` is today and it began less than OVERNIGHT ago."""
    local = datetime.fromtimestamp(now, LJUBLJANA)
    return local.date() == day and now - supplement.day_start(day) < OVERNIGHT


def load_trips(ids: list[str], day: Optional[date] = None) -> dict[str, dict]:
    """tripId -> {static, times, serviceDate}. Trips not running on `day` (today by default)
    are looked up on the previous day too, for runs that continue past midnight. Just after
    midnight a trip that runs every day has two runs, last night's (still on the road) and
    tonight's: last night's wins until it has arrived, so its times and delays are not a day off."""
    now = time.time()
    day = day or datetime.fromtimestamp(now, LJUBLJANA).date()
    overnight = _after_midnight(day, now)
    deadline = time.monotonic() + ROAD_WAIT
    out: dict[str, dict] = {}
    synthetic = [t for t in ids if closures.is_synthetic(t)]
    if synthetic:  # replacement buses made from SŽ notices exist only here, not in OTP
        from . import scheduled
        out.update({t: e for t in synthetic if (e := scheduled.synthetic_entry(t))})
        ids = [t for t in ids if t not in synthetic]
        if not ids:
            return out
    own = [t for t in ids if supplement.owns(t)]
    if own:  # feeds OTP has wrong, from the operator's timetable (supplement.py)
        out.update(_load_own(own, day, deadline, now))
        ids = [t for t in ids if t not in own]
        if not ids:
            return out
    for candidate in (day, day - timedelta(days=1)):
        # The previous day is asked for trips that do not run today and, just after midnight, for all of them.
        earlier = candidate != day
        wanted = [t for t in ids if t not in out or (earlier and overnight)]
        runs: dict[str, dict] = {}
        cached = {t: (_static.get(t), _times.get((t, candidate))) for t in wanted}
        for t, (static, times) in cached.items():
            if static and times:
                runs[t] = {'static': static, 'times': times, 'serviceDate': candidate}
        missing = [t for t in wanted if t not in runs]
        for i in range(0, len(missing), CHUNK):
            chunk = missing[i:i + CHUNK]
            try:
                found = _query_trips(chunk, candidate, {t for t in chunk if not _static.get(t)})
            except UpstreamError as e:
                logger.warning('Trip query failed: %r', e)
                if not out and not runs:
                    raise
                continue
            for trip_id, t in found.items():
                static = _static.get(trip_id)
                if not static and t.get('stoptimes') is not None:
                    static = _build_static(t, deadline)
                    if static:
                        # Shapes still being routed are rebuilt soon with the roads.
                        _static.put(trip_id, static, _static_ttl(static))
                times = t.get('stoptimesForDate') or []
                if static and times:
                    _times.put((trip_id, candidate), times)
                    runs[trip_id] = {'static': static, 'times': times, 'serviceDate': candidate}
        for trip_id, run in runs.items():
            if trip_id not in out or _still_running(run['times'], now):
                out[trip_id] = run
        if not overnight and (all(t in out for t in ids) or day != datetime.fromtimestamp(now, LJUBLJANA).date()):
            break
    return out


def _load_own(ids: list[str], day: date, deadline: float, now: float) -> dict[str, dict]:
    """load_trips for trips of a supplementary feed, with the realtime feed's delays."""
    from . import sources
    updates = sources.trip_updates.get().value if sources._safe(sources.trip_updates) else {}
    overnight = _after_midnight(day, now)
    out = {}
    for trip_id in ids:
        runs = [(c, t) for c in (day, day - timedelta(days=1)) if (t := supplement.otp_trip(trip_id, c, updates.get(trip_id)))]
        if not runs:
            continue
        # Last night's run wins while still on the road (see load_trips).
        last = runs[-1]
        candidate, t = last if overnight and last[0] != day and _still_running(last[1]['stoptimesForDate'], now) else runs[0]
        static = _static.get(trip_id)
        if not static:
            static = _build_static(t, deadline)
            if not static:
                continue
            _static.put(trip_id, static, _static_ttl(static))
        out[trip_id] = {'static': static, 'times': t['stoptimesForDate'], 'serviceDate': candidate}
    return out


def build_trip(entry: dict, typical: dict[str, float], geometry: bool = True) -> dict:
    static, times = entry['static'], {s['stopPosition']: s for s in entry['times']}
    stops = []
    realtime = False
    for i, stop in enumerate(static['stops']):
        st = times.get(stop['position'])
        if not st:
            continue
        day = st['serviceDay']
        live = bool(st.get('realtime'))
        canceled = st.get('realtimeState') == 'CANCELED'
        realtime = realtime or live
        nxt = static['stops'][i + 1]['stopId'] if i + 1 < len(static['stops']) else None
        stops.append({
            'stopId': stop['stopId'], 'name': stop['name'], 'latitude': stop['latitude'], 'longitude': stop['longitude'],
            'distance': stop['distance'],
            'scheduledArrival': mapping.iso(day + st['scheduledArrival']), 'scheduledDeparture': mapping.iso(day + st['scheduledDeparture']),
            'effectiveArrival': mapping.iso(day + st['realtimeArrival']) if live and not canceled else None,
            'effectiveDeparture': mapping.iso(day + st['realtimeDeparture']) if live and not canceled else None,
            'canceled': canceled,
            'typicalSeconds': typical.get(f'{stop["stopId"]}>{nxt}') if nxt else None,
            **({'platform': stop['platform'], 'platformUsual': stop['platformUsual']} if stop.get('platform') else {}),
        })
        if static['mode'] == 'rail' and 'platform' not in stops[-1]:
            # The train's track at each station (tracks.py).
            track, usual = tracks.tracks.track(static['routeName'], stop['stopId'], day + st['scheduledDeparture'])
            if track:
                stops[-1].update(platform=track, platformUsual=usual)
    return {
        **{k: static[k] for k in ('id', 'routeId', 'routeName', 'operatorId', 'mode', 'color', 'destination', 'directionId', 'patternId', 'length')},
        'serviceDate': entry['serviceDate'].isoformat(), 'realtime': realtime,
        # The shape is still being routed (see roads.py), or the bay it leaves from is about to be
        # announced (platforms.py): fetch the trip again shortly.
        'provisional': not static.get('complete', True) or _awaits_bay(static),
        'geometry': static['geometry'] if geometry else [], 'stops': stops,
        **{k: static[k] for k in ('originArea', 'destinationArea', 'originBays', 'comesFrom') if static.get(k)},
        **({'replacement': True} if static.get('replacement') else {}),
    }


# ---------------------------------------------------------------- lines

def load_line(route_id: str, day: Optional[date] = None) -> Optional[dict]:
    day = day or service_day()
    if closures.is_synthetic_line(route_id):  # buses SŽ announced but no feed carries (closures.py)
        from . import scheduled
        return scheduled.synthetic_line(route_id, day)
    key = (route_id, day)
    hit = _lines.get(key)
    if hit is not None:
        return hit
    route = supplement.otp_route(route_id, day) if supplement.owns(route_id) else None
    route = route or otp().query(LINE_Q, {'id': route_id, 'date': _yyyymmdd(day)}).get('route')
    if not route:
        return None
    line, complete = build_line(route, day, time.monotonic() + LINE_ROAD_WAIT)
    _lines.put(key, line, None if complete else PARTIAL_TTL)
    return line


def _departures(trips_today: list[dict]) -> list[dict]:
    """Today's trips of a pattern by first departure, in local time (the line screen's trip switcher)."""
    out = []
    for t in trips_today:
        st = t.get('departureStoptime') or {}
        if st.get('scheduledDeparture') is None or st.get('serviceDay') is None:
            continue
        at = datetime.fromtimestamp(st['serviceDay'] + st['scheduledDeparture'], LJUBLJANA)
        out.append((at, {'tripId': t['gtfsId'], 'departure': at.isoformat()}))
    return [d for _, d in sorted(out, key=lambda item: item[0])]


def build_line(route: dict, day: date, deadline: Optional[float] = None) -> tuple[dict, bool]:
    """The line screen from OTP's route: variants busiest first, with shapes, stops and today's departures."""
    patterns = []
    complete = True
    replacement = mapping.is_replacement(route)
    rail = mapping.mode_of(route.get('mode')) == 'rail'
    for p in route.get('patterns') or []:
        stops = _corrected(p.get('stops') or [], replacement)
        a, b, _, goes = abroad.trim(stops, lambda s: s.get('name'))
        if a == b:
            continue
        if rail and not goes:
            goes = abroad.train_ends(mapping.route_name(route), stops[0].get('name'), stops[-1].get('name'))[1]
        raw = p.get('shapeCoordinates') or mapping.decode_polyline((p.get('patternGeometry') or {}).get('points') or '')
        raw, stops = in_slovenia(raw, stops, a, b), stops[a:b]
        geometry, done = road_shape(raw, stops, mapping.mode_of(route.get('mode')), deadline, replacement)
        complete = complete and done
        distances = stop_distances(geometry, stops)
        patterns.append({
            'id': p['code'], 'directionId': mapping.direction_key(p.get('directionId')),
            'headsign': goes or p.get('headsign') or (stops[-1]['name'] if stops else ''),
            'tripCount': len(p.get('tripsForDate') or []),
            'departures': _departures(p.get('tripsForDate') or []),
            'length': round(cumulative(geometry)[-1], 1) if len(geometry) > 1 else 0.0,
            'geometry': geometry,
            'stops': [{'stopId': s['gtfsId'], 'name': stopfix.renamed(s['gtfsId'], s.get('name') or s['gtfsId']), 'latitude': round(s['lat'], 6),
                       'longitude': round(s['lon'], 6), 'distance': d} for s, d in zip(stops, distances)],
        })
    # Busiest variants first; rare variants (depot runs, school trips) last.
    patterns.sort(key=lambda p: (-p['tripCount'], p['directionId'], -len(p['stops'])))
    agency = route.get('agency') or {}
    origin, destination = mapping.route_ends(route)
    if rail:  # an international train's line: its real ends abroad (abroad.train_ends)
        comes, goes = abroad.train_ends(mapping.route_name(route), origin, destination)
        origin, destination = comes or origin, goes or destination
    long_name = route.get('longName') or ''
    ends = None if rail else mapping.popular_ends(patterns, (origin, destination))
    if ends and not (stopgroups.similar(ends[0], origin) and stopgroups.similar(ends[1], destination)):
        origin, destination = ends  # named by where most of its buses go, not by the feed's long name
        long_name = f'{origin} – {destination}'
    line = {
        'id': route['gtfsId'], 'name': mapping.route_name(route) or route['gtfsId'], 'longName': long_name,
        'operatorId': agency.get('gtfsId') or f'{route["gtfsId"].split(":")[0]}:unknown', 'operatorName': agency.get('name') or '',
        'mode': mapping.mode_of(route.get('mode')), 'color': f'#{route["color"]}' if route.get('color') else None,
        'origin': origin, 'destination': destination, 'serviceDate': day.isoformat(), 'patterns': patterns[:12],
        'provisional': not complete,
        # An SŽ replacement bus: the line screen draws it in the replacement orange, not the railway's blue.
        **({'replacement': True} if replacement else {}),
    }
    return line, complete

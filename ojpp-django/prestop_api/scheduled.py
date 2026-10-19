"""Trains on the map without a GPS feed.

Every running train is placed on its route by interpolating between its stop times: the
predicted ones when OTP has realtime for the trip, else the scheduled ones (quality
"scheduled", never presented as a GPS position). When SŽ's live feed (sz.py) reports
the train, its live delay moves it instead, kept between its last and next station
(quality "inferred"); reported coordinates are used as they are (quality "observed").
A train with a GTFS-RT position is shown from that feed instead.

SŽ's replacement buses (nadomestni prevoz, "BUS 61706") are placed the same way, as buses
on the roads between their stops (never the railway shape the feed gives them), and so are the
synthetic ones for closures the feed has no buses for (closures.py). While one runs, the train
it stands in for is not drawn on the replaced stretch and ignores live reports (see replacement.py).
"""
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from . import abroad, closures, geometry, mapping, roads, sz, sztimetables, tracks, trainlive
from . import replacement as replaced_by
from .trips import service_day
from .upstream import Cached, otp

logger = logging.getLogger(__name__)

_PATTERN_SHAPES = 'patterns { code patternGeometry { points } stops { lat lon } }'
_PATTERN_TIMES = '''gtfsId shortName longName mode agency { gtfsId }
  patterns { code tripsForDate(serviceDate: $date) { gtfsId tripHeadsign
    stoptimesForDate(serviceDate: $date) { scheduledArrival scheduledDeparture realtimeArrival realtimeDeparture realtime
      realtimeState serviceDay stop { gtfsId name lat lon } } } }'''
SHAPES_Q = '{ routes(transportModes: [RAIL]) { %s } }' % _PATTERN_SHAPES
TIMES_Q = 'query($date: String!) { routes(transportModes: [RAIL]) { %s } }' % _PATTERN_TIMES
# OTP cannot filter routes by agency: list the bus routes once, keep SŽ's, then ask for those by id.
BUS_ROUTES_Q = '{ routes(transportModes: [BUS, COACH]) { gtfsId agency { gtfsId } } }'
BUS_SHAPES_Q = 'query($ids: [String]) { routes(ids: $ids) { %s } }' % _PATTERN_SHAPES
BUS_TIMES_Q = 'query($date: String!, $ids: [String]) { routes(ids: $ids) { %s } }' % _PATTERN_TIMES
BOARDING = 120  # s a train is shown at its first station before departure
ARRIVED = 60    # s it stays at its last station


def _load_replacement_ids() -> list[str]:
    routes = otp().query(BUS_ROUTES_Q, timeout=(5, 90))['routes']
    return [r['gtfsId'] for r in routes if (r.get('agency') or {}).get('gtfsId') in mapping.REPLACEMENT_AGENCIES]


replacement_ids = Cached(_load_replacement_ids, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)


def _load_shapes() -> dict[str, dict]:
    """pattern code -> simplified shape, its cumulative lengths, the stop distances and the stops."""
    out = {}
    routes = otp().query(SHAPES_Q, timeout=(5, 90))['routes']
    rail = len(routes)
    ids = replacement_ids.get().value
    if ids:
        routes += otp().query(BUS_SHAPES_Q, {'ids': ids}, timeout=(5, 90))['routes']
    for n, route in enumerate(routes):
        for p in route.get('patterns') or []:
            stops = p.get('stops') or []
            coords = mapping.decode_polyline((p.get('patternGeometry') or {}).get('points') or '')
            if n < rail:
                coords = geometry.trim_spurs(coords)
            if len(coords) < 2:
                coords = [[s['lon'], s['lat']] for s in stops]
            if len(coords) < 2:
                continue
            coords = geometry.simplify(coords)
            out[p['code']] = {'coords': coords, 'cum': geometry.cumulative(coords), 'distances': geometry.stop_distances(coords, stops), 'stops': stops}
    return out


_road_shapes: dict[str, dict] = {}


def _road_shape(stops: list[dict]) -> Optional[dict]:
    """A replacement bus's shape: the roads between its stops (see roads.py), never the railway the
    feed gives it. Never waits: missing legs are routed in the background and drawn straight until
    then; the shape is kept once complete."""
    stops = [s for s in stops if s.get('lat') is not None]
    if len(stops) < 2:
        return None
    key = ';'.join(f'{s["lat"]:.5f},{s["lon"]:.5f}' for s in stops)
    if key in _road_shapes:
        return _road_shapes[key]
    coords, complete = roads.repair([], stops, road_only=True)
    coords = geometry.simplify(coords) if len(coords) > 1 else [[s['lon'], s['lat']] for s in stops]
    fixed = {'coords': coords, 'cum': geometry.cumulative(coords), 'distances': geometry.stop_distances(coords, stops), 'stops': stops,
             'complete': complete}
    if complete:
        if len(_road_shapes) > 2000:
            _road_shapes.clear()
        _road_shapes[key] = fixed
    return fixed


def _trips_for(day) -> list[dict]:
    date = day.strftime('%Y%m%d')
    routes = otp().query(TIMES_Q, {'date': date}, timeout=(5, 60))['routes']
    ids = replacement_ids.get().value
    if ids:
        routes += otp().query(BUS_TIMES_Q, {'date': date, 'ids': ids}, timeout=(5, 60))['routes']
    out = []
    for route in routes:
        for p in route.get('patterns') or []:
            for t in p.get('tripsForDate') or []:
                st = t.get('stoptimesForDate') or []
                if len(st) < 2 or all(s.get('realtimeState') == 'CANCELED' for s in st):
                    continue
                live = [bool(s.get('realtime')) for s in st]
                out.append({
                    'id': t['gtfsId'], 'route': route, 'pattern': p['code'], 'headsign': t.get('tripHeadsign'),
                    'stops': [s['stop'] for s in st],
                    'arrivals': [s['serviceDay'] + (s['realtimeArrival'] if r else s['scheduledArrival']) for s, r in zip(st, live)],
                    'departures': [s['serviceDay'] + (s['realtimeDeparture'] if r else s['scheduledDeparture']) for s, r in zip(st, live)],
                    'delays': [(s['realtimeDeparture'] - s['scheduledDeparture']) if r else None for s, r in zip(st, live)],
                    'scheduledArrivals': [s['serviceDay'] + s['scheduledArrival'] for s in st],
                    'scheduledDepartures': [s['serviceDay'] + s['scheduledDeparture'] for s in st],
                    'serviceDay': st[0]['serviceDay'],
                })
    return out


def _load_timetable() -> list[dict]:
    """Today's trains and yesterday's (for those still running after midnight)."""
    today = service_day()
    trips = _trips_for(today) + _trips_for(today - timedelta(days=1))
    closures.warm()
    return trips


shapes = Cached(_load_shapes, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)
timetable = Cached(_load_timetable, ttl=120, max_stale=6 * 3600, revalidate=600)
_derived: dict = {'key': None, 'sections': {}, 'synthetic': [], 'by_id': {}, 'suppressed': {}, 'decided': {}}
# Other service days (a board or a journey for another date): their trains, and what replaces them that day.
DAY_PLANS = 4
_day_tables: dict[str, Cached] = {}
_day_derived: dict[str, dict] = {}


def _derive_into(slot: dict, trips: list[dict], defer_timetables: bool = False) -> dict:
    """Replaced sections and synthetic replacement buses for a timetable, the notices and SŽ's replacement
    timetables, recomputed only when one of them changes (see replacement.py, closures.py). With
    `defer_timetables` (a request for today or tomorrow) a newer version of the replacement timetables alone does
    not rebuild the plan: the warmer does that in the background (warm.plans). Their first read after a restart
    does: a plan guessed from the notices alone would show EC 38 (19 Oct) by train until the warmer came round."""
    loaded = closures.inputs()
    # The notices by content, the rest by identity (a reload is a new object).
    key = (trips, closures.notices_fingerprint(loaded[0]), *loaded[1:], sztimetables.current()) if loaded else (trips,)
    old = slot['key']
    same = lambda a, b: a == b if isinstance(a, int) else a is b  # noqa: E731
    if old is not None and len(old) == len(key):
        rest = len(key) - 1 if loaded else len(key)  # everything but the replacement timetables
        deferred = defer_timetables and (old[-1] is not None or key[-1] is None)
        if all(same(a, b) for a, b in zip(old[:rest], key[:rest])) and (not loaded or deferred or same(old[-1], key[-1])):
            return slot
    real = replaced_by.sections(trips)
    built = {'buses': [], 'suppressed': {}, 'decided': {}}
    if loaded:
        try:
            built = closures.build(trips, real, loaded, key[-1])
        except Exception as e:  # a notice we cannot read must not take the trains off the map
            logger.warning('Synthetic replacement buses failed: %r', e)
    synthetic, suppressed = built['buses'], built['suppressed']
    # The feed's buses a replacement timetable runs instead of no longer replace their trains.
    merged = {k: v for k, v in ((k, [s for s in v if s['busTripId'] not in suppressed]) for k, v in real.items()) if v}
    for train, extra in closures.sections(synthetic).items():
        merged.setdefault(train, []).extend(extra)
    by_trip: dict[str, list[dict]] = {}
    for t in trips:
        by_trip.setdefault(t['id'], []).append(t)
    slot.update(key=key, sections=merged, synthetic=synthetic, by_id={b['id']: b for b in synthetic}, trips=by_trip,
                suppressed=suppressed, decided=built['decided'])
    return slot


def _derive(trips: Optional[list[dict]] = None) -> dict:
    """Today's (and yesterday's late) replacements. `trips`: a timetable the caller already holds."""
    return _derive_into(_derived, timetable.get().value if trips is None else trips, defer_timetables=True)


def replaced_sections(trips: Optional[list[dict]] = None) -> dict[str, list[dict]]:
    """Train trip id -> replaced sections, by real and synthetic replacement buses."""
    return _derive(trips)['sections']


def synthetic_trips() -> list[dict]:
    return _derive()['synthetic']


def day_timetable(day: date) -> Cached:
    key = day.isoformat()
    cache = _day_tables.get(key)
    if cache is None:
        cache = _day_tables[key] = Cached(lambda d=day: _trips_for(d), ttl=1800, max_stale=6 * 3600, revalidate=3600)
        while len(_day_tables) > DAY_PLANS:
            oldest = next(iter(_day_tables))
            _day_tables.pop(oldest)
            _day_derived.pop(oldest, None)
    return cache


def day_plan(day: date, wait: float = 0, refresh: bool = False) -> Optional[dict]:
    """What replaces trains on service day `day`: {'sections' (train trip id -> replaced sections), 'synthetic',
    'by_id' (synthetic buses), 'trips' (trip id -> that day's timetable trips, trains and buses), 'suppressed'
    (feed buses a replacement timetable runs instead, see closures.plan), 'decided'}. Each day has its own
    trains and only the notices in effect that day, so a closure that ends on the 11th leaves the 12th's
    trains alone. None while the day's timetable is not loaded (after waiting up to `wait` s); today's never
    waits unless asked to. New replacement timetables rebuild today's and tomorrow's plans only with
    `refresh` (the warmer's call), so no request waits on that. Right after a restart a request that may wait
    also waits (within `wait`) for the notices and reads the replacement timetables, so its plan is not one
    without any replacement buses."""
    deadline = time.time() + wait
    if closures.inputs() is None:
        closures.warm()
        while wait and closures.inputs() is None and time.time() < deadline:
            time.sleep(0.05)
    if wait and sztimetables.current() is None:
        sztimetables.load()  # reads the files at most once a minute; nothing when there are none
    wait = max(0.0, deadline - time.time()) if wait else 0
    today = service_day()
    if day == today:
        snap = timetable.wait(wait) if wait else timetable.get_nowait()
        slot = _derived
    else:
        snap = day_timetable(day).wait(wait)
        slot = _day_derived.setdefault(day.isoformat(), {'key': None, 'sections': {}, 'synthetic': [], 'by_id': {}, 'suppressed': {}, 'decided': {}})
    return _derive_into(slot, snap.value, defer_timetables=not refresh and day in (today, today + timedelta(days=1))) if snap else None


def plan_at(when: float, wait: float = 0, cold: bool = False) -> Optional[dict]:
    """The plan holding the trains running at `when`: today's also has yesterday's trains (after midnight). Today's
    never waits (it is loaded and kept warm, warm.py; a board must not wait), unless `cold`: a journey plan right
    after a restart waits up to `wait` rather than ride trains that buses replace."""
    day = datetime.fromtimestamp(when, closures.LOCAL).date()
    today = service_day()
    if day in (today, today - timedelta(days=1)):
        return day_plan(today, wait if cold else 0)
    return day_plan(day, wait)


def train_run(plan: dict, trip_id: str, when: float) -> Optional[dict]:
    """The run of train `trip_id` (one per service day in a plan) that is under way around `when`."""
    runs = (plan.get('trips') or {}).get(trip_id) or []
    return min(runs, key=lambda t: min(abs(x - when) for x in t['scheduledDepartures'] + t['scheduledArrivals']), default=None)


def synthetic_bus(trip_id: str, wait: float = 8) -> tuple[Optional[dict], Optional[dict]]:
    """A synthetic replacement bus by id, for its own service day, and that day's plan."""
    served = closures.synthetic_day(trip_id)
    today = service_day()
    if served is None or served in (today, today - timedelta(days=1)):
        snap = timetable.wait(wait)  # today's plan, which also holds yesterday's late trains
        plan = _derive(snap.value) if snap else None
        bus = plan['by_id'].get(trip_id) if plan else None
        if bus or served is None:
            return bus, plan
    plan = day_plan(served, wait)
    return (plan['by_id'].get(trip_id) if plan else None), plan


def synthetic_entry(trip_id: str) -> Optional[dict]:
    """A synthetic replacement bus in the form trips.load_trips returns ({static, times, serviceDate}), or None."""
    bus, plan = synthetic_bus(trip_id)
    if not bus:
        return None
    bus = trainlive.live_bus(plan, bus)  # its live times, as on the map and boards
    shape = _road_shape(bus['stops'])
    coords = shape['coords'] if shape else [[s['lon'], s['lat']] for s in bus['stops']]
    distances = shape['distances'] if shape else [0.0] * len(bus['stops'])
    route = bus['route']
    day = bus.get('serviceDay') or 0
    static = {
        'id': bus['id'], 'routeId': route['gtfsId'], 'routeName': route['shortName'], 'operatorId': route['agency']['gtfsId'],
        'mode': 'bus', 'color': None, 'destination': bus['headsign'] or '', 'directionId': '0', 'patternId': bus['pattern'],
        **({'comesFrom': bus['comesFrom']} if bus.get('comesFrom') else {}),
        'length': round(shape['cum'][-1], 1) if shape else 0.0, 'geometry': coords,
        'stops': [{'stopId': s['gtfsId'], 'name': s.get('name') or s['gtfsId'], 'latitude': round(s['lat'], 6), 'longitude': round(s['lon'], 6),
                   'distance': d, 'position': i,
                   # SŽ's note on the stop ("the shuttle from the station leaves 5 minutes before the published time")
                   **({'note': s['note']} if s.get('note') else {})} for i, (s, d) in enumerate(zip(bus['stops'], distances))],
        'complete': bool(shape and shape['complete']),
        'replacement': True, 'synthetic': True,
    }
    times = [{'stopPosition': i, 'serviceDay': day, 'realtime': bus['delays'][i] is not None, 'realtimeState': 'SCHEDULED',
              'scheduledArrival': bus['scheduledArrivals'][i] - day, 'realtimeArrival': bus['arrivals'][i] - day,
              'scheduledDeparture': bus['scheduledDepartures'][i] - day, 'realtimeDeparture': bus['departures'][i] - day}
             for i in range(len(bus['stops']))]
    served = bus['serviceDate']
    return {'static': static, 'times': times, 'serviceDate': date(int(served[:4]), int(served[4:6]), int(served[6:]))}


def synthetic_line(route_id: str, day: date) -> Optional[dict]:
    """The line screen of the buses that replace one train on `day` (closures.synthetic_line_id): a variant
    per replaced stretch, with the replacement stops and the roads between them, and that day's runs."""
    plan = day_plan(day, wait=8)
    stamp = day.strftime('%Y%m%d')
    buses = [b for b in (plan or {}).get('synthetic', []) if b['route']['gtfsId'] == route_id and b['serviceDate'] == stamp]
    if not buses:
        # Not running that day (a closure that starts next week): the nearest day already worked out, which is
        # the one a board or journey just showed it on.
        known = [b for slot in (_derived, *_day_derived.values()) for b in slot.get('synthetic', []) if b['route']['gtfsId'] == route_id]
        if not known:
            return None
        nearest = min({b['serviceDate'] for b in known}, key=lambda d: abs((date(int(d[:4]), int(d[4:6]), int(d[6:])) - day).days))
        day, buses = date(int(nearest[:4]), int(nearest[4:6]), int(nearest[6:])), [b for b in known if b['serviceDate'] == nearest]
    variants: dict[tuple, list[dict]] = {}
    for b in buses:
        variants.setdefault(tuple(s['gtfsId'] for s in b['stops']), []).append(b)
    patterns, complete = [], True
    for runs in variants.values():
        first = runs[0]
        shape = _road_shape(first['stops'])
        complete = complete and bool(shape and shape['complete'])
        coords = shape['coords'] if shape else [[s['lon'], s['lat']] for s in first['stops']]
        distances = shape['distances'] if shape else geometry.stop_distances(coords, first['stops'])
        patterns.append({
            'id': first['pattern'], 'directionId': '0', 'headsign': first['headsign'] or '', 'tripCount': len(runs),
            'departures': [{'tripId': b['id'], 'departure': mapping.iso(b['scheduledDepartures'][0])} for b in sorted(runs, key=lambda b: b['departures'][0])],
            'length': round(geometry.cumulative(coords)[-1], 1) if len(coords) > 1 else 0.0, 'geometry': coords,
            'stops': [{'stopId': s['gtfsId'], 'name': s.get('name') or s['gtfsId'], 'latitude': round(s['lat'], 6),
                       'longitude': round(s['lon'], 6), 'distance': d} for s, d in zip(first['stops'], distances)],
        })
    patterns.sort(key=lambda p: -p['tripCount'])
    route = buses[0]['route']
    origin, destination = patterns[0]['stops'][0]['name'], patterns[0]['stops'][-1]['name']
    return {
        # A replacement timetable's buses are named each ("BUS 318/2"); their line is the train's ("BUS 318").
        'id': route_id, 'name': buses[0].get('lineName') or route['shortName'], 'longName': f'{origin} – {destination}',
        'operatorId': route['agency']['gtfsId'], 'operatorName': '', 'mode': 'bus', 'color': None,
        'origin': origin, 'destination': destination, 'serviceDate': day.isoformat(), 'patterns': patterns,
        'provisional': not complete, 'replacement': True, 'replacesTrain': buses[0].get('trainName') or None,
    }


def road_shape_of(stops: list[dict]) -> Optional[dict]:
    """The roads between replacement stops, never waiting (see _road_shape)."""
    return _road_shape(stops)


def locate(trip: dict, shape: Optional[dict], now: float) -> Optional[dict]:
    """Where `trip` is at `now` by its stop times: distance along the shape, index of the
    stop it is at or heading to, whether it stands there, and its speed; None if not running."""
    arr, dep = trip['arrivals'], trip['departures']
    # A bus with one stop in Slovenia (Sežana -> Opčine): it waits there until it leaves the country.
    if not dep[0] - BOARDING <= now <= (dep[0] if len(arr) == 1 else arr[-1] + ARRIVED):
        return None
    distances = shape['distances'] if shape and len(shape['distances']) == len(arr) else None
    for i in range(len(arr)):
        if now <= (dep[i] if i < len(arr) - 1 else arr[i] + ARRIVED):
            if i == 0 or now >= arr[i]:
                return {'distance': distances[i] if distances else None, 'stop': i, 'stopped': True, 'speed': 0.0}
            span = max(1, arr[i] - dep[i - 1])
            f = min(1.0, max(0.0, (now - dep[i - 1]) / span))
            if not distances:
                return {'distance': None, 'stop': i, 'stopped': False, 'speed': None, 'fraction': f}
            meters = max(0.0, distances[i] - distances[i - 1])
            return {'distance': distances[i - 1] + f * meters, 'stop': i, 'stopped': False, 'speed': meters / span}
    return None


def live_locate(trip: dict, shape: Optional[dict], report: dict, now: float) -> Optional[dict]:
    """Where a train is by its live delay: its timetable shifted by the delay, kept between
    the station before the one it reports heading to and that station."""
    if report.get('delay') is None:
        return None
    shifted = {'arrivals': [t + report['delay'] for t in trip.get('scheduledArrivals') or trip['arrivals']],
               'departures': [t + report['delay'] for t in trip.get('scheduledDepartures') or trip['departures']]}
    return _held(trip, shape, report, locate(shifted, shape, now))


def _held(trip: dict, shape: Optional[dict], report: dict, at: Optional[dict]) -> Optional[dict]:
    """`at` kept between the station before the one SŽ reports the train heading to and that station."""
    key = sz.station_key(report.get('next') or '')
    nxt = next((i for i, s in enumerate(trip['stops']) if key and sz.station_key(s.get('name') or '') == key), None)
    if at is None:
        if nxt is None:
            return None
        at = {'distance': None, 'stop': nxt, 'stopped': True, 'speed': None}
    distances = shape['distances'] if shape and len(shape['distances']) == len(trip['stops']) else None
    if nxt is not None and distances and at['distance'] is not None:
        low = distances[nxt - 1] if nxt > 0 else distances[0]
        if at['distance'] > distances[nxt]:
            at = {**at, 'distance': distances[nxt], 'stop': nxt, 'stopped': False, 'speed': 0.0}
        elif at['distance'] < low:
            at = {**at, 'distance': low, 'stop': nxt, 'stopped': False}
    return at


def vehicles(now: Optional[float] = None, skip_trips: frozenset = frozenset(), live: Optional[dict] = None,
             updates: Optional[dict] = None) -> list[dict]:
    """Trains and SŽ replacement buses by their timetable, moved by their live delay (trainlive.py): SŽ's report
    (`live`, by train number) or the GTFS-RT trip updates (`updates`, sources.trip_updates) of the train they run for."""
    now = now or time.time()
    trips = timetable.get().value
    shape_index = shapes.get().value
    live = sz.live.get(now) if live is None else live
    updates = {} if updates is None else updates
    derived = _derive()
    replaced = derived['sections']
    suppressed = derived.get('suppressed') or {}  # the feed's buses a replacement timetable runs instead
    out, seen = [], set()
    for trip in trips + derived['synthetic']:
        if trip['id'] in skip_trips or trip['id'] in seen or trip['id'] in suppressed:
            continue
        times = trip.get('scheduledDepartures') or trip['departures']
        if not times[0] - BOARDING <= now <= times[-1] + ARRIVED + mapping.MAX_UNCONFIRMED_DELAY:
            continue  # not on its way even when very late
        shape = shape_index.get(trip['pattern'])
        replacement = mapping.is_replacement(trip['route'])
        run = trainlive.train_of(derived, trip) if replacement else trip
        own = trainlive.of(derived, trip, updates, live) if run else None
        number = sz.train_parts(mapping.route_name(run['route']))[1] if run else None
        # SŽ's report of the number, when it is what moves this vehicle; `held` when it names this vehicle's next stop
        # (the bus while it runs the train's stretch), not the stop of the vehicle before it
        report = live.get(number) if own and own['source'] == 'sz' and number else None
        held = report if report and own['reported'] is not None else None
        names = {'stops': trip.get('stations') or trip['stops']}
        timed = trainlive.applied(trip, own)
        if replacement:
            if not trip.get('synthetic'):  # the feed's bus calls at the station; it stops at the replacement stop
                timed = {**timed, 'stops': closures.relocate(trip['stops'])}
            shape = _road_shape(timed['stops'])
            category = None
        else:
            category = sz.train_parts(mapping.route_name(trip['route']))[0]
        sections = replaced_by.active(replaced.get(trip['id']), now, BOARDING)
        at = locate(timed, shape, now)
        if held:
            at = _held(names, shape, held, at)
        if not at or any(replaced_by.inside(s, at['stop']) for s in sections):
            continue
        seen.add(trip['id'])
        quality = 'inferred' if report else 'scheduled'
        delay = timed['delays'][at['stop']]
        trip, i, stops = timed, at['stop'], timed['stops']
        # Reported coordinates are the train's own: never the bus's (SŽ's coordinates of a replaced train were not
        # checked), nor while a bus runs part of the train.
        if held and held.get('coords') and not replacement and not sections:
            # Reported coordinates win; the bearing still comes from the railway.
            lat, lon = report['coords']
            bearing = geometry.bearing_at(shape['coords'], shape['cum'], at['distance']) if shape and at['distance'] is not None else None
            quality = 'observed'
        elif at['distance'] is not None:
            lon, lat = geometry.point_at(shape['coords'], shape['cum'], at['distance'])
            bearing = geometry.bearing_at(shape['coords'], shape['cum'], at['distance'])
        elif at['stopped']:
            lon, lat, bearing = stops[i]['lon'], stops[i]['lat'], None
        else:  # no usable shape: straight between the stations
            a, b, f = stops[i - 1], stops[i], at['fraction']
            lon, lat, bearing = a['lon'] + (b['lon'] - a['lon']) * f, a['lat'] + (b['lat'] - a['lat']) * f, None
        route = trip['route']
        feed, local = trip['id'].split(':', 1)
        ends = abroad.scheduled_ends(trip)
        out.append({
            'id': f'{feed}:scheduled-{local}', 'name': mapping.route_name(route) or trip['id'],
            'latitude': round(lat, 6), 'longitude': round(lon, 6), 'mode': 'bus' if replacement else 'rail',
            'operatorId': (route.get('agency') or {}).get('gtfsId') or f'{feed}:unknown',
            'routeId': route['gtfsId'], 'routeName': mapping.route_name(route) or '?',
            'destination': ends[1] or stops[-1].get('name') or trip.get('headsign') or '',
            **({'comesFrom': ends[0]} if ends[0] else {}),
            'nextStop': stops[i].get('name'), 'nextStopId': stops[i]['gtfsId'],
            'bearing': round(bearing, 1) if bearing is not None else None,
            'updatedAt': mapping.iso(report['at'] if report else now),
            'delaySeconds': delay,
            'quality': quality, 'tripId': trip['id'],
            'trainCategory': (report or {}).get('category') or category, 'trainNumber': None if replacement else number,
            'speed': round(at['speed'], 2) if at['speed'] is not None and at['speed'] < 70 else None,
            'stopped': at['stopped'],
        })
        if delay is not None:
            out[-1]['delaySource'] = own['source']
        if replacement:
            out[-1]['replacement'] = True
        else:  # the train's track at its next station (tracks.py)
            track, usual = tracks.tracks.track(mapping.route_name(route), stops[i]['gtfsId'], (trip.get('scheduledDepartures') or trip['departures'])[i])
            if track:
                out[-1].update(nextPlatform=track, nextPlatformUsual=usual)
        if trip.get('alertIds'):
            out[-1]['alertIds'] = trip['alertIds']
    return out

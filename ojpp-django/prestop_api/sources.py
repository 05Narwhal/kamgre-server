"""Live data sources behind /api/v1, each cached in-process with stale fallback.

| Source               | Upstream                                   | Refresh |
| -------------------- | ------------------------------------------ | ------- |
| stop + route index   | OTP `stops`, `routes`                      | 1 h     |
| vehicle positions    | combined GTFS-RT VehiclePositions          | 5 s     |
| trip updates         | combined GTFS-RT TripUpdates               | 10 s    |
| alerts               | OTP `alerts` (GTFS-RT alerts incl. SŽ)     | 60 s    |
| rentals              | OTP rental stations and floating vehicles  | 60 s    |
| boards, journeys     | OTP per request (realtime already applied) | —       |
"""
from datetime import datetime
import json
import logging
import threading
import time
from typing import Optional

from django.conf import settings
from django.db import DatabaseError

from . import abroad, coverage, mapping, stopfix, stopgroups, supplement
from .upstream import Cached, Snapshot, UpstreamError, get_json, otp

logger = logging.getLogger(__name__)

STOPS_Q = '{ stops { gtfsId name lat lon vehicleMode platformCode parentStation { gtfsId } routes { gtfsId mode agency { gtfsId } } } }'
ROUTES_Q = '{ routes { gtfsId shortName longName mode color agency { gtfsId name url } patterns { directionId headsign } } }'
ALERTS_Q = '''{ alerts { id feed alertUrl effectiveStartDate effectiveEndDate
  alertHeaderTextTranslations { language text } alertDescriptionTextTranslations { language text }
  agency { gtfsId url }
  entities { __typename
    ... on Stop { gtfsId } ... on Agency { gtfsId }
    ... on Route { gtfsId agency { gtfsId } }
    ... on Trip { gtfsId route { gtfsId agency { gtfsId } } }
    ... on StopOnRoute { stop { gtfsId } route { gtfsId agency { gtfsId } } }
    ... on StopOnTrip { stop { gtfsId } trip { gtfsId route { gtfsId agency { gtfsId } } } } } } }'''
RENTALS_Q = '''{ vehicleRentalStations { stationId name lat lon vehiclesAvailable spacesAvailable capacity
    allowPickupNow allowDropoffNow operative rentalNetwork { networkId } rentalUris { web android ios }
    availableVehicles { byType { count vehicleType { formFactor propulsionType } } }
    availableSpaces { byType { count vehicleType { formFactor } } } }
  rentalVehicles { vehicleId name lat lon allowPickupNow operative vehicleType { formFactor } rentalNetwork { networkId } } }'''
BOARD_Q = '''query($id: String!, $start: Long, $range: Int, $n: Int, $omit: Boolean) {
  stop(id: $id) { gtfsId
    stoptimesWithoutPatterns(startTime: $start, timeRange: $range, numberOfDepartures: $n, omitNonPickups: $omit, omitCanceled: false) {
      serviceDay scheduledArrival scheduledDeparture realtimeArrival realtimeDeparture realtime realtimeState
      headsign stopPosition pickupType dropoffType stop { platformCode }
      trip { gtfsId tripHeadsign route { gtfsId shortName longName mode agency { gtfsId } }
        departureStoptime { stopPosition scheduledDeparture stop { gtfsId name } } arrivalStoptime { stopPosition stop { gtfsId name } } } } } }'''
TRIP_FIELDS = 'gtfsId directionId tripHeadsign route { gtfsId } arrivalStoptime { stop { name } }'


# ---------------------------------------------------------------- indexes

def _load_stops():
    overrides, snaps = stopfix.tables()
    # Hand-checked positions first, then stops off the road snapped onto it (see stopfix.py).
    raw = otp().query(STOPS_Q)['stops']
    # Feeds whose timetable OTP has wrong (supplement.py): their stops come from the operator's file.
    extra = supplement.stops()
    if extra:
        feeds = {s['gtfsId'].split(':', 1)[0] for s in extra}
        raw = [s for s in raw if s['gtfsId'].split(':', 1)[0] not in feeds] + extra
    # No stop abroad: KamGre shows Slovenia only (abroad.py).
    raw = [s for s in stopfix.correct(raw, overrides, snaps) if not abroad.is_abroad_stop(s.get('name'))]
    built = mapping.build_stops(raw)
    # Stops that are the same physical stop or station become one (see stopgroups.py).
    ways = _stop_directions(built)
    merged, groups = stopgroups.merge(built, overrides['merge'], overrides['stations'], ways)
    # Each side of a stop on its own side of the road (Slovenia drives on the right), at OSM's pole when one is close.
    stopgroups.place_sides(merged, built, ways, set(overrides['stops']) | set(overrides['stations']), stopfix.osm_poles())
    for i, station in enumerate(merged):
        # Where SŽ's replacement buses leave from when that is beside the station, not at it.
        nearby = [r for sid in station.get('memberIds') or [station['id']] for r in overrides['replacement'].get(sid, [])]
        if nearby:
            merged[i] = {**station, 'replacementStops': [{'name': stopfix.stop_name(r['label'], station['name']), 'latitude': r['lat'], 'longitude': r['lon']} for r in nearby]}
    routes = {s['gtfsId']: {r['gtfsId'] for r in s.get('routes') or [] if r.get('gtfsId')} for s in raw}
    for ids in groups.values():
        union = set().union(*(routes.get(i, set()) for i in ids))
        for i in ids:
            routes[i] = union
    return {'list': merged, 'all': built, 'groups': groups, 'routes': routes, 'directions': ways}


def _stop_directions(built: list[dict]) -> dict[str, list]:
    """Which way vehicles travel through each stop, from the timetable's patterns (stopgroups.directions);
    empty when the patterns cannot be loaded (then only stops at the same spot merge across feeds)."""
    try:
        runs = patterns.get().value['patterns']
    except UpstreamError as e:
        logger.warning('Stop directions unavailable: %r', e)
        runs = []
    own = supplement.sequences()
    feeds = {run[0].split(':', 1)[0] for run in own if run}
    sequences = [p['stops'] for p in runs if p['stops'] and p['stops'][0].split(':', 1)[0] not in feeds] + own
    return stopgroups.directions(sequences, {s['id']: (s['latitude'], s['longitude']) for s in built})


def stop_directions(stop_id: str) -> list[tuple[float, float]]:
    """Unit vectors of the ways vehicles travel through a stop (empty: unknown)."""
    snap = stops.peek()
    return ((snap.value.get('directions') or {}).get(stop_id) or []) if snap else []


def stop_group(stop_id: str, wait: bool = False) -> list[str]:
    """Every stop id that is the same physical stop as `stop_id` (just itself if none). `wait`: with no stop
    index yet (~20 s after a start), wait for it instead of answering for this one stop (a board would miss the others)."""
    snap = stops.peek()
    if snap is None and wait:
        try:
            snap = stops.get()
        except UpstreamError as e:
            logger.warning('Stop groups unavailable: %r', e)
    return (snap.value.get('groups') or {}).get(stop_id, [stop_id]) if snap else [stop_id]


def _load_routes():
    routes = {}
    for r in otp().query(ROUTES_Q)['routes']:
        agency = r.get('agency') or {}
        routes[r['gtfsId']] = {**r, 'agencyId': agency.get('gtfsId'), 'agencyName': agency.get('name'), 'agencyUrl': agency.get('url')}
    extra = supplement.routes()  # feeds OTP has wrong (supplement.py) replace OTP's routes
    if extra:
        feeds = {r.split(':', 1)[0] for r in extra}
        routes = {k: v for k, v in routes.items() if k.split(':', 1)[0] not in feeds} | extra
    return routes


stops = Cached(_load_stops, ttl=3600, max_stale=24 * 3600, revalidate=3600)
routes = Cached(_load_routes, ttl=3600, max_stale=24 * 3600, revalidate=3600)


def stop_names() -> dict[str, str]:
    snap = stops.peek()
    return {s['id']: s['name'] for s in snap.value.get('all') or snap.value['list']} if snap else {}


# ---------------------------------------------------------------- realtime feeds

def _load_positions():
    return get_json(settings.PRESTOP_RT_VEHICLES_URL, limit=16 * 1024 * 1024)


def _load_trip_updates():
    return _with_old_ids(supplement.with_own_ids(mapping.trip_update_index(get_json(settings.PRESTOP_RT_TRIP_UPDATES_URL, limit=48 * 1024 * 1024))))


positions = Cached(_load_positions, ttl=5, max_stale=120, revalidate=30)
trip_updates = Cached(_load_trip_updates, ttl=10, max_stale=300, revalidate=60)


class TripInfo:
    """tripId -> route, direction, destination; trips are static for a day, so cache long."""

    TTL = 12 * 3600
    CHUNK = 150

    def __init__(self):
        self._data: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get_many(self, trip_ids) -> dict[str, dict]:
        now = time.time()
        wanted = set(trip_ids)
        missing = [t for t in wanted if t not in self._data or now - self._data[t][0] > self.TTL]
        if missing:
            with self._lock:
                missing = [t for t in missing if t not in self._data or now - self._data[t][0] > self.TTL]
                for i in range(0, len(missing), self.CHUNK):
                    self._fetch(missing[i:i + self.CHUNK], now)
            if len(self._data) > 50_000:
                self._data = {k: v for k, v in self._data.items() if now - v[0] < self.TTL}
        return {t: self._data[t][1] for t in wanted if t in self._data}

    def _fetch(self, ids: list[str], now: float):
        aliases = ' '.join(f't{i}: trip(id: {json.dumps(t)}) {{ {TRIP_FIELDS} }}' for i, t in enumerate(ids))
        try:
            data = otp().query('{ ' + aliases + ' }')
        except UpstreamError as e:
            logger.warning('Trip lookup failed: %r', e)
            return
        for i, trip_id in enumerate(ids):
            t = data.get(f't{i}')
            # Unknown trips are cached too, so they are not re-queried on every poll.
            self._data[trip_id] = (now, {
                'routeId': (t.get('route') or {}).get('gtfsId'),
                'directionId': t.get('directionId'),
                'headsign': t.get('tripHeadsign'),
                'destination': ((t.get('arrivalStoptime') or {}).get('stop') or {}).get('name'),
            } if t else {})


trip_info = TripInfo()


# The realtime feed can name a run by an older timetable version's trip id than OTP's (IJPP:477644 is OTP's
# IJPP:481044, A6340 Jesenice bolnica 14:05; IJPP:475657 is line 69's IJPP:481137 at Ljubljana AP): OTP then has no
# live data for the run, and its board lost a late bus once the timetable time had passed (D3, 22 Oct 2026: 9 such
# IJPP updates). The update is filed under OTP's run too: the one run at its first timed stop at the same position and
# timetable time whose stops are the update's at each position (at least two). Its delays are against the older
# version's times (IJPP:445124: +253 s at 14:42:49 where OTP's A6105 has 14:43), so they are taken again from its live
# times against OTP's. Never as a new run (that would show the bus twice); no single match: left as it is.
OLD_ID_LOOKUPS = 20  # unknown trip ids looked up per load of the trip updates, the rest on the next
OLD_ID_CANDIDATES = 6  # runs at the first stop compared at most
TRIP_CALLS_Q = '''query($id: String!, $date: String!) { trip(id: $id) {
  stoptimesForDate(serviceDate: $date) { stopPosition stop { gtfsId } serviceDay scheduledArrival scheduledDeparture } } }'''
_old_ids: dict[tuple, Optional[tuple]] = {}  # (trip id, start date) -> (OTP's trip id of that run, its calls), or None


def _with_old_ids(index: dict) -> dict:
    if len(_old_ids) > 20_000:
        _old_ids.clear()
    ids = [t for t in index if not supplement.owns(t)]
    known = trip_info.get_many(ids)
    lookups = 0
    for trip_id in ids:
        if known.get(trip_id) != {}:  # OTP knows it, or the lookup failed
            continue
        update = index[trip_id]
        key = (trip_id, update['trip'].get('startDate'))
        if key not in _old_ids:
            if lookups == OLD_ID_LOOKUPS:
                continue
            lookups += 1
            try:
                _old_ids[key] = _same_run(update)
            except UpstreamError as e:
                logger.warning('Run of trip update %s not found: %r', trip_id, e)
                continue
        found = _old_ids[key]
        if found and found[0] not in index:
            run, calls = found
            index[run] = {**update, 'trip': {**update['trip'], 'tripId': run}, 'oldId': trip_id,
                          'updates': [_against(u, calls[u['stopSequence']]) for u in update['updates'] if u.get('stopSequence') in calls]}
    return index


def _against(call: dict, scheduled: dict) -> dict:
    """A trip update's call with its delays from its live times against OTP's timetable times there."""
    out = dict(call)
    for part, key in (('arrival', 'scheduledArrival'), ('departure', 'scheduledDeparture')):
        live = (call.get(part) or {}).get('time')
        if live:
            out[part] = {**call[part], 'delay': int(live) - scheduled[key]}
        else:
            out.pop(part, None)
    return out


def _same_run(update: dict) -> Optional[tuple]:
    """(OTP's trip id, its calls by position) of the run a trip update under an unknown trip id is about
    (_with_old_ids), else None."""
    stops = {u['stopSequence']: u['stopId'] for u in update.get('updates') or [] if u.get('stopId') and u.get('stopSequence') is not None}
    first = next((u for u in update.get('updates') or [] if u.get('stopSequence') in stops and mapping.update_delay(u) is not None
                  and ((u.get('departure') or {}).get('time') or (u.get('arrival') or {}).get('time'))), None)
    if first is None or len(stops) < 2:
        return None
    from zoneinfo import ZoneInfo
    part = next(p for p in (first.get('departure') or {}, first.get('arrival') or {}) if p.get('time'))
    scheduled = int(part['time']) - int(part['delay'] if part.get('delay') is not None else mapping.update_delay(first))
    stop = otp().query(BOARD_Q, {'id': first['stopId'], 'start': scheduled - 60, 'range': 120, 'n': 50, 'omit': False}).get('stop') or {}
    candidates = [st for st in stop.get('stoptimesWithoutPatterns') or [] if st.get('stopPosition') == first['stopSequence']
                  and min(abs(st['serviceDay'] + st[k] - scheduled) for k in ('scheduledArrival', 'scheduledDeparture')) <= 30]
    found = []
    for st in candidates[:OLD_ID_CANDIDATES]:
        date = datetime.fromtimestamp(st['serviceDay'] + 12 * 3600, ZoneInfo('Europe/Ljubljana')).strftime('%Y%m%d')
        trip = otp().query(TRIP_CALLS_Q, {'id': st['trip']['gtfsId'], 'date': date}).get('trip') or {}
        calls = {c['stopPosition']: {'stopId': (c.get('stop') or {}).get('gtfsId'), 'scheduledArrival': c['serviceDay'] + c['scheduledArrival'],
                                     'scheduledDeparture': c['serviceDay'] + c['scheduledDeparture']} for c in trip.get('stoptimesForDate') or []}
        if all((calls.get(seq) or {}).get('stopId') == stop_id for seq, stop_id in stops.items()):
            found.append((st['trip']['gtfsId'], calls))
    return found[0] if len(found) == 1 and len(candidates) <= OLD_ID_CANDIDATES else None


# ---------------------------------------------------------------- trips the timetable does not know

# The realtime feed can be a timetable version ahead of OTP's: its newest trips and routes (IJPP:479070 on
# route IJPP:66623) are unknown there, so their buses had no line ("?") and no destination. Their trip
# updates still name the stops they serve, which OTP knows: the line is the one whose pattern serves them.
PATTERNS_Q = '{ patterns { route { gtfsId } stops { gtfsId name } } }'


def _load_patterns() -> dict:
    patterns = [{'routeId': (p.get('route') or {}).get('gtfsId'), 'stops': [s['gtfsId'] for s in p.get('stops') or []],
                 'last': ((p.get('stops') or [{}])[-1] or {}).get('name') or ''}
                for p in otp().query(PATTERNS_Q, timeout=(5, 90))['patterns']]
    by_stop: dict[str, set[int]] = {}
    for i, p in enumerate(patterns):
        for stop in p['stops']:
            by_stop.setdefault(stop, set()).add(i)
    return {'patterns': patterns, 'by_stop': by_stop}


patterns = Cached(_load_patterns, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)


def infer_trip(update: Optional[dict], index: dict, route_index: dict) -> dict:
    """{'routeId', 'destination'} for a trip OTP does not know, from the stops its trip update names:
    the line whose pattern serves most of them (at least 3, and 60% of those OTP knows; stop ids can
    change between versions too), when the best patterns all belong to one line name; else {}."""
    stops = [u['stopId'] for u in (update or {}).get('updates') or [] if u.get('stopId')]
    known = [st for st in stops if st in index['by_stop']]
    if len(known) < 3:
        return {}
    counts: dict[int, int] = {}
    for st in known:
        for i in index['by_stop'][st]:
            counts[i] = counts.get(i, 0) + 1
    best = max(counts.values())
    if best < max(3, 0.6 * len(known)):
        return {}
    candidates = [index['patterns'][i] for i, n in counts.items() if n == best and index['patterns'][i]['routeId'] in route_index]
    names = {mapping.route_name(route_index[p['routeId']]) for p in candidates}
    if len(names) != 1:
        return {}
    # The pattern that ends where the trip ends gives the destination.
    ending = next((p for p in candidates if p['stops'][-1] == stops[-1]), None)
    return {'routeId': (ending or candidates[0])['routeId'], 'destination': ending['last'] if ending else None}


# Recent reports per vehicle: a vehicle reporting the same place for a while is standing.
motion_history = mapping.MotionHistory()


def _load_vehicles(drops: Optional[list] = None):
    """`drops`: collects each feed entity or timetable train left out and why (coverage.note)."""
    pos = positions.get()
    updates = trip_updates.get().value if _safe(trip_updates) else {}
    route_index = routes.get().value
    if not stops.peek():
        _safe(stops)
    trip_ids = [((e.get('vehicle') or {}).get('trip') or {}).get('tripId') for e in pos.value]
    own = {t for t in trip_ids if t and supplement.owns(t)}
    infos = trip_info.get_many([t for t in trip_ids if t and t not in own])
    infos.update({t: info for t in own if (info := supplement.trip_info(t))})
    unknown = [t for t in trip_ids if t and (infos.get(t) or {}).get('routeId') not in route_index]
    if unknown and _safe(patterns):
        index = patterns.get().value
        for t in unknown:
            guess = infer_trip(updates.get(t), index, route_index)
            if guess:
                infos[t] = {**(infos.get(t) or {}), **{k: v for k, v in guess.items() if v}}
    live = mapping.build_vehicles(pos.value, updates, infos, route_index, stop_names(), history=motion_history, drops=drops)
    from . import sz
    for v in live:
        if v['mode'] == 'rail':
            v['trainCategory'], v['trainNumber'] = sz.train_parts(v['routeName'])
    # Trains without a position feed (SŽ) are placed by their timetable, never instead of a live report.
    try:
        from . import scheduled
        trains = scheduled.vehicles(skip_trips=frozenset(v['tripId'] for v in live if v.get('tripId')), updates=updates, drops=drops)
    except UpstreamError as e:
        logger.warning('Scheduled trains unavailable: %r', e)
        trains = []
    return live + trains


vehicles = Cached(_load_vehicles, ttl=4, max_stale=120, revalidate=30)


def _safe(cache: Cached) -> bool:
    try:
        cache.get()
        return True
    except UpstreamError:
        return False


# ---------------------------------------------------------------- alerts, rentals, boards

FEED_GRACE = 2 * 3600  # s a feed's alerts are kept after OTP stops returning any for that feed
_vanished: dict[str, float] = {}  # feed -> when OTP first returned none of its alerts


def _load_alerts() -> list[dict]:
    """OTP's alerts. OTP now and then answers without one feed's alerts (an updater restarting, a fallback server
    without them), and Arriva's or Marprom's disruptions vanished from the list until the next good answer: a feed
    that had alerts and now has none keeps its last ones for FEED_GRACE, each until its own end, and it is logged."""
    return keep_vanished(otp().query(ALERTS_Q)['alerts'], alerts_raw.peek(), time.time())


def keep_vanished(fresh: list[dict], previous: Optional[Snapshot], now: float) -> list[dict]:
    feeds = {a.get('feed') for a in fresh}
    out = list(fresh)
    for feed, kept in _by_feed(previous.value if previous else []).items():
        if feed in feeds:
            if _vanished.pop(feed, None) is not None:
                logger.info('OTP alerts of feed %s are back', feed)
            continue
        since = _vanished.setdefault(feed, now)
        if since == now:
            logger.warning('OTP returned no alerts of feed %s (it had %d); keeping them for up to %d min', feed, len(kept), FEED_GRACE // 60)
        if now - since < FEED_GRACE:
            out += [a for a in kept if not a.get('effectiveEndDate') or a['effectiveEndDate'] >= now]
    return out


def _by_feed(alerts: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for a in alerts:
        out.setdefault(a.get('feed'), []).append(a)
    return out


alerts_raw = Cached(_load_alerts, ttl=60, max_stale=3600, revalidate=300)


ALERTS_TTL = 45.0  # s a built alert list is reused; a new OTP alert snapshot rebuilds it at once
_built_alerts: dict[str, tuple[float, object, list[dict]]] = {}  # language -> (built at, alerts_raw snapshot, list)
_building: set[str] = set()


def alerts(language: str) -> list[dict]:
    """Every alert in `language`: OTP's, SŽ's notices OTP lacks, operators' site notices and detected ones.

    Building the list matches each notice against the rail patterns (0.3-0.9 s of CPU), and every board, alert
    list and journey asks for it, so the list is built once per OTP snapshot and ALERTS_TTL (warm.py rebuilds it
    ahead of requests). While one request rebuilds an expired list, the others get the previous one."""
    snap = alerts_raw.get()
    if not settings.PRESTOP_SHORT_CACHE:
        return _build_alerts(snap.value, language)
    hit = _built_alerts.get(language)
    if hit and hit[1] is snap and (time.time() - hit[0] < ALERTS_TTL or language in _building):
        return list(hit[2])
    _building.add(language)
    try:
        out = _build_alerts(snap.value, language)
    finally:
        _building.discard(language)
    _built_alerts[language] = (time.time(), snap, out)
    return list(out)


def warm_alerts(share: float = 0.6):
    """Rebuilds the alert lists people asked for once they are `share` of ALERTS_TTL old (warm.py)."""
    for language, (built, snap, _) in list(_built_alerts.items()):
        if time.time() - built >= ALERTS_TTL * share or snap is not alerts_raw.peek():
            fresh = alerts_raw.get()
            _built_alerts[language] = (time.time(), fresh, _build_alerts(fresh.value, language))


def _build_alerts(raw: list[dict], language: str) -> list[dict]:
    from . import closures, detected
    # SŽ's replacement notices OTP doesn't carry yet, where we have their timetables (closures.sz_notice_alerts).
    out = closures.notice_alerts(mapping.build_alerts(raw, language))
    from . import operator_notices
    out += operator_notices.alerts()  # notices on operators' own websites (Arriva)
    if not settings.PRESTOP_DETECTED_ALERTS:
        return out
    try:  # vehicles standing where they shouldn't (detected.py)
        known = routes.peek()
        out += detected.alerts(language, known.value if known else {}, stop_names())
    except DatabaseError as e:
        logger.warning('Detected alerts unavailable: %r', e)
    return out


def _load_rentals():
    data = otp().query(RENTALS_Q)
    stations = [{**s, 'network': (s.get('rentalNetwork') or {}).get('networkId')} for s in data.get('vehicleRentalStations') or []]
    rentals = mapping.build_rentals(stations, data.get('rentalVehicles') or [])
    # Operators' own GBFS feeds, where configured, override OTP's numbers and say how fresh they are.
    from . import gbfs
    try:
        feeds = gbfs.networks.get().value
    except UpstreamError as e:
        logger.warning('GBFS feeds unavailable: %r', e)
        return rentals
    now = time.time()
    out = []
    for r in rentals:
        network, _, station = r['id'].partition(':')
        out.append(gbfs.merge(r, network, station, feeds, now))
    return out


rentals = Cached(_load_rentals, ttl=60, max_stale=900, revalidate=300)


BOARD_MAX = 150  # rows: a board this long goes on from its last row's time in the app ("Later"); a shorter one is all
BOARD_PAGES = 6  # OTP pages of BOARD_MAX calls read for one stop at most (half of Ljubljana AP's calls end there)
SERVICE_DAY_ENDS_HOUR = 4  # trips after midnight still belong to the previous day's timetable


def _until_service_day_end(start: int) -> int:
    """Seconds from `start` to the end of its service day (04:00 local), so a board lists everything left today.
    In the small hours (before 04:00) it runs on to the end of the day that is starting: at 01:00 the night's
    last trips are followed by the morning's first departures instead of an empty board."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    local = datetime.fromtimestamp(start, ZoneInfo('Europe/Ljubljana'))
    end = (local - timedelta(hours=SERVICE_DAY_ENDS_HOUR)).replace(hour=SERVICE_DAY_ENDS_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if local.hour < SERVICE_DAY_ENDS_HOUR:
        end += timedelta(days=1)
    return max(int(end.timestamp()) - start, 3600)


def _member_board(stop_id: str, kind: str, start: int, alert_list: list[dict], drops: Optional[list] = None) -> Optional[list[dict]]:
    if supplement.owns(stop_id):  # OTP has this feed's timetable wrong (supplement.py)
        updates = trip_updates.get().value if _safe(trip_updates) else {}
        own = supplement.stoptimes(stop_id, start, _until_service_day_end(start), BOARD_MAX * BOARD_PAGES, updates)
        if own is not None:
            return mapping.build_board(stop_id, own, kind, alert_list, _live_delays(), drops=drops)
    # In the small hours OTP has a late train still out from yesterday at its timetable (mapping.update_run), so it
    # leaves it out once that time has passed here: the hours before are asked for too, and kept when still to come.
    # So is a run whose trip update OTP left out (mapping.update_day), by as much as the feed has a run late here.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from . import trainlive
    updates = trainlive.trip_updates()
    back = mapping.MAX_UNCONFIRMED_DELAY if datetime.fromtimestamp(start, ZoneInfo('Europe/Ljubljana')).hour < SERVICE_DAY_ENDS_HOUR else 0
    back = max(back, min(mapping.MAX_UNCONFIRMED_DELAY, max((d for at, d in _late_by_stop(updates).get(stop_id, []) if at is None or at >= start), default=0)))
    # A run OTP has leaving its first stop early, gone from OTP's board while the bus waits there (mapping.EARLY_START).
    back = max(back, mapping.EARLY_START if kind == 'departure' else 0)
    # OTP's BOARD_MAX calls can hold far fewer rows (at Ljubljana AP 80 of 150 end there: 70 departures to 16:00, so
    # the app took the day for done; D3, 22 Oct 2026): it is asked on from its last call until the rows fill a board.
    until, at, calls, seen = start + _until_service_day_end(start), start - back, [], set()
    live = _live_delays()
    for _ in range(BOARD_PAGES):
        n = 2 * BOARD_MAX if calls else BOARD_MAX  # OTP takes as long for 300 as for 150 (~0.2 s)
        stop = otp().query(BOARD_Q, {'id': stop_id, 'start': at, 'range': until - at, 'n': n, 'omit': kind == 'departure'}).get('stop')
        if stop is None:
            return None
        page = stop.get('stoptimesWithoutPatterns') or []
        for st in page:  # a call at the time a page ends is on the next one too
            key = ((st.get('trip') or {}).get('gtfsId'), st.get('serviceDay'), st.get('stopPosition'))
            if key not in seen:
                seen.add(key)
                calls.append(st)
        noted: list = []
        rows = mapping.build_board(stop_id, calls, kind, alert_list, live, updates, noted if drops is not None else None)
        kept = [r for r in rows if (r['effectiveAt'] or r['scheduledAt']) >= mapping.iso(start)] if back else rows
        if len(page) < n or len(kept) >= BOARD_MAX:
            break
        at = max(at + 1, page[-1]['serviceDay'] + page[-1]['realtimeDeparture'])
        if at >= until:
            break
    if drops is not None:
        drops += noted
    if back:
        coverage.note(drops, 'gone before the board starts', *(r for r in rows if (r['effectiveAt'] or r['scheduledAt']) < mapping.iso(start)))
    return kept


_late: tuple = (None, {})  # the trip updates last indexed, and their index (mapping.late_by_stop)


def _late_by_stop(updates: dict) -> dict:
    global _late
    if _late[0] is not updates:
        _late = (updates, mapping.late_by_stop(updates))
    return _late[1]


def _live_delays() -> dict[str, Optional[int]]:
    """Trip id -> the delay its vehicle shows now (what confirms a very large delay on a board)."""
    snap = vehicles.peek()
    return {v['tripId']: v.get('delaySeconds') for v in (snap.value if snap else []) if v.get('tripId')}


BOARD_TTL = 15.0     # s a board is reused: realtime reaches OTP every 10-30 s, and the app polls each board
BOARD_REUSE = 60     # s: a board asked for up to this much later than a reused one starts is the same board
_boards: dict[tuple, tuple[float, int, Optional[list[dict]]]] = {}


def board(stop_id: str, kind: str, start: int, language: str) -> Optional[list[dict]]:
    """Departures or arrivals; a merged stop lists every member's, in time order. A board built in the last
    BOARD_TTL seconds from up to BOARD_REUSE seconds earlier is served again (callers copy before changing it)."""
    if not settings.PRESTOP_SHORT_CACHE:
        return _board(stop_id, kind, start, language)
    key = (stop_id, kind, language)
    hit = _boards.get(key)
    if hit and time.time() - hit[0] < BOARD_TTL and 0 <= start - hit[1] < BOARD_REUSE:
        return hit[2]
    items = _board(stop_id, kind, start, language)
    if len(_boards) > 5000:
        _boards.clear()
    _boards[key] = (time.time(), start, items)
    return items


def _board(stop_id: str, kind: str, start: int, language: str, drops: Optional[list] = None) -> Optional[list[dict]]:
    """`drops`: collects each run left out and why (coverage.note), for the coverage audit."""
    try:
        alert_list = alerts(language)
    except UpstreamError:
        alert_list = []
    members = stop_group(stop_id, wait=True)
    if len(members) == 1:
        return _capped(_with_live_platforms(_member_board(stop_id, kind, start, alert_list, drops), stop_id, kind, start, drops), drops)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, len(members))) as pool:
        boards = list(pool.map(lambda m: _member_board(m, kind, start, alert_list, drops), members))
    if all(b is None for b in boards):
        return None
    entries, seen, runs = [], set(), {}
    names = stop_names()
    for entry in sorted((e for b in boards if b for e in b), key=lambda e: e['scheduledAt']):
        # The same trip can be listed by two feeds; keep the first (the head's feed). A feed's own second trip
        # at that time is a second bus (mapping.copy_of).
        if entry['id'] in seen or mapping.copy_of(entry, runs) is not None:
            coverage.note(drops, 'same run from another stop or feed', entry)
            continue
        seen.add(entry['id'])
        # Which of the merged stops it leaves from, by that stop's own name (stopgroups.py).
        entries.append({**entry, 'stopName': names[entry['stopId']]} if entry.get('stopId') in names else entry)
    return _capped(_with_live_platforms(entries, stop_id, kind, start, drops), drops)


def _capped(entries: Optional[list[dict]], drops: Optional[list] = None) -> Optional[list[dict]]:
    """A board's first BOARD_MAX rows by the time they go, in their order: the app goes on from the last one's time
    (a late bus kept by its timetable time would make it skip the rows between)."""
    if not entries or len(entries) <= BOARD_MAX:
        return entries
    beyond = {id(e) for e in sorted(entries, key=lambda e: e.get('effectiveAt') or e['scheduledAt'])[BOARD_MAX:]}
    coverage.note(drops, 'beyond the board row cap', *(e for e in entries if id(e) in beyond))
    return [e for e in entries if id(e) not in beyond]


def _with_live_platforms(entries: Optional[list[dict]], stop_id: str, kind: str = 'departure', start: Optional[int] = None,
                         drops: Optional[list] = None) -> Optional[list[dict]]:
    """Track numbers from SŽ's live feed, for trains whose next station is this one; trains a bus
    replaces from here show as that bus (see replacement.board_rows)."""
    if not entries:
        return entries
    from . import replacement, scheduled
    # Each row by its own service day. Today's never waits for the timetable (a 3–11 s rebuild; with
    # none loaded yet this one board shows the trains); another date's waits once, briefly, then is kept.
    # The buses of SŽ's replacement timetables at this stop within the board's time get their own rows.
    window = {'stop_ids': stop_group(stop_id), 'start': start, 'end': start + _until_service_day_end(start)} if start is not None else {}
    try:
        entries = replacement.board_rows(entries, kind, stop_names(), lambda when: scheduled.plan_at(when, wait=6), drops=drops, **window)
    except UpstreamError as e:
        logger.warning('Replaced trains unknown: %r', e)
    from . import platforms
    if kind == 'departure' and stop_id in platforms.STATIONS:
        # Bus station bays, as AP Ljubljana's board announced them (platforms.learn), else the bay the
        # destination usually leaves from (marked as such).
        seen = platforms.station_seen(stop_id) or []
        for e in entries:
            if e['mode'] == 'bus' and not e.get('platform') and e.get('scheduledAt'):
                at = datetime.fromisoformat(e['scheduledAt'].replace('Z', '+00:00')).timestamp()
                e['platform'], usual = platforms.platform_for(stop_id, at, e.get('destination') or '', seen)
                if usual:
                    e['platformUsual'] = True
    from . import sz, tracks
    reports = sz.live.get()
    here = sz.station_key(stop_names().get(stop_id, ''))
    for e in entries:
        if e['mode'] != 'rail' or e.get('platform'):
            continue
        report = reports.get(sz.train_parts(e['routeName'])[1] or '')
        if report and report.get('platform') and sz.station_key(report.get('next') or '') == here:
            e['platform'] = report['platform']
            continue
        # The station board's track (tracks.py), else the train's usual one there.
        at = datetime.fromisoformat(e['scheduledAt'].replace('Z', '+00:00')).timestamp() if e.get('scheduledAt') else None
        track, usual = tracks.tracks.track(e['routeName'], e.get('stopId') or stop_id, at)
        if track:
            e['platform'] = track
            if usual:
                e['platformUsual'] = True
    return entries


# ---------------------------------------------------------------- places

def search_stations(q: str, limit: int) -> list[dict]:
    """Stops grouped by name within stopgroups.MERGE_METERS (the poles of one stop on both sides of the road), best
    prefix matches first. A railway station never takes a namesake bus stop here: those in range are one stop already
    (stopgroups.merge), and one further off is another place (Radovljica's bus stop is 340 m from its station)."""
    needle = mapping.fold(q.strip())
    if not needle:
        return []
    groups: dict[str, list[dict]] = {}
    railway = set()  # every railway station's name, so a town's district ("Celje Lava") is not a town of its own
    for s in stops.get().value['list']:
        name = mapping.fold(s['name'])
        if 'rail' in s['modes']:
            railway.add(name)
        if needle in name:
            groups.setdefault(name, []).append(s)
    places = []
    for members in groups.values():
        clusters: list[list[dict]] = []
        for s in sorted(members, key=lambda s: ('rail' not in s['modes'], s['id'])):
            for c in clusters:
                if ('rail' in c[0]['modes']) == ('rail' in s['modes']) and all(stopgroups.meters(m, s) <= stopgroups.MERGE_METERS for m in c):
                    c.append(s)
                    break
            else:
                clusters.append([s])
        for c in clusters:
            head = c[0]
            places.append({
                'id': head['id'], 'name': head['name'], 'kind': 'station', 'stopId': head['id'],
                'modes': sorted({m for s in c for m in s.get('modes', [])}),
                'latitude': round(sum(s['latitude'] for s in c) / len(c), 6),
                'longitude': round(sum(s['longitude'] for s in c) / len(c), 6),
                '_rank': (mapping.fold(head['name']) != needle, not mapping.fold(head['name']).startswith(needle), 'rail' not in head['modes'], -len(c), len(head['name'])),
                '_rail': 'rail' in head['modes'], '_members': [s['id'] for s in c],
            })
    places.sort(key=lambda p: p.pop('_rank'))
    return _with_towns(places, railway)[:limit]


TOWN_METERS = 3000  # a town's railway station and its bus station this far apart are still the town (Kranj: 780 m)
TOWN_STOPS = 8  # stop ids a town carries at most (journeys.MAX_TOWN_STOPS): both poles of each station


def _town_bus_stations(places: list[dict], railway: set[str]) -> dict[str, dict]:
    """Railway station id -> its town's bus station among `places`: a bus stop of the same town name ("Kranj AP" for
    "Kranj", "Radovljica" for "Radovljica") within TOWN_METERS, a bus station by name ("AP") first, then the nearest.
    A stop named after the railway station ("Kranj ŽP") is the station's own bus stop, not the town's bus station. A
    station named as another one and more ("Celje Lava", "Novo mesto Šmihel") is a part of that town, not a town."""
    by_town: dict[str, list[dict]] = {}
    for p in places:
        if not p['_rail']:
            by_town.setdefault(stopgroups.normalize(p['name']), []).append(p)
    found, taken = {}, set()
    for rail in (p for p in places if p['_rail']):
        name = mapping.fold(rail['name'])
        if any(name.startswith(other + ' ') for other in railway):
            continue
        best = None
        for p in by_town.get(stopgroups.normalize(rail['name']), []):
            named = bool(stopgroups.BUS_STATION_WORDS.search(mapping.fold(p['name'])))
            if p['id'] in taken or (not named and stopgroups.name_key(p['name']) != stopgroups.name_key(rail['name'])):
                continue
            d = stopgroups.meters(rail, p)
            if d <= TOWN_METERS and (best is None or (not named, d) < best[0]):
                best = ((not named, d), p)
        if best:
            found[rail['id']] = best[1]
            taken.add(best[1]['id'])
    return found


def _with_towns(places: list[dict], railway: set[str]) -> list[dict]:
    """A town whose railway station and bus station are apart (Kranj, Radovljica) is one more result, both stations as
    one place (`stopIds`: plan from whichever suits, journeys.py), right before them; the two stay results of their own
    next to it. Stations close enough to be one are one stop already (stopgroups.merge) and need no town."""
    bus_of = _town_bus_stations(places, railway)
    rail_of = {bus['id']: rail_id for rail_id, bus in bus_of.items()}
    by_id = {p['id']: p for p in places}
    out, placed = [], set()
    for p in places:
        if p['id'] in placed:
            continue
        rail = p if p['id'] in bus_of else by_id.get(rail_of.get(p['id'], ''))
        if not rail:
            out.append(p)
            continue
        bus = bus_of[rail['id']]
        out += [{
            'id': f'town:{rail["id"]}', 'name': rail['name'], 'kind': 'station', 'category': 'town', 'stopId': rail['id'],
            # Every pole of both (Kranj AP's other side is another stop): a journey may leave from any of them.
            'stopIds': (rail['_members'] + bus['_members'])[:TOWN_STOPS] if len(rail['_members']) < TOWN_STOPS else [rail['id'], bus['id']], 'modes': sorted(set(rail['modes']) | set(bus['modes'])),
            'latitude': round((rail['latitude'] + bus['latitude']) / 2, 6), 'longitude': round((rail['longitude'] + bus['longitude']) / 2, 6),
        }, rail, bus]
        placed.update((rail['id'], bus['id']))
    return [{k: v for k, v in p.items() if k not in ('_rail', '_members')} for p in out]


def geocode(q: str, limit: int, language: str, near=None) -> list[dict]:
    """Addresses and points of interest in Slovenia (Photon and Pelias merged, see places.py)."""
    from . import places
    return places.geocode(q, limit, language, near)


def geocode_soon(q: str, limit: int, language: str, near=None) -> tuple[list[dict], bool]:
    """geocode without waiting long for the slower geocoder: (places, complete); see places.search."""
    from . import places
    return places.search(q, limit, language, near, soft=places.SOFT_WAIT)

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

from . import abroad, mapping, stopfix, stopgroups, supplement
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
        departureStoptime { scheduledDeparture stop { gtfsId name } } arrivalStoptime { stop { gtfsId name } } } } } }'''
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


def stop_group(stop_id: str) -> list[str]:
    """Every stop id that is the same physical stop as `stop_id` (just itself if none)."""
    snap = stops.peek()
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
    return mapping.trip_update_index(get_json(settings.PRESTOP_RT_TRIP_UPDATES_URL, limit=48 * 1024 * 1024))


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


def _load_vehicles():
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
    live = mapping.build_vehicles(pos.value, updates, infos, route_index, stop_names(), history=motion_history)
    from . import sz
    for v in live:
        if v['mode'] == 'rail':
            v['trainCategory'], v['trainNumber'] = sz.train_parts(v['routeName'])
    # Trains without a position feed (SŽ) are placed by their timetable, never instead of a live report.
    try:
        from . import scheduled
        trains = scheduled.vehicles(skip_trips=frozenset(v['tripId'] for v in live if v.get('tripId')))
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


BOARD_MAX = 150
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


def _member_board(stop_id: str, kind: str, start: int, alert_list: list[dict]) -> Optional[list[dict]]:
    if supplement.owns(stop_id):  # OTP has this feed's timetable wrong (supplement.py)
        updates = trip_updates.get().value if _safe(trip_updates) else {}
        own = supplement.stoptimes(stop_id, start, _until_service_day_end(start), BOARD_MAX, updates)
        if own is not None:
            return mapping.build_board(stop_id, own, kind, alert_list)
    data = otp().query(BOARD_Q, {'id': stop_id, 'start': start, 'range': _until_service_day_end(start), 'n': BOARD_MAX, 'omit': kind == 'departure'})
    stop = data.get('stop')
    if stop is None:
        return None
    return mapping.build_board(stop_id, stop.get('stoptimesWithoutPatterns') or [], kind, alert_list)


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


def _board(stop_id: str, kind: str, start: int, language: str) -> Optional[list[dict]]:
    try:
        alert_list = alerts(language)
    except UpstreamError:
        alert_list = []
    members = stop_group(stop_id)
    if len(members) == 1:
        return _with_live_platforms(_member_board(stop_id, kind, start, alert_list), stop_id, kind, start)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, len(members))) as pool:
        boards = list(pool.map(lambda m: _member_board(m, kind, start, alert_list), members))
    if all(b is None for b in boards):
        return None
    entries, seen = [], set()
    names = stop_names()
    for entry in sorted((e for b in boards if b for e in b), key=lambda e: e['scheduledAt']):
        # The same trip can be listed by two feeds; keep the first (the head's feed).
        key = (entry['routeName'], entry['scheduledAt'], entry['destination'])
        if entry['id'] in seen or key in seen:
            continue
        seen.update({entry['id'], key})
        # Which of the merged stops it leaves from, by that stop's own name (stopgroups.py).
        entries.append({**entry, 'stopName': names[entry['stopId']]} if entry.get('stopId') in names else entry)
    return _with_live_platforms(entries[:BOARD_MAX], stop_id, kind, start)


def _with_live_platforms(entries: Optional[list[dict]], stop_id: str, kind: str = 'departure', start: Optional[int] = None) -> Optional[list[dict]]:
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
        entries = replacement.board_rows(entries, kind, stop_names(), lambda when: scheduled.plan_at(when, wait=6), **window)
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
    for s in stops.get().value['list']:
        name = mapping.fold(s['name'])
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
            })
    places.sort(key=lambda p: p.pop('_rank'))
    return places[:limit]


def geocode(q: str, limit: int, language: str, near=None) -> list[dict]:
    """Addresses and points of interest in Slovenia (Photon and Pelias merged, see places.py)."""
    from . import places
    return places.geocode(q, limit, language, near)


def geocode_soon(q: str, limit: int, language: str, near=None) -> tuple[list[dict], bool]:
    """geocode without waiting long for the slower geocoder: (places, complete); see places.search."""
    from . import places
    return places.search(q, limit, language, near, soft=places.SOFT_WAIT)

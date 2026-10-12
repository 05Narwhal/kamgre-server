"""Road geometry where a feed's bus shape is missing or wrong.

Some IJPP patterns come without a GTFS shape, so OTP draws straight lines from stop to
stop; many departures from Ljubljana AP still start at the old bus station although the
stop has moved. Such stop-to-stop segments are routed along roads a bus may use
(Valhalla with `bus` costing, so bus-only streets count) and spliced into the shape.

A segment is re-routed when a stop at either end lies far off the shape, when the shape
runs straight between the stops without a single point in between (how feeds without shapes
look), or when `manage.py road_shapes` found the shape off the road there: sparse shapes
(points hundreds of metres apart) cut corners, so a point half-way between two distant shape
points is located on the road network once, offline, and the result kept in
`data/shape_checks.json`. Routed legs are stored in the database, so each is requested once;
a background worker fetches them and callers wait only up to a deadline.
"""
import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from django.conf import settings
from django.db import close_old_connections

from . import geometry, mapping
from .upstream import session

logger = logging.getLogger(__name__)

OFF_SHAPE = 100       # m: a stop further than this from the shape means the shape is wrong there
STRAIGHT = 150        # m: longer stop-to-stop runs without shape points are feed straight lines
SPARSE = 150          # m: shape points further apart than this may cut a corner (checked by road_shapes)
OFF_ROAD = 25         # m: a checked point further than this from a bus road means the shape is wrong there
CHECKS = Path(__file__).resolve().parent / 'data' / 'shape_checks.json'
END_SLACK = 15        # m: shape points this close to a stop do not count as "in between"
MAX_LOCATIONS = 10    # per Valhalla request (the public server's limit)
REQUEST_GAP = 0.35    # s between requests to the public server
RETRY_AFTER = 600     # s before a failed request is tried again
DETOUR = (4, 1000)    # a routed leg longer than 4x the straight line and 1 km more is a router loop

_gate = threading.Lock()  # one Valhalla request at a time across the router and the matcher


def _gap() -> float:
    """Seconds to pause after a background request (settings.PRESTOP_VALHALLA_GAP; 0 for a local router)."""
    return getattr(settings, 'PRESTOP_VALHALLA_GAP', REQUEST_GAP)


def leg_key(a: dict, b: dict) -> str:
    return f'{a["lat"]:.5f},{a["lon"]:.5f};{b["lat"]:.5f},{b["lon"]:.5f}'


def shapeless(coords: list, stops: list[dict]) -> bool:
    """True when the feed sent no shape (OTP then returns the stops as the line)."""
    return len(coords) < 2 or len(coords) <= len(stops) + 1


_checks: dict = {'stamp': None, 'value': {}}
_checks_lock = threading.Lock()


def checks() -> dict[str, float]:
    """Leg key -> metres the feed's shape is off the road there (`data/shape_checks.json`), re-read when it changes."""
    try:
        stamp = os.stat(CHECKS).st_mtime
    except OSError:
        return {}
    with _checks_lock:
        if _checks['stamp'] != stamp:
            try:
                _checks.update(stamp=stamp, value=json.loads(CHECKS.read_text(encoding='utf-8')))
            except (OSError, ValueError) as e:
                logger.warning('shape_checks.json unreadable: %r', e)
                _checks.update(stamp=stamp, value={})
        return _checks['value']


def bad_segments(coords: list, stops: list[dict], checked: Optional[dict] = None) -> list[bool]:
    """For each stop-to-stop segment, whether the shape is unusable there."""
    if len(stops) < 2:
        return []
    if shapeless(coords, stops):
        return [geometry.distance([a['lon'], a['lat']], [b['lon'], b['lat']]) > 30 for a, b in zip(stops, stops[1:])]
    checked = checks() if checked is None else checked
    cum = geometry.cumulative(coords)
    proj = geometry.project_stops(coords, stops)
    out = []
    for i, ((a, off_a), (b, off_b)) in enumerate(zip(proj, proj[1:])):
        inner = sum(1 for d in cum if a + END_SLACK < d < b - END_SLACK)
        off_road = checked.get(leg_key(stops[i], stops[i + 1]), 0) > OFF_ROAD if checked else False
        out.append(off_a > OFF_SHAPE or off_b > OFF_SHAPE or (inner == 0 and b - a > STRAIGHT) or off_road)
    return out


def sparse_points(coords: list, cum: list[float], a: float, b: float, most: int = 3) -> list[list]:
    """Points half-way across the (at most `most`) longest gaps over SPARSE metres in the shape between
    distances `a` and `b`: where a sparse shape would cut a corner."""
    marks = [a, *(d for d in cum if a < d < b), b]
    gaps = sorted(((y - x, x) for x, y in zip(marks, marks[1:]) if y - x > SPARSE), reverse=True)[:most]
    return [geometry.point_at(coords, cum, x + length / 2) for length, x in gaps]


def plausible(leg: list, a: dict, b: dict) -> bool:
    """False for a leg that loops far away, e.g. when the router snaps a stop to the far side of
    a divided road and drives kilometres to turn around."""
    crow = geometry.distance([a['lon'], a['lat']], [b['lon'], b['lat']])
    length = geometry.cumulative(leg)[-1]
    return length <= max(DETOUR[0] * crow, crow + DETOUR[1])


def splice(coords: list, stops: list[dict], bad: list[bool], legs: dict[str, list]) -> list:
    """The shape between the first and last stop, with bad segments replaced by routed legs.

    A bad segment without a (plausible) routed leg stays as the feed has it (a straight line
    when there is no shape)."""
    if shapeless(coords, stops):
        coords = [[s['lon'], s['lat']] for s in stops]
    cum = geometry.cumulative(coords)
    along = [a for a, _ in geometry.project_stops(coords, stops)]
    out: list = []
    for i, is_bad in enumerate(bad):
        leg = legs.get(leg_key(stops[i], stops[i + 1])) if is_bad else None
        if leg and len(leg) > 1 and plausible(leg, stops[i], stops[i + 1]):
            part = leg
        elif is_bad and (along[i] >= along[i + 1] or shapeless(coords, stops)):
            part = [[stops[i]['lon'], stops[i]['lat']], [stops[i + 1]['lon'], stops[i + 1]['lat']]]
        else:
            part = geometry.slice_between(coords, cum, along[i], along[i + 1])
        if out and part and out[-1] == part[0]:
            part = part[1:]
        out.extend(part)
    return out if len(out) > 1 else coords


# ---------------------------------------------------------------- store

class _Legs:
    """Routed legs: memory in front of the `RoadLeg` table. An empty leg means no route."""

    def __init__(self):
        self._memory: dict[str, list] = {}

    def get_many(self, keys: list[str]) -> dict[str, list]:
        found = {k: self._memory[k] for k in keys if k in self._memory}
        missing = [k for k in keys if k not in found]
        if missing:
            try:
                from .models import RoadLeg
                for row in RoadLeg.objects.filter(key__in=missing):
                    self._memory[row.key] = found[row.key] = row.geometry
            except Exception as e:  # the map still works with straight segments
                logger.warning('Road legs unavailable: %r', e)
        return found

    def put_many(self, legs: dict[str, list]):
        self._memory.update(legs)
        try:
            from .models import RoadLeg
            RoadLeg.objects.bulk_create([RoadLeg(key=k, geometry=v) for k, v in legs.items()], ignore_conflicts=True)
        except Exception as e:
            logger.warning('Could not store road legs: %r', e)


legs = _Legs()


# ---------------------------------------------------------------- routing

def route_window(stops: list[dict]) -> Optional[list[list]]:
    """One Valhalla request through up to MAX_LOCATIONS stops: a leg per consecutive pair,
    None when there is no road route (a leg may then be empty), raises on transport errors."""
    body = {'locations': [{'lat': s['lat'], 'lon': s['lon'], 'type': 'break'} for s in stops],
            'costing': 'bus', 'directions_type': 'none'}
    resp = session().post(settings.PRESTOP_VALHALLA_URL, json=body, timeout=(5, 20))
    if resp.status_code == 400:  # no route between these points
        logger.info('No road route: %s', resp.text[:200])
        return None
    resp.raise_for_status()
    trip = resp.json()['trip']
    return [mapping.decode_polyline(leg['shape'], precision=6) for leg in trip['legs']]


class _Worker:
    def __init__(self):
        self._queue: 'queue.Queue[tuple[list[dict], threading.Event]]' = queue.Queue()
        self._pending: dict[str, threading.Event] = {}
        self._failed: dict[str, float] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def request(self, stops: list[dict], missing: set[str]) -> list[threading.Event]:
        """Queue windows covering the missing legs of a run of stops; events fire when done."""
        events = []
        now = time.time()
        with self._lock:
            for start in range(0, len(stops) - 1, MAX_LOCATIONS - 1):
                window = stops[start:start + MAX_LOCATIONS]
                keys = {leg_key(a, b) for a, b in zip(window, window[1:])} & missing
                keys = {k for k in keys if now - self._failed.get(k, 0) > RETRY_AFTER}
                if not keys:
                    continue
                pending = {self._pending[k] for k in keys if k in self._pending}
                if len(pending) and all(k in self._pending for k in keys):
                    events.extend(pending)
                    continue
                event = threading.Event()
                for k in keys:
                    self._pending[k] = event
                self._queue.put((window, event))
                events.append(event)
            if events and (not self._thread or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, name='prestop-roads', daemon=True)
                self._thread.start()
        return events

    def _run(self):
        while True:
            try:
                window, event = self._queue.get(timeout=60)
            except queue.Empty:
                return
            keys = [leg_key(a, b) for a, b in zip(window, window[1:])]
            try:
                with _gate:
                    routed = route_window(window)
                found = {k: (routed[i] if routed and i < len(routed) else []) for i, k in enumerate(keys)}
                legs.put_many(found)
            except Exception as e:
                logger.warning('Road routing failed: %r', e)
                with self._lock:
                    self._failed.update({k: time.time() for k in keys})
            finally:
                with self._lock:
                    for k in keys:
                        if self._pending.get(k) is event:
                            del self._pending[k]
                event.set()
                close_old_connections()
            time.sleep(_gap())


worker = _Worker()


# ---------------------------------------------------------------- map matching

MATCH_PREFIX = 'm:'      # RoadLeg keys of map-matched shapes
MATCH_CHUNK = 6000       # m of feed shape per request when the whole shape doesn't match in one
MATCH_NEAR = 40          # m: a feed point further than this from the matched line means the match took another road
MATCH_SHARE = 0.95       # share of (sampled) feed points that must lie that close
MATCH_LENGTH = (0.9, 1.15)  # matched length / feed length
MATCH_SAMPLE = 50        # m between feed points checked


def match_key(coords: list) -> str:
    """RoadLeg key of a feed shape's map-matched line: a hash of its points (5 decimals)."""
    import hashlib
    text = ';'.join(f'{x:.5f},{y:.5f}' for x, y in coords)
    return MATCH_PREFIX + hashlib.sha1(text.encode()).hexdigest()


def trace(coords: list) -> Optional[list]:
    """Valhalla map matching (`trace_route`, bus costing) of a feed shape onto the road network:
    the matched line, None when Valhalla finds no match; raises on transport errors."""
    url = settings.PRESTOP_VALHALLA_URL.rsplit('/', 1)[0] + '/trace_route'
    body = {'shape': [{'lat': y, 'lon': x} for x, y in coords], 'costing': 'bus', 'shape_match': 'map_snap',
            'directions_type': 'none', 'trace_options': {'search_radius': MATCH_NEAR, 'gps_accuracy': 12}}
    resp = session().post(url, json=body, timeout=(5, 60))
    if resp.status_code == 400:  # nothing to match it to
        logger.info('No map match: %s', resp.text[:200])
        return None
    resp.raise_for_status()
    out: list = []
    for leg in resp.json()['trip']['legs']:
        part = mapping.decode_polyline(leg['shape'], precision=6)
        out.extend(part[1:] if out and part and out[-1] == part[0] else part)
    return out


def match_ok(feed: list, matched: Optional[list]) -> bool:
    """Whether a matched line stays with the feed shape: about as long, and (nearly) every feed
    point close to it. A match that wandered off along another road, or only matched a part, fails."""
    if not matched or len(matched) < 2 or len(feed) < 2:
        return False
    feed_length, matched_length = geometry.cumulative(feed)[-1], geometry.cumulative(matched)[-1]
    if not feed_length or not MATCH_LENGTH[0] <= matched_length / feed_length <= MATCH_LENGTH[1]:
        return False
    cum = geometry.cumulative(feed)
    samples = [geometry.point_at(feed, cum, d) for d in range(0, int(feed_length) + 1, MATCH_SAMPLE)]
    offsets = [off for _, off in geometry.project_stops(matched, [{'lat': y, 'lon': x} for x, y in samples])]
    return sum(1 for off in offsets if off <= MATCH_NEAR) >= MATCH_SHARE * len(offsets)


def match_shape(coords: list, request=None) -> list:
    """A feed shape map-matched onto the roads: in one request when that matches the whole shape,
    else in pieces of about MATCH_CHUNK metres, keeping the feed's own line for a piece that does
    not match. Empty when no piece matched (the feed shape is then used as it is)."""
    request = request or trace
    whole = request(coords)
    if match_ok(coords, whole):
        return whole
    cum = geometry.cumulative(coords)
    cuts = [0]
    for i, d in enumerate(cum):
        if d - cum[cuts[-1]] >= MATCH_CHUNK and i < len(coords) - 1:
            cuts.append(i)
    cuts.append(len(coords) - 1)
    out: list = []
    matched_any = False
    for a, b in zip(cuts, cuts[1:]):
        piece = coords[a:b + 1]
        line = request(piece) if len(piece) >= 2 else None
        if match_ok(piece, line):
            matched_any = True
        else:
            line = piece
        out.extend(line[1:] if out and line and out[-1] == line[0] else line)
    return out if matched_any else []


class _Matcher:
    """Map-matches feed shapes in the background, one at a time; callers wait on an event."""

    def __init__(self):
        self._queue: 'queue.Queue[tuple[str, list, threading.Event]]' = queue.Queue()
        self._pending: dict[str, threading.Event] = {}
        self._failed: dict[str, float] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def request(self, key: str, coords: list) -> Optional[threading.Event]:
        with self._lock:
            if key in self._pending:
                return self._pending[key]
            if time.time() - self._failed.get(key, 0) < RETRY_AFTER:
                return None
            event = self._pending[key] = threading.Event()
            self._queue.put((key, coords, event))
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name='prestop-match', daemon=True)
                self._thread.start()
            return event

    def _run(self):
        while True:
            try:
                key, coords, event = self._queue.get(timeout=60)
            except queue.Empty:
                return
            try:
                def paced(points):
                    with _gate:
                        try:
                            return trace(points)
                        finally:
                            time.sleep(_gap())
                legs.put_many({key: match_shape(coords, paced)})
            except Exception as e:
                logger.warning('Map matching failed: %r', e)
                with self._lock:
                    self._failed[key] = time.time()
            finally:
                with self._lock:
                    self._pending.pop(key, None)
                event.set()
                close_old_connections()


matcher = _Matcher()


def matched(coords: list, deadline: Optional[float] = None) -> tuple[Optional[list], bool]:
    """(the feed shape map-matched onto the roads or None, whether it is still being matched). None:
    no match, or not matched yet. The first call for a shape starts matching it in the background
    and waits for it until `deadline`; a shape still matching then must not be kept as final."""
    if len(coords) < 2 or not settings.PRESTOP_VALHALLA_URL or not getattr(settings, 'PRESTOP_SHAPE_MATCH', True):
        return None, False
    key = match_key(coords)
    found = legs.get_many([key])
    if key not in found:
        event = matcher.request(key, coords)
        if event is None:  # failed a short while ago: the feed's own line for now
            return None, False
        if not event.wait(max(0.0, (deadline or 0) - time.monotonic())):
            return None, True
        found = legs.get_many([key])
    return found.get(key) or None, False


def repair(coords: list, stops: list[dict], deadline: Optional[float] = None, road_only: bool = False, reroute: Iterable[int] = ()) -> tuple[list, bool]:
    """A bus shape that follows roads between all stops. `stops` are dicts with lat/lon.

    Returns (geometry, complete). Missing legs are fetched in the background; the call
    waits for them until `deadline` (time.monotonic()) and is incomplete if they are late.
    `road_only` ignores the feed's shape: SŽ replacement buses come with the railway's, so every
    leg is routed, and a leg still being routed is a straight line between its stops. Otherwise the
    feed's shape is first map-matched onto the roads (`matched`), in the background like the legs.
    `reroute`: segments routed whatever the shape says (a bus leaving a bay drives out of it)."""
    on_roads, matching = None, False
    if road_only:
        coords = [[s['lon'], s['lat']] for s in stops]
    elif not shapeless(coords, stops):
        # The feed's line snapped onto the streets (sparse feed shapes cut corners through buildings);
        # what is still wrong after that (a stop far off it) is routed below. The offline road checks
        # describe the feed's own line, so they don't apply to a matched one.
        on_roads, matching = matched(coords, deadline)
        coords = on_roads or coords
    if len(stops) < 2:
        return coords, not matching
    bad = bad_segments(coords, stops, {} if on_roads else None)
    for i in reroute:
        if 0 <= i < len(bad):
            bad[i] = True
    if not any(bad):
        return coords, not matching
    keys = [leg_key(stops[i], stops[i + 1]) for i, is_bad in enumerate(bad) if is_bad]
    found = legs.get_many(keys)
    missing = set(keys) - set(found)
    if missing and settings.PRESTOP_VALHALLA_URL:
        events = []
        i = 0
        while i < len(bad):  # each run of consecutive bad segments is routed in one go
            if not bad[i]:
                i += 1
                continue
            j = i
            while j < len(bad) and bad[j]:
                j += 1
            events += worker.request(stops[i:j + 1], missing)
            i = j
        for event in events:
            if not event.wait(max(0.0, (deadline or 0) - time.monotonic())):
                break
        found = legs.get_many(keys)
        missing = set(keys) - set(found)
    return splice(coords, stops, bad, found), (not missing or not settings.PRESTOP_VALHALLA_URL) and not matching

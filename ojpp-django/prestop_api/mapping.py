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
# A delay this large (s, late or early) is believed only when the vehicle's own report confirms it: a bus still
# reporting the trip it finished hours ago (N0127, 19 Oct: its 07:05 run "+208 min" at 10:39) or matched to another
# run of its line (A6103 "+159 min") is shown as having no live data instead.
MAX_UNCONFIRMED_DELAY = 120 * 60
# A bus waits at its first stop for its time: a departure predicted earlier there is held to the timetable (D3, 22 Oct
# 2026: buses predicted 2-5 min early at their first stop left on time or later, IJPP:473334 -272 s left +268 s, and
# the board had dropped each while it stood there). Boards ask for departures this much earlier for them (s).
EARLY_START = 10 * 60
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
    """Origin/destination labels: the route's long name, else the two termini its variants' headsigns ("A - B") name
    most often (A6335 has no long name; most variants run Rateče – Ljubljana AP, one Rateče – Jesenice Integral)."""
    def ends(text):
        parts = re.split(r'\s[-–]\s', text or '')
        return (parts[0].strip(), parts[-1].strip()) if len(parts) > 1 else None
    if ends(route.get('longName')):
        return ends(route['longName'])
    named = [e for e in (ends(p.get('headsign')) for p in route.get('patterns') or []) if e]
    if named:
        popular = popular_ends([{'tripCount': 1, 'stops': [{'name': a}, {'name': b}]} for a, b in named], named[0])
        return popular or named[0]
    headsigns = [p.get('headsign') for p in route.get('patterns') or [] if p.get('headsign')]
    return (headsigns[0], headsigns[-1]) if headsigns else ('', '')


def popular_ends(patterns: list[dict], named: tuple[str, str]) -> Optional[tuple[str, str]]:
    """A line's two ends by where its trips actually go: each variant's first and last stop counts its trips, and the
    two busiest stops win ("Rateče – Ljubljana AP", not the feed's "Rateče – Jesenice Integral" when most buses run
    on to Ljubljana). Kept in the order of the feed's name `named` where it names one of them; None without trips."""
    from .stopgroups import similar
    votes: dict[str, int] = {}
    for p in patterns:
        stops = p.get('stops') or []
        if len(stops) < 2 or not p.get('tripCount'):
            continue
        ends = {stops[0]['name'], stops[-1]['name']}
        for name in ends:
            key = next((k for k in votes if similar(k, name)), name)
            votes[key] = votes.get(key, 0) + p['tripCount']
    top = sorted(votes, key=lambda k: -votes[k])[:2]
    if len(top) < 2:
        return None
    a, b = top
    busiest = max((p for p in patterns if len(p.get('stops') or []) > 1), key=lambda p: p.get('tripCount') or 0)
    if named[0] and similar(named[0], b) or named[1] and similar(named[1], a):
        a, b = b, a
    elif not any(n and (similar(n, a) or similar(n, b)) for n in named) and similar(busiest['stops'][0]['name'], b):
        a, b = b, a
    return a, b


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


def update_delay(update: dict) -> Optional[int]:
    for key in ('arrival', 'departure'):
        part = update.get(key) or {}
        if part.get('delay') is not None:
            return int(part['delay'])
    return None


def confirms(trip_update: Optional[dict], stop_id: Optional[str], stop_sequence: Optional[int]) -> bool:
    """The vehicle's report names where it is on the trip (its current or next stop, which the trip update covers):
    the position confirms the update's delay there. Without it a vehicle on another trip can't be told apart."""
    updates = (trip_update or {}).get('updates') or []
    return any((stop_id and u.get('stopId') == stop_id) or (stop_sequence is not None and u.get('stopSequence') == stop_sequence)
               for u in updates if update_delay(u) is not None)


def believable(delay: Optional[int], confirmed: bool) -> Optional[int]:
    """`delay`, or None ("no live data") when it is beyond MAX_UNCONFIRMED_DELAY and nothing confirms it."""
    return None if delay is not None and abs(delay) > MAX_UNCONFIRMED_DELAY and not confirmed else delay


def current_delay(trip_update: Optional[dict], stop_id: Optional[str], stop_sequence: Optional[int]) -> Optional[int]:
    """Delay at the vehicle's current/next stop, else the nearest following update."""
    if not trip_update:
        return None
    updates = trip_update['updates']
    for u in updates:
        if stop_id and u.get('stopId') == stop_id and update_delay(u) is not None:
            return update_delay(u)
    if stop_sequence is not None:
        later = [u for u in updates if (u.get('stopSequence') or 0) >= stop_sequence and update_delay(u) is not None]
        if later:
            return update_delay(min(later, key=lambda u: u.get('stopSequence') or 0))
    known = [u for u in updates if update_delay(u) is not None]
    return update_delay(known[-1]) if known else None


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

    def __init__(self, size: int = 6, age: float = HISTORY_AGE):
        self.size = size
        self.age = age
        self._reports: dict[str, deque] = {}
        self._swept = 0.0

    def observe(self, vehicle_id: str, stamp: float, lat: float, lon: float, now: float) -> list[tuple[float, float, float]]:
        reports = self._reports.setdefault(vehicle_id, deque(maxlen=self.size))
        if not reports or stamp > reports[-1][0]:
            reports.append((stamp, lat, lon))
        while reports and reports[0][0] < now - self.age:
            reports.popleft()
        if now - self._swept > self.age:
            self._swept = now
            self._reports = {k: v for k, v in self._reports.items() if v and v[-1][0] >= now - self.age}
            self._reports.setdefault(vehicle_id, reports)
        return list(reports)

    def recent(self, vehicle_id: str) -> list[tuple[float, float, float]]:
        return list(self._reports.get(vehicle_id) or ())

    def last(self) -> dict[str, tuple[float, float, float]]:
        """Each vehicle's latest report."""
        return {k: v[-1] for k, v in self._reports.items() if v}


def entity_vehicle_id(entity: dict) -> Optional[str]:
    """The id a feed entity's vehicle gets on the map (None: neither a trip nor its own id names its feed)."""
    v = entity.get('vehicle') or {}
    trip_id = (v.get('trip') or {}).get('tripId')
    raw = (v.get('vehicle') or {}).get('id') or entity.get('id') or trip_id
    if trip_id:
        return qualify(raw, trip_id.split(':', 1)[0])
    return raw if raw and QUALIFIED.match(raw) else None


# A vehicle the feed sends without a trip (Kranj city buses through the IJPP feed: IJPP:1302152 ran line 5 18:10 stop
# by stop, 3-4.5 min late, 22 Oct) is drawn on the run whose stops its path passed with one delay.
RUN_NEAR = 60          # m: a stop this close to the path between two reports was passed
RUN_STOPS = 3          # stops passed, at least
RUN_SPREAD = 240       # s: their delays agree within this
RUN_DELAY = 10 * 60    # s: and lie this close to the timetable
RUN_CLEAR = 5 * 60     # s: another run fitting as well must be this much further off, else it is unclear which
RUN_AFTER_END = 5 * 60  # s after its last stop (with the delay) a vehicle is no longer on that run


def _passes(track: list, lat: float, lon: float) -> list[float]:
    """When the path `track` [(epoch, lat, lon)] came within RUN_NEAR of a point: per stretch between two reports, the
    time at its closest approach."""
    from .geometry import KY, _kx
    kx = _kx(lat)
    pts = [(t, (lo - lon) * kx, (la - lat) * KY) for t, la, lo in track]
    out = []
    for (ta, ax, ay), (tb, bx, by) in zip(pts, pts[1:] or pts):
        dx, dy = bx - ax, by - ay
        f = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
        if math.hypot(ax + dx * f, ay + dy * f) <= RUN_NEAR:
            out.append(ta + (tb - ta) * f)
    return out


COPY_NEAR = 200  # m: a vehicle without a trip this close to a drawn one at each of its last reports is that one


def _position_at(track: list, t: float, slack: float = 10) -> Optional[tuple[float, float]]:
    """Where the path `track` [(epoch, lat, lon)] was at `t`: between two reports by time, or a report `slack` s away."""
    for (ta, la, lo), (tb, lb, lob) in zip(track, track[1:]):
        if ta <= t <= tb:
            f = (t - ta) / (tb - ta) if tb > ta else 0.0
            return la + (lb - la) * f, lo + (lob - lo) * f
    near = min(track, key=lambda p: abs(p[0] - t), default=None)
    return (near[1], near[2]) if near and abs(near[0] - t) <= slack else None


def same_path(track: list, reports: list) -> Optional[bool]:
    """Whether a vehicle without a trip is another vehicle under another feed's id: Kranj city buses report through
    MOKranj with their run and through IJPP without (IJPP:1302158 = MOKranj:KRJN601, 3-160 m apart, 22 Oct). True when
    its path `track` was within COPY_NEAR of the other at each of its `reports` [(epoch, lat, lon)] (at least 3
    compared), False when it was further at one, None when too few reports fall within its path."""
    from .geometry import KY, _kx
    compared = 0
    for t, la, lo in reports:
        at = _position_at(track, t)
        if at is None:
            continue
        if math.hypot((at[1] - lo) * _kx(la), (at[0] - la) * KY) > COPY_NEAR:
            return False
        compared += 1
    return True if compared >= 3 else None


def match_run(track: list, runs: list[dict], now: float) -> Optional[tuple[str, int, int]]:
    """(run id, delay s, index of its next stop) of the run a vehicle without a trip is on, from its recent path
    `track` [(epoch, lat, lon)], oldest first; `runs` [{'id', 'stops': [(lat, lon, scheduled epoch)]}]. A run fits when
    the path passed RUN_STOPS of its stops with delays within RUN_SPREAD of each other (in time order: a loop's stops
    count on the pass that fits) and the vehicle is not past its end. Only one run may fit clearly; None otherwise.
    The next stop follows the last one passed (on a loop the app needs it to place the bus on the right pass)."""
    fits = []
    for r in runs:
        seen = sorted((t - at, i) for i, (la, lo, at) in enumerate(r['stops']) for t in _passes(track, la, lo))
        best: tuple = ()
        for k, (low, _) in enumerate(seen):
            window = [(d, i) for d, i in seen[k:] if d - low <= RUN_SPREAD]
            stops = {i for _, i in window}
            if len(stops) > len(best[0] if best else ()):
                best = (stops, sorted(d for d, _ in window)[len(window) // 2])
        if not best or len(best[0]) < RUN_STOPS or abs(best[1]) > RUN_DELAY or now > r['stops'][-1][2] + best[1] + RUN_AFTER_END:
            continue
        nxt = max(best[0]) + 1
        while nxt < len(r['stops']) - 1 and r['stops'][nxt][2] + best[1] < track[-1][0]:
            nxt += 1  # passed since, by the timetable and its delay
        fits.append((-len(best[0]), abs(best[1]), r['id'], int(round(best[1])), min(nxt, len(r['stops']) - 1)))
    fits.sort()
    if not fits or (len(fits) > 1 and fits[1][0] == fits[0][0] and fits[1][1] - fits[0][1] < RUN_CLEAR):
        return None
    return fits[0][2], fits[0][3], fits[0][4]


class LooseVehicles:
    """Vehicles the feed sends without a trip, followed across feed updates: which of them is a drawn vehicle under
    another id (same_path) and which runs a run nobody else reports (match_run). Kranj city buses on 22 Oct 18:31-18:52:
    IJPP:1302158 and IJPP:1300652 were MOKranj:KRJN601 and KRKF884; 1302152 ran line 5, 1301556 line 7 from 18:40."""
    TRACK = 20 * 60   # s of path kept per vehicle
    STICK = 10 * 60   # s a copy stays one while too few reports compare
    TAKEN = 20 * 60   # s a run stays another vehicle's after it last reported it (it may have just ended it)
    AROUND = 2000     # m: drawn vehicles further than this from it are not compared

    def __init__(self):
        self.tracks = MotionHistory(size=80, age=self.TRACK)
        self.copies: dict[str, tuple[str, float]] = {}  # vehicle id -> (the drawn vehicle it is, when last seen so)
        self.taken: dict[str, float] = {}

    def assign(self, entities: list[dict], drawn_runs: Iterable[str], drawn: MotionHistory, runs, now: float,
               drops: Optional[list] = None) -> list[tuple[dict, str, int, Optional[str]]]:
        """(entity, run id, delay s, next stop id) for each of `entities` (no trip, fresh position) found on a run of `runs()` (called
        only when needed) that no drawn vehicle runs: `drawn_runs` this update, `drawn` their recent reports. The
        others' 'no trip id' notes (build_vehicles) get the reason they stay off the map."""
        from . import coverage
        from .geometry import KY, _kx
        for run_id in drawn_runs:
            self.taken[run_id] = now
        self.taken = {k: t for k, t in self.taken.items() if t >= now - self.TAKEN}
        last = drawn.last()
        found: dict[int, tuple] = {}
        reasons: dict[int, str] = {}
        candidates = None
        for e in entities:
            vehicle_id, v = entity_vehicle_id(e), e.get('vehicle') or {}
            pos = v.get('position') or {}
            if not vehicle_id or pos.get('latitude') is None or pos.get('longitude') is None or now - int(v.get('timestamp') or 0) > MAX_VEHICLE_AGE:
                continue
            lat, lon = pos['latitude'], pos['longitude']
            track = self.tracks.observe(vehicle_id, int(v.get('timestamp') or 0), lat, lon, now)
            kx = _kx(lat)
            near = [k for k, (_, la, lo) in last.items() if k != vehicle_id and math.hypot((lo - lon) * kx, (la - lat) * KY) <= self.AROUND]
            verdicts = {k: same_path(track, drawn.recent(k)) for k in near}
            was = self.copies.get(vehicle_id)
            other = next((k for k, same in verdicts.items() if same), None)
            if other is None and was and was[1] >= now - self.STICK and verdicts.get(was[0]) is None:
                other = was[0]  # too few of its reports fall within this path yet: still that one
            if other is not None:
                self.copies[vehicle_id] = (other, now if verdicts.get(other) else was[1])
                reasons[id(e)] = 'no trip id, a drawn vehicle'
                continue
            self.copies.pop(vehicle_id, None)
            if candidates is None:
                candidates = [r for r in runs() if r['id'] not in self.taken]
            match = match_run(track, candidates, now)
            if match:
                run_id, delay, nxt = match
                stop_ids = next(r for r in candidates if r['id'] == run_id).get('stopIds') or []
                found[id(e)] = (e, run_id, delay, stop_ids[nxt] if nxt < len(stop_ids) else None)
            else:
                reasons[id(e)] = 'no trip id, no run fits'
        per_run = Counter(found_run[1] for found_run in found.values())
        out = []
        for key, placed in found.items():
            if per_run[placed[1]] == 1:
                out.append(placed)
            else:
                reasons[key] = 'no trip id, two on one run'
        if drops is not None:
            placed = {id(p[0]) for p in out}
            kept = [d for d in drops if id(d['item']) not in placed and id(d['item']) not in reasons]
            drops[:] = kept
            for e in entities:
                if id(e) in reasons:
                    coverage.note(drops, reasons[id(e)], e)
        return out


def entity_trip(entity: dict, trip_updates: dict) -> Optional[str]:
    """The run a feed entity's vehicle is on: OTP's trip id where the feed names the run by an older timetable
    version's id (sources._with_old_ids: LPP 12D buses as IJPP:479040), else the feed's own."""
    trip_id = ((entity.get('vehicle') or {}).get('trip') or {}).get('tripId')
    return (trip_updates.get(trip_id) or {}).get('runId') or trip_id if trip_id else trip_id


def build_vehicles(positions: Iterable[dict], trip_updates: dict, trips: dict, routes: dict, stop_names: dict,
                   now: Optional[float] = None, history: Optional[MotionHistory] = None, drops: Optional[list] = None) -> list[dict]:
    """`drops`: collects each entity left out and why (coverage.note), for the coverage audit."""
    from . import abroad, coverage
    now = now or time.time()
    out = []
    positions = list(positions)

    def rank(e: dict) -> tuple:
        """Which report of a vehicle sent twice is drawn: one that can be (position, fresh), naming a well-formed run we
        know, the newest. Marprom sends a bus once with a bare trip id ("MARPROM:") and once with its run."""
        v = e.get('vehicle') or {}
        trip_id, pos = entity_trip(e, trip_updates) or '', v.get('position') or {}
        stamp = int(v.get('timestamp') or 0)
        return (pos.get('latitude') is not None and pos.get('longitude') is not None and now - stamp <= MAX_VEHICLE_AGE,
                bool(QUALIFIED.match(trip_id)), trip_id in trips, stamp)
    best: dict[str, dict] = {}
    for e in positions:
        vehicle_id = entity_vehicle_id(e)
        if vehicle_id is not None and (vehicle_id not in best or rank(e) > rank(best[vehicle_id])):
            best[vehicle_id] = e
    for e in positions:
        v = e.get('vehicle') or {}
        trip = v.get('trip') or {}
        trip_id, pos = entity_trip(e, trip_updates), v.get('position') or {}
        if not trip_id or pos.get('latitude') is None or pos.get('longitude') is None:
            coverage.note(drops, 'no trip id' if not trip_id else 'no position', e)
            continue
        stamp = int(v.get('timestamp') or 0)
        if now - stamp > MAX_VEHICLE_AGE:
            coverage.note(drops, 'stale', e)
            continue
        feed = trip_id.split(':', 1)[0]
        info = trips.get(trip_id) or {}
        route_id = info.get('routeId') or trip.get('routeId')
        route = routes.get(route_id) or {}
        if not route_id:
            coverage.note(drops, 'unknown trip, no line', e)
            continue
        descriptor = v.get('vehicle') or {}
        vehicle_id = entity_vehicle_id(e)
        if best[vehicle_id] is not e:
            coverage.note(drops, 'same vehicle twice', e)
            continue
        bearing = pos.get('bearing')
        speed = pos.get('speed')
        speed = float(speed) if isinstance(speed, (int, float)) and 0 <= speed < 70 else None
        stop_id = v.get('stopId')
        if stop_id and abroad.is_abroad_stop(stop_names.get(stop_id)):
            coverage.note(drops, 'abroad', e)
            continue  # on its way to or from its stops abroad: Slovenia only (abroad.py)
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
            'delaySeconds': believable(current_delay(trip_updates.get(trip_id), stop_id, v.get('currentStopSequence')),
                                       confirms(trip_updates.get(trip_id), stop_id, v.get('currentStopSequence'))),
            'quality': 'observed',
            # Motion hints: the client predicts the position between reports along the trip's shape.
            # Some feeds send bare prefixes (Marprom: "MARPROM:"); only well-formed ids are passed on.
            'tripId': trip_id if QUALIFIED.match(trip_id) else None,
            'speed': round(speed, 2) if speed is not None else None,
            'nextStopId': stop_id if stop_id and QUALIFIED.match(stop_id) else None,
            'stopped': stopped,
            'stoppedSince': iso(stopped_since) if stopped and stopped_since else None,
        })
        if out[-1]['delaySeconds'] is not None:
            out[-1]['delaySource'] = 'gtfs-rt'
        if is_replacement(route):  # an SŽ replacement bus with its own GPS: same look as the timetable-placed ones
            out[-1]['replacement'] = True
        if not fits_contract(out[-1]):
            out.pop()
            coverage.note(drops, 'failed contract', e)
    return out


VEHICLE_MODES = ('walk', 'bus', 'rail', 'bike', 'scooter', 'car')


def fits_contract(v: dict) -> bool:
    """The hard rules of the app's vehicle contract (src/contracts/transit.ts `vehicleSchema`). A vehicle breaking one
    is left out here (and by the app), never the whole answer: one bad field used to empty the map."""
    def number(x, low, high):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and low <= x <= high

    def qualified(x):
        return isinstance(x, str) and bool(QUALIFIED.match(x))
    return (all(qualified(v.get(k)) for k in ('id', 'operatorId', 'routeId'))
            and all(v.get(k) is None or qualified(v[k]) for k in ('tripId', 'nextStopId'))
            and all(isinstance(v.get(k), str) for k in ('name', 'routeName', 'destination', 'updatedAt'))
            and (v.get('nextStop') is None or isinstance(v['nextStop'], str))
            and number(v.get('latitude'), -90, 90) and number(v.get('longitude'), -180, 180)
            and v.get('mode') in VEHICLE_MODES
            and (v.get('bearing') is None or number(v['bearing'], 0, 360))
            and (v.get('delaySeconds') is None or number(v['delaySeconds'], -math.inf, math.inf))
            and (v.get('speed') is None or number(v['speed'], 0, math.inf)))


# ---------------------------------------------------------------- boards

# SŽ is the only rail operator in the feeds; its BUS routes ("BUS 61706") are replacement transport.
REPLACEMENT_AGENCIES = ['IJPP:1161']


def is_replacement(route: dict) -> bool:
    """An SŽ bus that runs instead of a train (nadomestni prevoz). Not "AVT": that is the avtovlak, the car-carrying
    train through the Bohinj tunnel (Bohinjska Bistrica - Most na Soči), which runs on the railway."""
    agency = (route.get('agency') or {}).get('gtfsId') or route.get('agencyId')
    name = (route.get('shortName') or '').upper()
    return agency in REPLACEMENT_AGENCIES and (route.get('mode') in ('BUS', 'COACH') or name.startswith('BUS '))


def _shows(vehicle_delay: Optional[int], delay: int) -> bool:
    """The trip's vehicle shows about this delay itself (within half an hour)."""
    return vehicle_delay is not None and abs(vehicle_delay - delay) <= 1800


UPDATE_AROUND = 3 * 3600  # s: a trip update sent this far from a run's times is about another day's run (trainlive.AROUND)


def update_day(update: Optional[dict], begin: int, end: int, day: Optional[int] = None) -> Optional[int]:
    """Which run a trip update is about, for the run from `begin` to `end` (its scheduled times) of service day `day`
    (OTP's serviceDay; else `begin`'s): 0 this one, -1 the run a day before, None OTP's placement stands (another
    day's, or sent at another time). Callers take the update only where OTP has no live times of its own: one naming
    this run's start date is about it, yet OTP left some out (D3, 22 Oct 2026: A6295 +19 min, LPP 25, N0128)."""
    if not update:
        return None
    named = (update.get('trip') or {}).get('startDate')
    if named:
        from zoneinfo import ZoneInfo
        when = begin if day is None else day + 12 * 3600  # serviceDay is noon less 12 h, also when the clocks change
        return 0 if named == datetime.fromtimestamp(when, ZoneInfo('Europe/Ljubljana')).strftime('%Y%m%d') else None
    sent = update.get('timestamp') or time.time()
    if begin - 86400 - UPDATE_AROUND <= sent <= end - 86400 + UPDATE_AROUND:
        return -1
    return 0 if begin - UPDATE_AROUND <= sent <= end + UPDATE_AROUND else None


def update_run(update: Optional[dict], stop_id: str, start: Optional[int], at: int, realtime: bool, effective: int,
               day: Optional[int] = None, position: Optional[int] = None) -> tuple[bool, int]:
    """OTP puts a trip update that names no start date on the trip's run of its own service day, so after midnight a
    train still out from yesterday had no live time and tonight's run of it had its delay (604 and IC 350, 20 Oct
    2026, 00:30). The update is about the run on its way when it was sent (`start`: the run's first departure, `at`:
    its time here, `day`: its service day): that run takes the update's delay here (at call `position`, when the trip
    calls here twice), and the run a day later has no live data from it."""
    about = update_day(update, at if start is None else start, at, day)
    if about == -1:
        return False, at
    if realtime or about is None:
        return realtime, effective
    calls = [u for u in update.get('updates') or [] if u.get('stopId') == stop_id and update_delay(u) is not None]
    call = next((u for u in calls if u.get('stopSequence') == position), calls[0] if calls else None)
    return (True, at + update_delay(call)) if call else (False, at)


def late_by_stop(updates: dict) -> dict[str, list[tuple[Optional[int], int]]]:
    """Stop id -> (live time or None, delay) of each trip update that has a run late there. OTP lists a run by its
    live time, or by its timetable when it left the run's update out (update_day): a board asks for that much earlier."""
    out: dict[str, list] = {}
    for update in updates.values():
        for u in update.get('updates') or []:
            delay = update_delay(u)
            if u.get('stopId') and delay and delay > 0:
                at = (u.get('departure') or {}).get('time') or (u.get('arrival') or {}).get('time')
                out.setdefault(u['stopId'], []).append((int(at) if at else None, delay))
    return out


def is_trip_end(st: dict, stop_id: str, end: str) -> bool:
    """Whether this call at `stop_id` is its trip's first (`end` 'departureStoptime') or last ('arrivalStoptime') call.
    The stop alone doesn't tell: a trip that starts and ends at one stop calls there twice (D3: A6385 at Radovljica,
    calls 1 and 16), so the call's position decides when both are known."""
    call = (st.get('trip') or {}).get(end) or {}
    if (call.get('stop') or {}).get('gtfsId') != stop_id:
        return False
    return call.get('stopPosition') is None or st.get('stopPosition') is None or call['stopPosition'] == st['stopPosition']


def copy_of(row: dict, runs: dict) -> Optional[dict]:
    """The row already listed that board row `row` repeats, else None; `runs` collects the rows seen, in board order.
    A run (line, scheduled time, destination) listed by two feeds is one bus (LPP's suburban lines are IJPP's too),
    and one trip at two stops of a group in one minute is one row. A feed's own trips are each a bus: A6196 runs
    twice at 13:10 (D3: two vehicles drove the two trips, as every such pair recorded on 2026-10-22, 82 of 82), so
    a row repeats another feed's only while that feed lists at least as many."""
    trip = row.get('tripId') or row.get('id') or ''
    by_feed = runs.setdefault((row.get('routeName'), row.get('scheduledAt'), fold(row.get('destination') or '')), {})
    same = next((r for rows in by_feed.values() for r in rows if row.get('tripId') and r.get('tripId') == row['tripId']), None)
    if same is not None:
        return same
    mine = by_feed.setdefault(trip.split(':', 1)[0], [])
    mine.append(row)
    return next((rows[len(mine) - 1] for rows in by_feed.values() if rows is not mine and len(rows) >= len(mine)), None)


def build_board(stop_id: str, stoptimes: Iterable[dict], kind: str, alerts: list[dict],
                live: Optional[dict[str, Optional[int]]] = None, updates: Optional[dict] = None, drops: Optional[list] = None) -> list[dict]:
    """`live`: trip id -> the delay its vehicle shows (build_vehicles); a delay beyond MAX_UNCONFIRMED_DELAY stays on
    the board only when the trip's vehicle shows it too, else the row has no live data. `updates`: the trip updates
    (trip_update_index), for the run each is about (update_run). `drops`: the stoptimes left out and why (coverage.note)."""
    from . import abroad, coverage, stopfix
    live, updates = live or {}, updates or {}
    out = []
    for st in stoptimes:
        trip = st.get('trip') or {}
        route = trip.get('route') or {}
        # Arrivals skip trips that start here; departures skip trips that end here.
        starts, ends = is_trip_end(st, stop_id, 'departureStoptime'), is_trip_end(st, stop_id, 'arrivalStoptime')
        if kind == 'arrival' and (starts or st.get('dropoffType') == 'NONE'):
            coverage.note(drops, 'starts here' if starts else 'no setting down', st)
            continue
        if kind == 'departure' and (ends or st.get('pickupType') == 'NONE'):
            coverage.note(drops, 'ends here' if ends else 'no picking up', st)
            continue
        day = st['serviceDay']
        scheduled = day + (st['scheduledArrival'] if kind == 'arrival' else st['scheduledDeparture'])
        realtime = bool(st.get('realtime'))
        canceled = st.get('realtimeState') == 'CANCELED'
        effective = day + (st['realtimeArrival'] if kind == 'arrival' else st['realtimeDeparture'])
        first_departure = (trip.get('departureStoptime') or {}).get('scheduledDeparture')
        realtime, effective = update_run(updates.get(trip.get('gtfsId')), stop_id, day + first_departure if isinstance(first_departure, int) else None,
                                         scheduled, realtime, effective, day, st.get('stopPosition'))
        if realtime and believable(effective - scheduled, _shows(live.get((st.get('trip') or {}).get('gtfsId')), effective - scheduled)) is None:
            realtime, effective = False, scheduled
        if kind == 'departure' and starts:  # it waits at its first stop for its time (EARLY_START)
            effective = max(effective, scheduled)
        end = ((trip.get('departureStoptime' if kind == 'arrival' else 'arrivalStoptime') or {}).get('stop') or {})
        other_end = stopfix.renamed(end.get('gtfsId'), end.get('name'))
        if end.get('gtfsId') == stop_id:  # a loop: its own stop says nothing about where it goes, its headsign does
            other_end = st.get('headsign') or trip.get('tripHeadsign') or other_end
        elif abroad.is_abroad_stop(other_end):
            other_end = abroad.place(other_end)
        elif mode_of(route.get('mode')) == 'rail':  # an international train: its real end abroad
            ends = abroad.train_ends(route_name(route), *((other_end, None) if kind == 'arrival' else (None, other_end)))
            other_end = ends[0 if kind == 'arrival' else 1] or other_end
        route_id = route.get('gtfsId') or f'{stop_id.split(":")[0]}:unknown'
        trip_id = trip.get('gtfsId') or f'{route_id}-{scheduled}'
        # When the trip leaves its first stop ("HH:MM"): what its departure usually does is learned under it (A5).
        start = (trip.get('departureStoptime') or {}).get('scheduledDeparture')
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
            **({'delaySource': 'gtfs-rt'} if realtime and not canceled else {}),  # OTP's realtime is the GTFS-RT feed's
            'canceled': canceled,
            'platform': (st.get('stop') or {}).get('platformCode') or None,
            'alertIds': [a['id'] for a in alerts if (stop_id in a['stopIds'] or route_id in a['routeIds']) and alert_active(a, scheduled)],
            **({'tripStart': f'{start // 3600 % 24:02d}:{start % 3600 // 60:02d}'} if isinstance(start, int) else {}),
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
        operator = (a.get('agency') or {}).get('gtfsId') or (sorted(agencies)[0] if agencies else None)
        if not operator:
            # SŽ's notices about lines OTP finds no route on (Ljubljana - Villach, Sežana - Opčine) are SŽ's all the same.
            operator = REPLACEMENT_AGENCIES[0] if 'SZ-OVIRA' in _decoded(a['id']) else f'{a.get("feed") or "otp"}:unknown'
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
                  'nextbike_cf': 'Zanaprej (Nomago Bikes)', 'nextbike_cn': 'KolesCE (Nomago Bikes)', 'nextbike_cx': 'KoroBajk (Nomago Bikes)',
                  # Smart City bikes networks: the town from their stations' names (OTP, 2026-10-18), docs/research/2026-10-18-sharing-systems.md.
                  'scbikes_gbike': 'Gorenjska.bike (Kranj)', 'scbikes_gonm': 'GoNM (Dolenjska)', 'scbikes_sobota': 'Sobota bikes (Pomurje)',
                  'scbikes_posbikes': 'Posbikes (Postojna)', 'scbikes_biciklanc': 'Biciklanc (Vrhnika)', 'scbikes_kras': 'Kras bikes (Sežana)',
                  'scbikes_pors': 'PorS (Rogaška Slatina)', 'scbikes_pokolo': 'Pokolo (Litija)', 'scbikes_kulu': 'KuLu (Ajdovščina)'}


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


def _electric_networks(stations: Iterable[dict]) -> set[str]:
    """Networks whose fleet has an electric type, judged over all their stations: only these report e-bike counts."""
    # Spaces too: with every e-bike out, OTP may still list e-bike spaces.
    return {s.get('network') or s['stationId'].split(':')[0] for s in stations
            if any((t.get('vehicleType') or {}).get('propulsionType') in ELECTRIC
                   for key in ('availableVehicles', 'availableSpaces') for t in (s.get(key) or {}).get('byType') or [])}


def _rack_details(s: dict, electric: bool = True) -> dict:
    """Capacity, free docks, e-bikes and the operator's app links; unknown values are left out (never 0).
    `ebikesAvailable` is left out too when the station's network has no e-bikes at all (BicikeLJ)."""
    out = {}
    count = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < NO_LIMIT else None
    if count(s.get('capacity')) is not None:
        out['capacity'] = s['capacity']
    if count(s.get('spacesAvailable')) is not None:
        out['docksAvailable'] = s['spacesAvailable']
    by_type = (s.get('availableVehicles') or {}).get('byType') or []
    typed = [t for t in by_type if (t.get('vehicleType') or {}).get('propulsionType')]
    if electric and typed:
        out['ebikesAvailable'] = sum(count(t.get('count')) or 0 for t in typed if t['vehicleType']['propulsionType'] in ELECTRIC)
    elif electric and s.get('vehiclesAvailable') == 0:
        out['ebikesAvailable'] = 0
    uris = {k: v for k, v in (s.get('rentalUris') or {}).items() if k in ('web', 'android', 'ios') and isinstance(v, str) and v.startswith('http')}
    if uris:
        out['rentalUris'] = uris
    return out


ZONE_RADIUS = 40  # m: a vehicle this close to a parking zone of its system stands in it


def _near(lat1: float, lon1: float, lat2: float, lon2: float, metres: float) -> bool:
    dy = (lat1 - lat2) * 111_320
    dx = (lon1 - lon2) * 111_320 * math.cos(math.radians(lat1))
    return dx * dx + dy * dy <= metres * metres


STAND_RADIUS = 15  # m: stations of different networks this close stand at one place (one marker on the map)


def _group_stands(stations: list[dict]) -> None:
    """Gives the stations of different networks at one place a shared `groupId` (each keeps its own numbers).
    Every two stations of a group are within STAND_RADIUS, so a chain of near ones never joins far ends; the
    closest pairs are joined first. Ids stay the same while the stations do."""
    # Cells at least STAND_RADIUS wide, so a station's neighbours are in the 3 x 3 cells around it: twice the degrees
    # across, since a degree of longitude is at most half as long as one of latitude south of 60°N.
    cell = STAND_RADIUS / 111_320
    grid: dict[tuple[int, int], list[int]] = {}
    for i, s in enumerate(stations):
        grid.setdefault((int(s['latitude'] // cell), int(s['longitude'] // (2 * cell))), []).append(i)

    def gap(a: dict, b: dict) -> float:
        dy = (a['latitude'] - b['latitude']) * 111_320
        dx = (a['longitude'] - b['longitude']) * 111_320 * math.cos(math.radians(a['latitude']))
        return math.hypot(dx, dy)

    pairs = []
    for (y, x), members in grid.items():
        near = [j for dy in (-1, 0, 1) for dx in (-1, 0, 1) for j in grid.get((y + dy, x + dx), ())]
        pairs += [(d, i, j) for i in members for j in near if i < j and (d := gap(stations[i], stations[j])) <= STAND_RADIUS]
    group = {i: {i} for i in range(len(stations))}
    for _, i, j in sorted(pairs, key=lambda p: (p[0], stations[p[1]]['id'], stations[p[2]]['id'])):
        if group[i] is group[j] or any(gap(stations[a], stations[b]) > STAND_RADIUS for a in group[i] for b in group[j]):
            continue
        joined = group[i] | group[j]
        for k in joined:
            group[k] = joined
    for members in {id(g): g for g in group.values()}.values():
        if len({stations[k]['providerId'].rpartition(':')[0] for k in members}) > 1:
            name = 'stand:' + min(stations[k]['id'] for k in members)
            for k in members:
                stations[k]['groupId'] = name


def build_rentals(stations: Iterable[dict], vehicles: Iterable[dict], now: Optional[float] = None) -> list[dict]:
    now = now or time.time()
    vehicles = list(vehicles)
    stations = list(stations)
    electric = _electric_networks(stations)
    # Networks with free-floating vehicles (Bolt): their stations without docks are parking zones where the
    # e-bikes and scooters are left, a system of their own rather than a dock.
    floating = {(v.get('rentalNetwork') or {}).get('networkId') or v.get('network') or v['vehicleId'].split(':')[0] for v in vehicles}
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
            **_rack_details(s, network in electric),
        })
        if network in floating and 'docksAvailable' not in out[-1]:
            out[-1]['zone'] = True
            out[-1]['canReturn'] = out[-1]['canReturn'] or s.get('allowDropoff') is not False
    _group_stands(out)
    # A vehicle standing in its system's parking zone is already in that zone's count (Bolt reports it twice).
    zones: dict[str, list[tuple[float, float]]] = {}
    for r in out:
        if r.get('zone'):
            zones.setdefault(r['id'].split(':')[0], []).append((r['latitude'], r['longitude']))
    for v in vehicles:
        mode = _rental_mode([(v.get('vehicleType') or {}).get('formFactor')])
        if not mode or v.get('lat') is None or v.get('operative') is False:
            continue
        network = (v.get('rentalNetwork') or {}).get('networkId') or v.get('network') or v['vehicleId'].split(':')[0]
        if any(_near(v['lat'], v['lon'], lat, lon, ZONE_RADIUS) for lat, lon in zones.get(network, ())):
            continue
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


def encode_polyline(coords: list, precision: int = 5) -> str:
    """[[lon, lat], ...] -> Google encoded polyline (decode_polyline's inverse)."""
    out, last, factor = [], (0, 0), 10 ** precision
    for lon, lat in coords:
        here = (round(lat * factor), round(lon * factor))
        for value in (here[0] - last[0], here[1] - last[1]):
            value = ~(value << 1) if value < 0 else value << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1f)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last = here
    return ''.join(out)


def thin(coords: list, limit: int = 400) -> list:
    if len(coords) <= limit:
        return coords
    step = len(coords) / (limit - 1)
    return [coords[int(i * step)] for i in range(limit - 1)] + [coords[-1]]

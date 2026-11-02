"""Slovenia's railway track (data/slovenia_rail.json, from OpenStreetMap by scripts/build-slovenia-rail.py), for train
lines that must follow it.

The feed's shapes mostly lie on the track, but not everywhere: north of Maribor most of them still run through the old
Pekel tunnel, abandoned for the new line; near Semič and Pavlovci they cut across where the line was rebuilt; a
pattern with no shape is its stops joined by straight lines. `follow` keeps a shape where it lies on the track and,
where it leaves it, takes the way along the track from where it left to where it comes back. The track is read from
the file only; nothing here asks OpenStreetMap.
"""
import hashlib
import heapq
import json
import logging
import math
import threading
from pathlib import Path

from . import geometry

logger = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parent / 'data' / 'slovenia_rail.json'
STEP = 25.0     # m between the track's points
LINK = 20.0     # m: track points this close are joined (a switch, a crossover, the second track the file leaves out)
OFF = 35.0      # m: a shape further than this from any track has left it
CLOSE = 12.0    # m: a shape this close to the track is back on it
END = 150.0     # m: a shape starting or ending this close to the track (a station beside it) starts or ends on it
DETOUR = 2.5    # the way along the track may be this many times as long as the stretch it replaces ...
SLACK = 1000.0  # ... plus this; a longer way is another line, so the stretch stays as it is
STRAY = 50.0    # m: a line further than this from the track does not follow it (the check, `strays`)
REACH = 2000.0  # m: `strays` reports how far a stretch strays up to this
CHORD = 1000.0  # m: a straight segment this long is a chord unless the track runs straight there too
CELL = 50.0
FINE = 10.0     # m between the track's points when telling whether a shape lies on it
_KX = 111_320 * math.cos(math.radians(46.1))


def _xy(p) -> tuple[float, float]:
    return p[0] * _KX, p[1] * geometry.KY


class Track:
    def __init__(self, tracks: list[list]):
        self.points: list[list] = []
        self.xy: list[tuple[float, float]] = []
        self.next: list[int] = []  # the following point of the same track, or -1
        self.links: list[list[tuple[int, float]]] = []
        self.left: list[list] = []  # stretches `follow` found off the track but had no way along it for: [from, to]
        self.grid: dict[tuple[int, int], list[int]] = {}
        for coords in tracks:
            dense = geometry.densify(coords, STEP)
            start = len(self.points)
            for k, p in enumerate(dense):
                i = start + k
                self.points.append(p)
                self.xy.append(_xy(p))
                self.next.append(i + 1 if k + 1 < len(dense) else -1)
                self.links.append([])
                self.grid.setdefault(self._cell(*self.xy[i]), []).append(i)
                if k:
                    self._join(i - 1, i)
        for i, (x, y) in enumerate(self.xy):
            for j in self._around(x, y, LINK):
                if j > i and self.next[i] != j and self.next[j] != i:
                    self._join(i, j)
        # For `on`: the track every FINE metres, in cells OFF wide, so a point looks at its own cell and the 8 around it.
        self.fine: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for coords in tracks:
            for p in geometry.densify(coords, FINE):
                x, y = _xy(p)
                self.fine.setdefault((int(x // OFF), int(y // OFF)), []).append((x, y))

    @staticmethod
    def _cell(x: float, y: float) -> tuple[int, int]:
        return int(x // CELL), int(y // CELL)

    def _join(self, i: int, j: int) -> None:
        d = math.dist(self.xy[i], self.xy[j])
        self.links[i].append((j, d))
        self.links[j].append((i, d))

    def _around(self, x: float, y: float, radius: float):
        cx, cy = self._cell(x, y)
        span = math.ceil(radius / CELL)
        for a in range(cx - span, cx + span + 1):
            for b in range(cy - span, cy + span + 1):
                for i in self.grid.get((a, b), ()):
                    if (self.xy[i][0] - x) ** 2 + (self.xy[i][1] - y) ** 2 <= radius * radius:
                        yield i

    def on(self, x: float, y: float) -> bool:
        """Within OFF of the track (to FINE / 2)."""
        cx, cy = int(x // OFF), int(y // OFF)
        return any((px - x) ** 2 + (py - y) ** 2 <= OFF * OFF
                   for a in (cx - 1, cx, cx + 1) for b in (cy - 1, cy, cy + 1) for px, py in self.fine.get((a, b), ()))

    def distance(self, x: float, y: float, radius: float = OFF) -> float:
        """Metres from the nearest track, or `radius` when none is closer."""
        best = radius
        # A segment within `radius` has a point within radius + STEP: each point stands for the segment it starts.
        for i in self._around(x, y, radius + STEP):
            ax, ay = self.xy[i]
            b = self.next[i]
            if b < 0:
                best = min(best, math.hypot(x - ax, y - ay))
                continue
            dx, dy = self.xy[b][0] - ax, self.xy[b][1] - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ((dx * dx + dy * dy) or 1e-9)))
            best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
        return best

    def nearest(self, x: float, y: float, radius: float) -> int | None:
        return min(self._around(x, y, radius), key=lambda i: (self.xy[i][0] - x) ** 2 + (self.xy[i][1] - y) ** 2, default=None)

    def way(self, a: int, b: int, limit: float) -> list[int] | None:
        """The track points from `a` to `b` along the track (A*), or None when that is longer than `limit` metres."""
        goal = self.xy[b]
        h = lambda i: math.dist(self.xy[i], goal)  # noqa: E731
        best = {a: 0.0}
        came: dict[int, int] = {}
        queue = [(h(a), 0.0, a)]
        while queue:
            _, cost, i = heapq.heappop(queue)
            if i == b:
                path = [b]
                while path[-1] != a:
                    path.append(came[path[-1]])
                return path[::-1]
            if cost > best.get(i, math.inf):
                continue
            for j, d in self.links[i]:
                c = cost + d
                if c < best.get(j, math.inf) and c + h(j) <= limit:
                    best[j] = c
                    came[j] = i
                    heapq.heappush(queue, (c + h(j), c, j))
        return None

    def follow(self, coords: list) -> list:
        """`coords` where they lie on the track, and the way along it where they leave it."""
        if len(coords) < 2:
            return coords
        points = geometry.densify(coords, STEP)
        xy = [_xy(p) for p in points]
        off = [not self.on(*q) for q in xy]
        if not any(off):
            return coords
        out: list = []
        i, n = 0, len(points)
        kept = 0  # out ends with points[kept:i] as they are; before them it may end with a way along the track
        while i < n:
            if not off[i]:
                out.append(points[i])
                i += 1
                continue
            j = i
            while j + 1 < n and off[j + 1]:
                j += 1
            # A shape drifts off gradually: the way replaces it from where it is beside the track again (CLOSE), not
            # from where it is just within OFF, or the line jogs sideways onto the track.
            while i - 1 > kept and self.distance(*xy[i - 1]) > CLOSE:
                i -= 1
                out.pop()
            while j + 1 < n and (off[j + 1] or self.distance(*xy[j + 1]) > CLOSE):
                j += 1
            way = self._way(points, xy, i, j)
            if way is None:
                out += points[i:j + 1]
                self.left.append([points[i], points[j]])
                i = kept = j + 1
                continue
            # The way starts at the track point nearest the point before the run and ends at the one nearest the point
            # after it: those two give way to it, or the line would step back to them.
            if i > kept:
                out.pop()
            out += way
            i = kept = j + 2
        return geometry.simplify(out, geometry.SHAPE_POINTS)

    def strays(self, coords: list, limit: float = STRAY) -> list[dict]:
        """The stretches of `coords` further than `limit` from the track, with their length and worst distance: the
        check that a line follows the track."""
        points = geometry.densify(coords, STEP)
        far = [0.0 if self.on(*_xy(p)) else self.distance(*_xy(p), limit + 1) for p in points]
        out, i = [], 0
        while i < len(points):
            if far[i] <= limit:
                i += 1
                continue
            j = i
            while j + 1 < len(points) and far[j + 1] > limit:
                j += 1
            out.append({'from': points[i], 'to': points[j], 'length': geometry.cumulative(points[i:j + 1])[-1],
                        'worst': max(self.distance(*_xy(p), REACH) for p in points[i:j + 1])})
            i = j + 1
        return out

    def chords(self, coords: list, length: float = CHORD, limit: float = STRAY) -> list[list]:
        """The segments of `coords` longer than `length` that leave the track by more than `limit` on the way: a
        straight line from station to station where the track curves. A long straight on straight track is not one."""
        return [[a, b] for a, b in zip(coords, coords[1:]) if geometry.distance(a, b) > length and self.strays([a, b], limit)]

    def _way(self, points: list, xy: list, i: int, j: int) -> list | None:
        """The way along the track in place of the off-track run i..j, between the points on the track either side of
        it; at a loose end, from the track point nearest that end if it lies within END of the track. None when there is
        no such way."""
        n = len(points)
        start = i - 1 if i > 0 else (i if self.distance(*xy[i], END) < END else None)
        stop = j + 1 if j + 1 < n else (j if self.distance(*xy[j], END) < END else None)
        if start is None or stop is None:
            return None
        a, b = self.nearest(*xy[start], END), self.nearest(*xy[stop], END)
        if a is None or b is None:
            return None
        path = self.way(a, b, DETOUR * geometry.cumulative(points[start:stop + 1])[-1] + SLACK)
        return None if path is None else [self.points[k] for k in path]


def _decode(flat: list[int]) -> list[list[float]]:
    x, y = flat[0], flat[1]
    out = [[x / 1e5, y / 1e5]]
    for k in range(2, len(flat), 2):
        x, y = x + flat[k], y + flat[k + 1]
        out.append([x / 1e5, y / 1e5])
    return out


def load() -> Track:
    """The track from the file: about a second and 75 MB, so a caller keeps it only while it needs it."""
    return Track([_decode(t) for t in json.loads(DATA.read_text(encoding='utf-8'))['tracks']])


KEEP = 120.0  # s the track stays loaded after its last use by `along`: only while new shapes are being worked out
STORE_PREFIX = 't:'  # RoadLeg keys of shapes along the track
_held: dict = {'track': None, 'timer': None}
_holding = threading.Lock()
_version: dict = {'value': None}


def _let_go() -> None:
    with _holding:
        _held.update(track=None, timer=None)


def _track_version() -> str:
    """Changes with the track file, so a new track means new shapes, and the old rows are simply no longer asked for."""
    if _version['value'] is None:
        _version['value'] = hashlib.sha1(DATA.read_bytes()).hexdigest()
    return _version['value']


def store_key(coords: list) -> str:
    """RoadLeg key of a shape along this track: a hash of the track file and the shape's points (5 decimals)."""
    text = ';'.join(f'{x:.5f},{y:.5f}' for x, y in coords)
    return STORE_PREFIX + hashlib.sha1(f'{_track_version()}|{text}'.encode()).hexdigest()


def _stored(key: str) -> list | None:
    try:
        from .models import RoadLeg
        row = RoadLeg.objects.filter(key=key).first()
        return row.geometry if row and len(row.geometry) >= 2 else None
    except Exception as e:  # worked out again: slower, nothing more
        logger.warning('Rail shapes unavailable: %r', e)
        return None


def _store(key: str, coords: list) -> None:
    try:
        from .models import RoadLeg
        RoadLeg.objects.bulk_create([RoadLeg(key=key, geometry=coords)], ignore_conflicts=True)
    except Exception as e:
        logger.warning('Could not store a rail shape: %r', e)


def _follow(coords: list) -> list | None:
    """Track.follow with the track held only while new shapes are being worked out (75 MB, see `load`); None when the
    file cannot be read."""
    with _holding:
        track = _held['track']
        if track is None:
            try:
                track = _held['track'] = load()
            except (OSError, ValueError, KeyError) as e:
                logger.warning('Rail track not read: %r', e)
                return None
        if _held['timer']:
            _held['timer'].cancel()
        _held['timer'] = threading.Timer(KEEP, _let_go)
        _held['timer'].daemon = True
        _held['timer'].start()
    found = track.follow(coords)
    track.left.clear()  # kept for raillines' rebuild; here it would only grow
    return found


def along(coords: list) -> list:
    """`coords` along the track for a train's shape, worked out once and kept in the RoadLeg table: every worker and
    restart after that reads it without loading the track. As they are when the track cannot be read: a line drawn off
    the track beats no line."""
    try:
        key = store_key(coords)
    except OSError as e:
        logger.warning('Rail track not read: %r', e)
        return coords
    found = _stored(key)
    if found is not None:
        return found
    found = _follow(coords)
    if found is None:
        return coords
    _store(key, found)
    return found

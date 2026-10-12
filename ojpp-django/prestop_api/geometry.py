"""Shape geometry in metres on a local plane: simplification, lengths, stop projection,
slicing and points along a shape. Coordinates are [lon, lat]."""
import bisect
import math
from typing import Optional

MAX_POINTS = 400
SHAPE_POINTS = 1500  # trip and line shapes: Douglas-Peucker keeps its 3 m tolerance on long, winding routes
DENSE_STEP = 30.0    # m between points in shapes sent to the app, which moves vehicles along them
KY = 110_574


def _kx(lat0: float) -> float:
    return 111_320 * math.cos(math.radians(lat0))


def _local(coords: list, lat0: float) -> list[tuple[float, float]]:
    """[lon, lat] -> metres on a local equirectangular plane (accurate to ~0.1 % in Slovenia)."""
    kx = _kx(lat0)
    return [(c[0] * kx, c[1] * KY) for c in coords]


def simplify(coords: list, limit: int = MAX_POINTS) -> list:
    """Douglas–Peucker in metres; the tolerance grows until at most `limit` points remain."""
    if len(coords) <= 2:
        return coords
    pts = _local(coords, coords[0][1])
    tolerance = 3.0
    while True:
        keep = [False] * len(pts)
        keep[0] = keep[-1] = True
        stack = [(0, len(pts) - 1)]
        while stack:
            a, b = stack.pop()
            (ax, ay), (bx, by) = pts[a], pts[b]
            dx, dy = bx - ax, by - ay
            norm = math.hypot(dx, dy)
            best, index = 0.0, -1
            for i in range(a + 1, b):
                # A loop (Marprom G3) ends where it starts: no line between the ends, so the distance to the end.
                d = abs(dy * (pts[i][0] - ax) - dx * (pts[i][1] - ay)) / norm if norm > 1e-6 else math.hypot(pts[i][0] - ax, pts[i][1] - ay)
                if d > best:
                    best, index = d, i
            if best > tolerance and index > 0:
                keep[index] = True
                stack += [(a, index), (index, b)]
        result = [c for c, k in zip(coords, keep) if k]
        if len(result) <= limit:
            return result
        tolerance *= 1.6


def _turn(a: tuple, b: tuple, c: tuple) -> float:
    """Degrees the line turns at `b` (0 straight on, 180 straight back)."""
    h1 = math.atan2(b[1] - a[1], b[0] - a[0])
    h2 = math.atan2(c[1] - b[1], c[0] - b[0])
    return abs((math.degrees(h2 - h1) + 180) % 360 - 180)


SPUR = 40.0       # m: an end piece this short that turns sharply onto the line is a stub to the stop's point
SPUR_TURN = 60.0  # degrees
SPUR_TINY, SPUR_TINY_TURN = 5.0, 15.0  # m, degrees: a stub this short counts from a shallower turn


def trim_spurs(coords: list, length: float = SPUR, turn: float = SPUR_TURN) -> list:
    """A rail shape without the stubs SŽ's shapes start and end with: the station's point sits ~10 m beside
    the track, so the line stepped sideways onto it (a visible kink zoomed in). Also drops short out-and-back
    spikes to a stop in the middle. The stops are still projected onto the line, so nothing else moves."""
    if len(coords) < 3:
        return coords
    pts = _local(coords, coords[0][1])
    seg = lambda i, j: math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1])  # noqa: E731

    def stub(order: list[int]) -> int:
        """How many points the stub at this end has: up to the first sharp turn within `length` of the end."""
        run = 0.0
        for k in range(1, len(order) - 1):
            run += seg(order[k - 1], order[k])
            if run >= length:
                break
            # A stub of a metre or two needs only a slight turn to bend a train.
            if _turn(pts[order[0]], pts[order[k]], pts[order[k + 1]]) > (turn if run > SPUR_TINY else SPUR_TINY_TURN):
                return k
        return 0
    keep = list(range(len(coords)))
    keep = keep[stub(keep):]
    if len(keep) > 2:
        keep = keep[:len(keep) - stub(keep[::-1])]
    out = [keep[0]]
    for k in range(1, len(keep) - 1):
        a, b, c = out[-1], keep[k], keep[k + 1]
        if seg(a, b) < length and seg(b, c) < length and _turn(pts[a], pts[b], pts[c]) > 150:
            continue  # out to the stop's point and straight back
        out.append(b)
    out.append(keep[-1])
    return smooth_kinks([coords[i] for i in out])


KINK_TURN = 10.0    # degrees: a sharp turn at one point â€¦
KINK_SEG = 80.0     # â€¦ between segments this short (sparse shapes turn more per point on a real curve)
KINK_JOIN = 40.0    # m: turns this close to a sharp one belong to its kink
KINK_NOISE = 2.0    # degrees: smaller turns are left out
KINK_CANCEL = 20.0  # degrees of a kink's turning that cancel out: a zigzag or a step aside, not a curve
KINK_LOOP = 270.0   # degrees: a short run turning this far round is a loop


def _signed(a: tuple, b: tuple, c: tuple) -> float:
    h1 = math.atan2(b[1] - a[1], b[0] - a[0])
    h2 = math.atan2(c[1] - b[1], c[0] - b[0])
    return (math.degrees(h2 - h1) + 180) % 360 - 180


def _kinks(pts: list, cum: list[float]) -> list[tuple[int, int]]:
    """(first, last) point of each kink in a rail line in metres. A real curve turns one way, so its turns
    add up, and a reversal turns about 180Â° one way. Through a step aside onto a station's point, or onto
    the next track, the turns cancel out; a short loop turns all the way round."""
    distinct = [0]
    for i in range(1, len(pts)):
        if math.dist(pts[i], pts[distinct[-1]]) > 0.5:
            distinct.append(i)
    # Every point's turn (noise under KINK_NOISE left out); a sharp one seeds a kink, which takes in
    # the turns within KINK_JOIN of it, so a small zigzag (8°, −16°, 9°) counts as a whole.
    turns: list[tuple[int, float, bool]] = []
    for a, b, c in zip(distinct, distinct[1:], distinct[2:]):
        turn = _signed(pts[a], pts[b], pts[c])
        if abs(turn) > KINK_NOISE:
            short = math.dist(pts[a], pts[b]) <= KINK_SEG and math.dist(pts[b], pts[c]) <= KINK_SEG
            turns.append((b, turn, short and abs(turn) > KINK_TURN))
    spans: list[list[float]] = []
    for b, _, sharp in turns:
        if not sharp:
            continue
        if spans and cum[b] - KINK_JOIN <= spans[-1][1]:
            spans[-1][1] = cum[b] + KINK_JOIN
        else:
            spans.append([cum[b] - KINK_JOIN, cum[b] + KINK_JOIN])
    out = []
    k = 0
    for lo, hi in spans:
        while k < len(turns) and cum[turns[k][0]] < lo:
            k += 1
        group = []
        while k < len(turns) and cum[turns[k][0]] <= hi:
            group.append(turns[k])
            k += 1
        net = sum(t for _, t, _ in group)
        turning = sum(abs(t) for _, t, _ in group)
        if turning - abs(net) >= KINK_CANCEL or abs(net) >= KINK_LOOP:
            out.append((group[0][0], group[-1][0]))
    return out


CROSSOVER_PARALLEL = 6.0  # degrees: in and out of a kink this close in heading are two parallel tracks
CROSSOVER_MIN, CROSSOVER_MAX = 40.0, 120.0  # m of approach each side of a kink, 6 m per metre of sideways shift


def smooth_kinks(coords: list) -> list:
    """A rail shape without the zigzags where it steps sideways onto a station's point in the middle of a
    route, or jumps to the next track within a few metres (Zidani Most: two 90Â° turns 9 m apart, the line
    leaving on a track 7 m beside the one it came in on), which bent the train models. Nearly every station
    of SÅ½'s shapes has one (16,304 turns over 15Â° in 726 patterns on 2026-10-11).

    Where the line runs straight in and out, the stretch becomes one gentle crossover: straight from well
    before the kink to well after it (6 m of approach per metre of shift, 40â€“120 m each side), like a real
    turnout. In a curve, only the kink's own points go."""
    n = len(coords)
    if n < 3:
        return coords
    pts = _local(coords, coords[0][1])
    cum = cumulative(coords)
    kinks = _kinks(pts, cum)
    if not kinks:
        return coords
    total = cum[-1]

    def at(s: float) -> tuple[float, float]:
        i = max(0, min(n - 2, bisect.bisect_right(cum, s) - 1))
        span = cum[i + 1] - cum[i]
        k = 0.0 if span <= 0 else min(1.0, max(0.0, (s - cum[i]) / span))
        return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k)

    def heading(a: float, b: float) -> Optional[float]:
        if b - a < 30:
            return None
        (ax, ay), (bx, by) = at(a), at(b)
        return math.atan2(by - ay, bx - ax)

    windows: list[list[float]] = []
    for a, b in kinks:
        sa, sb = cum[a], cum[b]
        h_in = heading(max(0.0, sa - 100), sa - 15)
        h_out = heading(sb + 15, min(total, sb + 100))
        if h_in is not None and h_out is not None and abs((math.degrees(h_out - h_in) + 180) % 360 - 180) <= CROSSOVER_PARALLEL:
            (ix, iy), (ox, oy) = at(sa - 15), at(min(total, sb + 60))
            shift = abs(math.cos(h_in) * (oy - iy) - math.sin(h_in) * (ox - ix))
            half = min(CROSSOVER_MAX, max(CROSSOVER_MIN, 6 * shift + 20))
            start, end = max(0.0, sa - half), min(total, sb + half)
        else:
            start, end = cum[a - 1], cum[min(n - 1, b + 1)]
        if windows and start <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], end)
        else:
            windows.append([start, end])
    lat0 = coords[0][1]
    lonlat = lambda p: [p[0] / _kx(lat0), p[1] / KY]  # noqa: E731
    out: list = []
    i = 0
    for start, end in windows:
        while i < n and cum[i] < start:
            out.append(coords[i])
            i += 1
        out += [lonlat(at(start)), lonlat(at(end))]
        while i < n and cum[i] <= end:
            i += 1
    return out + coords[i:]


def cumulative(coords: list) -> list[float]:
    if not coords:
        return []
    pts = _local(coords, coords[0][1])
    out = [0.0]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        out.append(out[-1] + math.hypot(bx - ax, by - ay))
    return out


def distance(a: list, b: list) -> float:
    kx = _kx(a[1])
    return math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * KY)


def project_stops(coords: list, stops: list[dict]) -> list[tuple[float, float]]:
    """(distance along the shape, distance from the shape) of each stop, in order, never decreasing.

    Each stop is projected onto the shape from the previous stop onwards. The search stops
    once a close match (< 60 m) is found and the shape has clearly moved away, so a line
    that passes the same street twice does not jump ahead to the second pass."""
    if len(coords) < 2:
        return [(0.0, math.inf) for _ in stops]
    lat0 = coords[0][1]
    pts = _local(coords, lat0)
    cum = cumulative(coords)
    kx = _kx(lat0)
    out, start, floor = [], 0, 0.0
    for stop in stops:
        px, py = stop['lon'] * kx, stop['lat'] * KY
        best = (math.inf, start, floor)
        for i in range(start, len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            d = math.hypot(ax + t * dx - px, ay + t * dy - py)
            along = cum[i] + t * math.sqrt(length2)
            if d < best[0] and along >= floor:
                best = (d, i, along)
            elif best[0] < 60 and cum[i] - best[2] > 400:
                break
        offset, start, floor = best
        out.append((floor, offset))
    return out


def stop_distances(coords: list, stops: list[dict]) -> list[float]:
    """Distance along the shape of each stop (see `project_stops`)."""
    if len(coords) < 2:
        return [0.0 for _ in stops]
    return [round(along, 1) for along, _ in project_stops(coords, stops)]


def point_at(coords: list, cum: list[float], d: float) -> list:
    """[lon, lat] at distance `d` along the shape."""
    if len(coords) == 1 or d <= 0:
        return coords[0]
    if d >= cum[-1]:
        return coords[-1]
    lo, hi = 0, len(cum) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if cum[mid] <= d:
            lo = mid
        else:
            hi = mid
    span = cum[hi] - cum[lo]
    t = (d - cum[lo]) / span if span else 0.0
    return [coords[lo][0] + (coords[hi][0] - coords[lo][0]) * t, coords[lo][1] + (coords[hi][1] - coords[lo][1]) * t]


def bearing_at(coords: list, cum: list[float], d: float) -> float:
    """Travel direction in degrees clockwise from north, over a short look-ahead."""
    ahead = min(cum[-1], d + 40)
    a, b = point_at(coords, cum, max(0.0, ahead - 80)), point_at(coords, cum, ahead)
    return (math.degrees(math.atan2((b[0] - a[0]) * _kx(a[1]), (b[1] - a[1]) * KY)) + 360) % 360


def slice_between(coords: list, cum: list[float], a: float, b: float) -> list:
    """The part of the shape from distance `a` to `b`, with interpolated end points."""
    if b <= a:
        return [point_at(coords, cum, a)]
    inner = [c for c, d in zip(coords, cum) if a < d < b]
    return [point_at(coords, cum, a), *inner, point_at(coords, cum, b)]


def densify(coords: list, step: float = DENSE_STEP) -> list:
    """The same line with points added so that no segment is longer than `step` metres."""
    if len(coords) < 2:
        return coords
    out = [coords[0]]
    for a, b in zip(coords, coords[1:]):
        n = math.ceil(distance(a, b) / step)  # pieces
        out.extend([round(a[0] + (b[0] - a[0]) * k / n, 6), round(a[1] + (b[1] - a[1]) * k / n, 6)] for k in range(1, n))
        out.append(b)
    return out

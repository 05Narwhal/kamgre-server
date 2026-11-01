"""The railway lines in service, for the map: every stretch of track drawn once.

A line counts when the timetable has a train on it on any day of the coming week: the Velenje and Ajdovščina lines have
no train on a Sunday or a holiday, and the Koroška line none on a Saturday, and they are lines all the same. A closure
does not take a line off the map either, while the feed still lists its trains: that is a disruption, not a line gone.
Only what lies in Slovenia is drawn (abroad.py).

All operators share one network for now, so a track two operators use is one line, all drawn in the railway's blue.
Neighbouring countries' services (an S-Bahn, a Maribor - Graz train) will want a line of their own beside it: give each
such service its own `index` in `_load`, and the map a `line-offset` per service.
"""
import math
from datetime import timedelta

from . import abroad, geometry, mapping, scheduled
from .upstream import Cached, otp

DAYS = 8          # today and the same weekday next week, so a week's every weekday is seen even across a holiday
TOLERANCE = 35.0  # m: closer than this to a line already kept is that line (double track, station tracks)
WANDER = 120.0    # m: a stretch that never gets further than this from the kept lines is the same line, wandering
THINNED_SPACING = 500.0  # m between a pattern's points: a long international train's shape, thinned (geometry.MAX_POINTS)
THINNED_WANDER = 1500.0  # m: such a shape cuts corners by this much, so it only adds what no other train runs
STEP = 25.0       # m between the points compared
MIN_LENGTH = 1000.0  # m: a shorter stretch with a loose end is a shape's approach to its platform, not a line
_KX = 111_320 * math.cos(math.radians(46.1))
ABROAD_STOPS = 'IJPP:INTL-'  # the international trains' stops abroad, which carry no country in their names


def _cell(x: float, y: float) -> tuple[int, int]:
    return int(x // TOLERANCE), int(y // TOLERANCE)


def _near(index: dict, x: float, y: float, radius: float = TOLERANCE) -> bool:
    cx, cy = _cell(x, y)
    span = math.ceil(radius / TOLERANCE)
    for i in range(cx - span, cx + span + 1):
        for j in range(cy - span, cy + span + 1):
            for px, py, _ in index.get((i, j), ()):
                if (px - x) ** 2 + (py - y) ** 2 <= radius ** 2:
                    return True
    return False


def _nearest(index: dict, x: float, y: float) -> list:
    cx, cy = _cell(x, y)
    found = [p for i in (cx - 1, cx, cx + 1) for j in (cy - 1, cy, cy + 1) for p in index.get((i, j), ())]
    return min(found, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)[2]


def _spacing(shape: list) -> float:
    return geometry.cumulative(shape)[-1] / len(shape)


def merge(shapes: list[list], index: dict | None = None, wander: float = WANDER) -> list[list]:
    """Lines covering `shapes` once: each shape adds only what lies off the lines kept so far (`index`, which it adds
    to), joined to them where it leaves and comes back. The most detailed shapes go first, so the lines follow them."""
    index = {} if index is None else index
    out = []
    for shape in sorted(shapes, key=_spacing):
        points = geometry.densify(shape, STEP)
        local = [(p[0] * _KX, p[1] * geometry.KY) for p in points]
        off = [not _near(index, x, y) for x, y in local]
        kept = []
        i = 0
        while i < len(points):
            if not off[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(points) and off[j + 1]:
                j += 1
            joined = i > 0 and j + 1 < len(points)
            away = any(not _near(index, *local[k], wander) for k in range(i, j + 1))
            run = points[i:j + 1]
            if away and (joined or geometry.cumulative(run)[-1] >= MIN_LENGTH):
                # Where it leaves or rejoins a kept line, it starts from that line, so no gap shows at a junction.
                before = [_nearest(index, *local[i - 1])] if i > 0 else []
                after = [_nearest(index, *local[j + 1])] if j + 1 < len(points) else []
                out.append(geometry.simplify([*before, *run, *after], geometry.SHAPE_POINTS))
                kept.append((i, j))
            i = j + 1
        # Added once the shape is done, or each point would count as covered by the one before it.
        for a, b in kept:
            for k in range(a, b + 1):
                index.setdefault(_cell(*local[k]), []).append((*local[k], points[k]))
    return out


def _is_abroad(stop: dict) -> bool:
    return (stop.get('gtfsId') or '').startswith(ABROAD_STOPS) or abroad.is_abroad_stop(stop.get('name'))


def home_parts(stops: list[dict]) -> list[tuple[int, int]]:
    """The stretches of a pattern between its stops in Slovenia, as (first, last) stop indices."""
    parts: list[tuple[int, int]] = []
    start = None
    for i, stop in enumerate(stops):
        if _is_abroad(stop):
            if start is not None and i - 1 > start:
                parts.append((start, i - 1))
            start = None
        elif start is None:
            start = i
    if start is not None and len(stops) - 1 > start:
        parts.append((start, len(stops) - 1))
    return parts


def _query(day) -> str:
    dates = ' '.join(f'd{n}: tripsForDate(serviceDate: "{day + timedelta(days=n):%Y%m%d}") {{ gtfsId }}' for n in range(DAYS))
    return '{ routes(transportModes: [RAIL]) { gtfsId shortName mode agency { gtfsId } patterns { code stops { gtfsId name } %s } } }' % dates


def _kind(shape: dict, stops: list[dict]) -> str:
    """How far a pattern's shape can be trusted: 'detailed'; 'thinned' (a long international train's); or 'unshaped',
    its stops joined by straight lines (LP 4208 through the Bohinj valley has no shape in the feed)."""
    if shape['cum'][-1] / len(shape['coords']) <= THINNED_SPACING:
        return 'detailed'
    return 'unshaped' if len(shape['coords']) <= len(stops) else 'thinned'


def stretches(routes: list[dict], shapes: dict, kind: str = 'detailed') -> dict[str, list[list]]:
    """Operator -> the stretches of track in Slovenia of the patterns of this `kind` with a train in the coming week."""
    seen: dict[str, list[list]] = {}
    for route in routes:
        if mapping.is_replacement(route):
            continue
        operator = (route.get('agency') or {}).get('gtfsId') or f'{route["gtfsId"].split(":")[0]}:unknown'
        for pattern in route.get('patterns') or []:
            shape = shapes.get(pattern['code'])
            stops = pattern.get('stops') or []
            # Stops that do not match the shape's cannot be placed on it.
            if (not shape or len(shape['distances']) != len(stops) or not any(pattern.get(f'd{n}') for n in range(DAYS))
                    or _kind(shape, stops) != kind):
                continue
            for a, b in home_parts(stops):
                coords = geometry.slice_between(shape['coords'], shape['cum'], shape['distances'][a], shape['distances'][b])
                if len(coords) > 1:
                    seen.setdefault(operator, []).append(coords)
    return seen


def merge_unshaped(parts: list[list], index: dict) -> list[list]:
    """Stops joined by straight lines can cut across a mountain, so a leg is drawn only to reach a stop no line reaches."""
    out = []
    for part in parts:
        for a, b in zip(part, part[1:]):
            if not all(_near(index, c[0] * _KX, c[1] * geometry.KY, WANDER) for c in (a, b)):
                out += merge([[a, b]], index)
    return out


_built: dict = {'key': None, 'lines': []}


def _load() -> list[dict]:
    """The coming week's lines. The merge takes seconds, so it runs again only when the stretches have changed."""
    routes = otp().query(_query(scheduled.service_day()), timeout=(5, 90))['routes']
    shapes = scheduled.shapes.get().value
    steps = [('detailed', merge), ('thinned', lambda parts, index: merge(parts, index, THINNED_WANDER)), ('unshaped', merge_unshaped)]
    found = [(stretches(routes, shapes, kind), add) for kind, add in steps]
    key = [{operator: sorted(hash(repr(part)) for part in parts) for operator, parts in group.items()} for group, _ in found]
    if key != _built['key']:
        index: dict = {}  # shared: see the top of this file
        lines: list[dict] = []
        for group, add in found:
            # The operator with the most stretches first: the others add only what it does not run.
            for operator, parts in sorted(group.items(), key=lambda item: (-len(item[1]), item[0])):
                for coords in add(parts, index):
                    lines.append({'id': f'{operator}#{len(lines)}', 'operatorId': operator, 'geometry': [[round(x, 5), round(y, 5)] for x, y in coords]})
        _built.update(key=key, lines=lines)
    return _built['lines']


network = Cached(_load, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)

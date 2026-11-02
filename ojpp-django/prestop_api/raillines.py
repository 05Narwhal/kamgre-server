"""The railway lines in service, for the map: every stretch of track drawn once.

A line counts when the timetable has a train on it on any day of the coming week: the Velenje and Ajdovščina lines have
no train on a Sunday or a holiday, and the Koroška line none on a Saturday, and they are lines all the same. A closure
does not take a line off the map either, while the feed still lists its trains: that is a disruption, not a line gone.
Only what lies in Slovenia is drawn (border.py): a line going abroad runs from its last Slovenian station to the border
and stops there, and a stretch between two Slovenian stations that crosses a neighbour's land (near Rogatec and
Podčetrtek) has a gap where it does.

All operators share one network for now, so a track two operators use is one line, all drawn in the railway's blue.
Neighbouring countries' services (an S-Bahn, a Maribor - Graz train) will want a line of their own beside it: give each
such service its own `index` in `_load`, and the map a `line-offset` per service.

Lines follow the track (railtrack.py): the feed's shapes are taken as the feed gives them, not thinned as the moving
trains' are (scheduled.shapes keeps 400 points, cutting corners by hundreds of metres on a long international train),
and where a shape still leaves the track, the way along the track replaces it before the merge.
"""
import logging
import math
from datetime import timedelta

from . import abroad, border, geometry, mapping, railtrack, scheduled, sz
from .upstream import Cached, otp

log = logging.getLogger(__name__)

DAYS = 8          # today and the same weekday next week, so a week's every weekday is seen even across a holiday
TOLERANCE = 35.0  # m: closer than this to a line already kept is that line (double track, station tracks)
WANDER = 120.0    # m: a stretch that never gets further than this from the kept lines is the same line, wandering
THINNED_SPACING = 500.0  # m between a pattern's points: a long international train's shape, thinned (geometry.MAX_POINTS)
THINNED_WANDER = 1500.0  # m: such a shape cuts corners by this much, so it only adds what no other train runs
STEP = 25.0       # m between the points compared
MIN_LENGTH = 1000.0  # m: a shorter stretch with a loose end is a shape's approach to its platform, not a line
_KX = 111_320 * math.cos(math.radians(46.1))
ABROAD_STOPS = 'IJPP:INTL-'  # the international trains' stops, which carry no country in their names; a UIC code follows
HOME_UIC = '79'              # Slovenia's: Lendava is one of them
BORDER_POINT = 'drzavna meja'  # "Hodos Drzavna meja" has Slovenia's code too, but it is only the border, no station


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


def merge(shapes: list[list], index: dict | None = None, wander: float = WANDER, min_length: float = MIN_LENGTH) -> list[list]:
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
            if away and (joined or geometry.cumulative(run)[-1] >= min_length):
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
    stop_id, name = stop.get('gtfsId') or '', stop.get('name')
    if stop_id.startswith(ABROAD_STOPS):
        return not stop_id.startswith(ABROAD_STOPS + HOME_UIC) or BORDER_POINT in mapping.fold(name or '')
    return abroad.is_abroad_stop(name)


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


def ways_out(stops: list[dict]) -> list[tuple[int, int]]:
    """Where a pattern crosses the border: (its stop in Slovenia, the stop abroad next to it), coming or going."""
    return [(i, n) for i, stop in enumerate(stops) if not _is_abroad(stop)
            for n in (i - 1, i + 1) if 0 <= n < len(stops) and _is_abroad(stops[n])]


def _query(day) -> str:
    dates = ' '.join(f'd{n}: tripsForDate(serviceDate: "{day + timedelta(days=n):%Y%m%d}") {{ gtfsId }}' for n in range(DAYS))
    return '{ routes(transportModes: [RAIL]) { gtfsId shortName mode agency { gtfsId } patterns { code stops { gtfsId name } %s } } }' % dates


def _kind(shape: dict, stops: list[dict]) -> str:
    """How far a pattern's shape can be trusted: 'detailed'; 'thinned' (a long international train's); or 'unshaped',
    its stops joined by straight lines (LP 4208 through the Bohinj valley has no shape in the feed)."""
    if shape['cum'][-1] / len(shape['coords']) <= THINNED_SPACING:
        return 'detailed'
    return 'unshaped' if len(shape['coords']) <= len(stops) else 'thinned'


def _running(routes: list[dict], shapes: dict):
    """(operator, stops, shape) of each train pattern with a train in the coming week and a shape to place its stops on."""
    for route in routes:
        if mapping.is_replacement(route):
            continue
        operator = (route.get('agency') or {}).get('gtfsId') or f'{route["gtfsId"].split(":")[0]}:unknown'
        for pattern in route.get('patterns') or []:
            shape = shapes.get(pattern['code'])
            stops = pattern.get('stops') or []
            # Stops that do not match the shape's cannot be placed on it.
            if shape and len(shape['distances']) == len(stops) and any(pattern.get(f'd{n}') for n in range(DAYS)):
                yield operator, stops, shape


def stretches(routes: list[dict], shapes: dict, kind: str = 'detailed') -> dict[str, list[list]]:
    """Operator -> the stretches of track in Slovenia of the patterns of this `kind` with a train in the coming week."""
    seen: dict[str, list[list]] = {}
    for operator, stops, shape in _running(routes, shapes):
        if _kind(shape, stops) != kind:
            continue
        for a, b in home_parts(stops):
            coords = geometry.slice_between(shape['coords'], shape['cum'], shape['distances'][a], shape['distances'][b])
            if len(coords) > 1:
                seen.setdefault(operator, []).append(coords)
    return seen


def to_the_border(routes: list[dict], shapes: dict, kind: str = 'detailed') -> dict[str, list[list]]:
    """Operator -> from each pattern's last stop in Slovenia (`ways_out`) along the track, up to where it leaves. Never
    from a shape of straight lines between stops: those say nothing about where the track meets the border."""
    seen: dict[str, list[list]] = {}
    for operator, stops, shape in _running(routes, shapes):
        if _kind(shape, stops) != kind:
            continue
        for stop, neighbour in ways_out(stops):
            a, b = sorted((stop, neighbour))
            coords = geometry.slice_between(shape['coords'], shape['cum'], shape['distances'][a], shape['distances'][b])
            inside = border.until_abroad(coords if stop == a else coords[::-1])
            if len(inside) > 1:
                seen.setdefault(operator, []).append(inside)
    return seen


def merge_unshaped(parts: list[list], index: dict, follow=lambda leg: leg) -> list[list]:
    """Stops joined by straight lines can cut across a mountain, so a leg is drawn only to reach a stop no line reaches,
    and then along the track (`follow`)."""
    out = []
    for part in parts:
        for a, b in zip(part, part[1:]):
            if not all(_near(index, c[0] * _KX, c[1] * geometry.KY, WANDER) for c in (a, b)):
                out += merge([follow([a, b])], index)
    return out


def merge_to_border(parts: list[list], index: dict, ends: list, reach: float = WANDER) -> list[list]:
    """Each way out of the country once: what lies between the last kept line and the border, joined to that line. Only
    the end of a stretch counts, the rest is track a home line already draws (Maribor to the border, past Šentilj). A
    stretch ending within `reach` of a crossing already drawn (`ends`, which it adds to) is that crossing: the second
    track of a double line, or a thinned shape cutting the corner."""
    out = []
    for part in sorted(parts, key=_spacing):
        end = (part[-1][0] * _KX, part[-1][1] * geometry.KY)
        if any((end[0] - x) ** 2 + (end[1] - y) ** 2 <= reach ** 2 for x, y in ends):
            continue
        points = geometry.densify(part, STEP)
        local = [(p[0] * _KX, p[1] * geometry.KY) for p in points]
        last = next((k for k in range(len(points) - 1, -1, -1) if _near(index, *local[k])), None)
        first = 0 if last is None else last + 1
        if first >= len(points):
            continue
        joined = [] if last is None else [_nearest(index, *local[last])]
        out.append(geometry.simplify([*joined, *points[first:]], geometry.SHAPE_POINTS))
        for k in range(first, len(points)):
            index.setdefault(_cell(*local[k]), []).append((*local[k], points[k]))
        ends.append(end)
    return out


def _load_shapes() -> dict[str, dict]:
    """pattern code -> the feed's shape (Douglas-Peucker at 3 m, as trip and line shapes), its lengths and the stops'
    distances along it."""
    out = {}
    for route in otp().query(scheduled.SHAPES_Q, timeout=(5, 90))['routes']:
        for p in route.get('patterns') or []:
            stops = p.get('stops') or []
            coords = geometry.trim_spurs(mapping.decode_polyline((p.get('patternGeometry') or {}).get('points') or ''))
            if len(coords) < 2:
                coords = [[s['lon'], s['lat']] for s in stops]
            if len(coords) < 2:
                continue
            coords = geometry.simplify(coords, geometry.SHAPE_POINTS)
            out[p['code']] = {'coords': coords, 'cum': geometry.cumulative(coords), 'distances': geometry.stop_distances(coords, stops),
                              'stops': [sz.station_key(s.get('name') or '') for s in stops]}
    return out


feed_shapes = Cached(_load_shapes, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)
_legs: dict = {'shapes': None, 'index': {}}
SPARSE = 2     # points per stop: at most this many is no real shape, only its stops joined (a real one has hundreds a leg)
LEG_GAP = 4    # stops apart a leg is looked for in another train's shape


def _leg_index(shapes: dict) -> dict:
    """(station, a later station) -> (a pattern with a real shape between them, their indices there, reversed), for
    `shape_from_others`: this direction before the other, and neighbouring stops before ones a few apart (a train
    that skips a station another calls at). By the station's name: the feed has Solkan under two stop ids."""
    if _legs['shapes'] is not shapes:
        index: dict = {}
        real = [s for s in shapes.values() if s.get('stops') and all(s['stops']) and len(s['coords']) > SPARSE * len(s['stops'])]
        for turned in (False, True):
            for gap in range(1, LEG_GAP + 1):
                for shape in real:
                    names = shape['stops']
                    for k in range(len(names) - gap):
                        index.setdefault((names[k + gap], names[k]) if turned else (names[k], names[k + gap]), (shape, k, k + gap, turned))
        _legs.update(shapes=shapes, index=index)
    return _legs['index']


def shape_from_others(stops: list[dict]) -> list | None:
    """The shape of a pattern the feed gives only its stops for (some runs of LP 4208 and 4292, whose sibling runs have a
    shape), leg by leg from any train with a real shape over the same two stops, either way. Stops stay joined straight
    where no train has one; None when none has any, or the shapes are not read yet. The track file cannot do this: it has
    gaps (the Bohinj line), where a real shape lies on it yet no way along it is found."""
    snap = feed_shapes.peek()
    if not snap or len(stops) < 2:
        return None
    index = _leg_index(snap.value)
    out: list = []
    found = False
    for a, b in zip(stops, stops[1:]):
        hit = index.get((sz.station_key(a.get('name') or ''), sz.station_key(b.get('name') or '')))
        leg = [[a['lon'], a['lat']], [b['lon'], b['lat']]]
        if hit:
            shape, k, m, turned = hit
            part = geometry.slice_between(shape['coords'], shape['cum'], shape['distances'][k], shape['distances'][m])
            if len(part) >= 2:
                leg, found = part[::-1] if turned else part, True
        out += leg if not out else leg[1:]
    return out if found else None
_built: dict = {'key': None, 'lines': []}


def _load() -> list[dict]:
    """The coming week's lines. The merge takes seconds, so it runs again only when the stretches have changed."""
    routes = otp().query(_query(scheduled.service_day()), timeout=(5, 90))['routes']
    shapes = feed_shapes.get().value
    followed: dict = {}
    track: list = []  # loaded for a rebuild only, and let go after it

    def follow(coords: list) -> list:
        # Many patterns share a stretch: each is taken along the track once.
        key = repr(coords)
        if key not in followed:
            track[:] = track or [railtrack.load()]
            followed[key] = track[0].follow(coords)
        return followed[key]

    def along(add):
        return lambda parts, index: add([follow(part) for part in parts], index)

    ends: list = []  # the border crossings drawn so far
    found = [(stretches(routes, shapes), along(merge)),
             (stretches(routes, shapes, 'thinned'), along(lambda parts, index: merge(parts, index, THINNED_WANDER))),
             # Unshaped legs are taken along the track only where one is drawn.
             (stretches(routes, shapes, 'unshaped'), lambda parts, index: merge_unshaped(parts, index, follow)),
             (to_the_border(routes, shapes), along(lambda parts, index: merge_to_border(parts, index, ends))),
             (to_the_border(routes, shapes, 'thinned'), along(lambda parts, index: merge_to_border(parts, index, ends, THINNED_WANDER)))]
    key =[{operator: sorted(hash(repr(part)) for part in parts) for operator, parts in group.items()} for group, _ in found]
    if key != _built['key']:
        index: dict = {}  # shared: see the top of this file
        lines: list[dict] = []
        for group, add in found:
            # The operator with the most stretches first: the others add only what it does not run.
            for operator, parts in sorted(group.items(), key=lambda item: (-len(item[1]), item[0])):
                for coords in add(parts, index):
                    for part in border.inside_parts(coords):
                        part = geometry.simplify(part, geometry.SHAPE_POINTS)
                        lines.append({'id': f'{operator}#{len(lines)}', 'operatorId': operator, 'geometry': [[round(x, 5), round(y, 5)] for x, y in part]})
        # The track file lacks a way there (a new line OpenStreetMap does not have yet), so it is drawn as the feed has
        # it. Where the track crosses a neighbour's land (Dobovec) the file has none either, but nothing is drawn there.
        left = {repr(sorted(s)): s for s in (track[0].left if track else []) if all(border.contains(*p) for p in s)}
        if left:
            log.warning('rail lines: %d stretches off the track with no way along it, e.g. %s', len(left), list(left.values())[:3])
        _built.update(key=key, lines=lines)
    return _built['lines']


network = Cached(_load, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)

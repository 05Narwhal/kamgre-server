"""One stop where people see one stop.

Several feeds describe the same physical stop: the national IJPP feed and a city's own
feed (Kranj's MOKranj stops sit on the IJPP ones; Koper's city stop is ~60 m from the
intercity one). On the map they were separate, overlapping markers with half the departures
each. Stops become one station (the head keeps its id, gains the others as `memberIds`, its
board lists every member's departures, its marker sits at the members' centroid) when their
normalised names match (see `normalize`) and:

- they come from *different* feeds, lie within NEAR_METERS and vehicles at both travel the same
  way (`directions`, from the timetable's patterns). Where a direction is unknown, only stops
  within SAME_SPOT_METERS merge;
- their names are alike (`similar`: "Brežice OB" and "Brežice Občina", "Marles" and "Limbuš
  Marles"), they lie within MERGE_METERS and every way vehicles travel at one is a way they travel
  at the other (`alike`), from any feed: the poles of one stop for one direction;
- one of them is a railway station and they lie within MERGE_METERS: the station and the bus
  stops named after it are one place, whichever way you leave it;
- they come from different feeds and are one pole (`same_pole`, SAME_POLE_METERS): not served opposite
  ways, or one of them is served both ways and also the other's way;
- they come from the same feed and are exact duplicates (DUPLICATE_METERS);
- the override table says so (`merge_into`, see stopfix.py), which also may pin the marker (the
  three bays of Kozina's bus station, Tržič's).

Opposite sides of a road are different stops for the direction you travel: two groups never join
when any pair across them goes different ways (unless alike or one pole), or lies more than MERGE_METERS
apart, and a stop served both ways (a terminus, a loop) joins nothing beyond NEAR_METERS. A group holds
two stops of one feed only when every direction in it is known, so the two sides can't chain into
one through a stop whose direction is unknown. The merged stop takes the fullest of its members'
names; each member keeps its own (line views and board rows show which one it is). Its marker is at a
city feed's pole (never between poles further apart than SAME_SPOT_METERS), and `place_sides` puts the
two sides of a stop on their own sides of the road.
"""
import math
import re
from typing import Iterable, Optional

from .mapping import fold

MERGE_METERS = 150
NEAR_METERS = 75
SAME_SPOT_METERS = 25
# Two feeds' poles this close are one pole, whatever their lines do next: each feed's direction comes from its own
# previous and next stop, so the city line turning off makes Zgornje Bitnje K (MOKranj:103 / IJPP:1121360, 0.3 m)
# look 80° apart. Only opposite ways keep them apart, unless one of them is served both ways (IJPP's single
# Slovenija avto pole 3.6 m from LPP's northbound one).
SAME_POLE_METERS = 8
DUPLICATE_METERS = 3
# Directions of travel at most ~60° apart (cosine) count as the same way.
SAME_WAY = 0.5
# A way through a stop that runs against its main way on under a fifth as many patterns is a feed slip
# (a few IJPP patterns use the other side's pole: "Ljubljana Kino Šiška" 91 runs one way, 11 the other).
SLIP_SHARE = 0.2
# Words that name the kind of stop rather than the place: "Koper AP" is "Koper".
STOP_WORDS = re.compile(r'\b(avtobusna postaja|avtobusno postajalisce|zelezniska postaja|avt\.? ?post\.?|zel\.? ?post\.?|zel\.? ?p\.|ap|zp)(?=\W|$)')
# A town's bus station by its name: "Kranj AP", "Avtobusna postaja Celje" (search_stations' town results).
BUS_STATION_WORDS = re.compile(r'\b(avtobusna postaja|avt\.? ?post\.?|ap)(?=\W|$)')
# A direction added to the name: "Bled / smer Lesce", "Bled (smer Lesce)".
DIRECTION_SUFFIX = re.compile(r'\s*[/(,-]?\s*\bsmer\b.*$')
TOWN_SUFFIX = re.compile(r'(?<=\w)/[^\s/]+')
_CELL = (MERGE_METERS / 110_574, MERGE_METERS / 77_000)  # degrees; 77 km per degree of longitude is Slovenia's minimum


def name_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', fold(name or ''))


def normalize(name: str) -> str:
    """Name key without case, diacritics, punctuation and stop-kind words ("AP", "žel. post.")."""
    return re.sub(r'[^a-z0-9]', '', STOP_WORDS.sub(' ', fold(name or ''))) or name_key(name)


def words(name: str) -> list[str]:
    """The place words of a stop name: folded, without stop-kind words, a direction suffix, the town after a slash
    ("Ajdovščina/Lj." is Ajdovščina in Ljubljana) and punctuation."""
    return re.findall(r'[a-z0-9]+', STOP_WORDS.sub(' ', TOWN_SUFFIX.sub(' ', DIRECTION_SUFFIX.sub('', fold(name or '')))))


def _word_alike(a: str, b: str) -> bool:
    """The same word, or one abbreviates the other ("gim." for "gimnazija"); numbers only as themselves."""
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short) >= 2 and long.startswith(short) and not short.isdigit() and not long.isdigit()


def similar(a: str, b: str) -> bool:
    """Names of one stop as different feeds or years write it: equal once normalised, abbreviated word by word
    ("Brežice OB", "Brežice Občina"), or the shorter leaves out the town in front ("Bavarski dvor",
    "Ljubljana Bavarski dvor"). A town alone is not alike its stops ("Kranj AP", "Kranj ZD")."""
    if normalize(a) == normalize(b):
        return True
    short, long = sorted((words(a), words(b)), key=len)
    if not short or sum(map(len, short)) < 4:
        return False
    return all(_word_alike(x, y) for x, y in zip(short, long[len(long) - len(short):]))


def meters(a: dict, b: dict) -> float:
    kx = 111_320 * math.cos(math.radians(a['latitude']))
    return math.hypot((a['longitude'] - b['longitude']) * kx, (a['latitude'] - b['latitude']) * 110_574)


def directions(sequences: Iterable[list[str]], positions: dict[str, tuple[float, float]]) -> dict[str, list[tuple[float, float]]]:
    """Stop id -> unit vectors of the ways vehicles travel through it: from the previous stop to the
    next in each pattern's run of stops, without slips (SLIP_SHARE). `positions`: stop id -> (lat, lon)."""
    out: dict[str, dict] = {}
    for run in sequences:
        for i, sid in enumerate(run):
            a, b = positions.get(run[max(0, i - 1)]), positions.get(run[min(len(run) - 1, i + 1)])
            if not a or not b or a == b:
                continue
            dx, dy = (b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0]
            n = math.hypot(dx, dy)
            if n:
                way = out.setdefault(sid, {})
                key = (round(dx / n, 2), round(dy / n, 2))
                way[key] = way.get(key, 0) + 1
    return {k: _without_slips(v) for k, v in out.items()}


def _without_slips(counts: dict[tuple[float, float], int]) -> list[tuple[float, float]]:
    def runs(v):  # patterns going v's way through the stop
        return sum(c for w, c in counts.items() if v[0] * w[0] + v[1] * w[1] >= SAME_WAY)
    total = {v: runs(v) for v in counts}
    # The main way (the most patterns) first: main_way compares stops by it.
    kept = [v for v in counts if not any(v[0] * u[0] + v[1] * u[1] <= -SAME_WAY and total[v] < SLIP_SHARE * total[u] for u in counts)]
    return sorted(kept, key=lambda v: (-counts[v], v))


def main_way(a: Optional[list], b: Optional[list]) -> Optional[bool]:
    """Whether most vehicles at two stops travel the same way (None when either is unknown): a branch or turning
    variant at one pole does not split it from its namesake, while poles on two sides of a road stay apart."""
    if not a or not b:
        return None
    return a[0][0] * b[0][0] + a[0][1] * b[0][1] >= SAME_WAY


def same_way(a: Optional[list], b: Optional[list]) -> Optional[bool]:
    """Whether vehicles leave two stops in the same direction (None when either is unknown)."""
    if not a or not b:
        return None
    return max(x1 * x2 + y1 * y2 for x1, y1 in a for x2, y2 in b) >= SAME_WAY


def alike(a: Optional[list], b: Optional[list]) -> bool:
    """Every way vehicles travel at one stop is a way they travel at the other (both known): a terminus served both
    ways is not alike a stop on one side of the road."""
    if not a or not b:
        return False
    return all(any(x1 * x2 + y1 * y2 >= SAME_WAY for x2, y2 in b) for x1, y1 in a) and \
        all(any(x1 * x2 + y1 * y2 >= SAME_WAY for x1, y1 in a) for x2, y2 in b)


def two_way(a: Optional[list]) -> bool:
    """Vehicles go through the stop in opposite directions (a terminus, a loop, a pole a feed uses for both sides)."""
    return bool(a) and any(x1 * x2 + y1 * y2 <= -SAME_WAY for x1, y1 in a for x2, y2 in a)


def opposite(a: Optional[list], b: Optional[list]) -> bool:
    """Most vehicles at the two stops travel opposite ways (both known)."""
    return bool(a and b) and a[0][0] * b[0][0] + a[0][1] * b[0][1] <= -SAME_WAY


def serves(a: Optional[list], b: Optional[list]) -> bool:
    """A stop served both ways that is also served the other's main way."""
    return bool(a and b) and two_way(a) and any(x * b[0][0] + y * b[0][1] >= SAME_WAY for x, y in a)


def same_pole(a: dict, b: dict, ways: dict, d: float) -> bool:
    """Two feeds' stops that are one pole (SAME_POLE_METERS)."""
    if _feed(a) == _feed(b) or d > SAME_POLE_METERS:
        return False
    wa, wb = ways.get(a['id']), ways.get(b['id'])
    return not opposite(wa, wb) or serves(wa, wb) or serves(wb, wa)


SIDE_METERS = 2  # a stop for one way less than this to the right of its opposite namesake is on the wrong side


def group_ways(members: list[dict], ways: dict) -> Optional[list]:
    """The ways vehicles travel through a merged stop, main way first: those of its first member (in marker order:
    city feeds' poles, then the rest) whose ways are known."""
    placed = [s for s in members if _feed(s) != 'IJPP'] + [s for s in members if _feed(s) == 'IJPP']
    return next((ways[s['id']] for s in placed if ways.get(s['id'])), None)


def group_way(members: list[dict], ways: dict) -> Optional[tuple[float, float]]:
    """The main way vehicles travel through a merged stop (group_ways)."""
    found = group_ways(members, ways)
    return found[0] if found else None


def right_of(a: dict, b: dict, way: tuple[float, float]) -> float:
    """How many metres stop `a` lies to the right of stop `b`, across the road, for vehicles travelling `way`
    (a unit vector, x east, y north). Slovenia drives on the right: a stop for `way` lies to the right of the
    one for the opposite way, so this is positive when the two are on their own sides."""
    kx = 111_320 * math.cos(math.radians(a['latitude']))
    dx, dy = (a['longitude'] - b['longitude']) * kx, (a['latitude'] - b['latitude']) * 110_574
    return dx * way[1] - dy * way[0]


def _fullest(names: list[str]) -> str:
    """The most complete of a group's names: most place words, then most letters; the first on a tie."""
    return max(names, key=lambda n: (len(words(n)), len(''.join(words(n))), '/' not in n))


def _feed(stop: dict) -> str:
    return stop['id'].split(':', 1)[0]


def _head_rank(stop: dict):
    # Rail first (stations keep their own map layer), then the national feed, then the busiest.
    return ('rail' not in stop['modes'], _feed(stop) != 'IJPP', -len(stop.get('operatorIds') or []), stop['id'])


def _cell(stop: dict) -> tuple[int, int]:
    return int(stop['latitude'] / _CELL[0]), int(stop['longitude'] / _CELL[1])


def merge(stops: list[dict], forced: Optional[dict[str, str]] = None,
          pinned: Optional[dict[str, tuple[float, float]]] = None,
          ways: Optional[dict[str, list]] = None) -> tuple[list[dict], dict[str, list[str]]]:
    """Merged stop list (input order kept, members dropped) and member id -> group ids (head first).

    `forced`: stop id -> stop id to join regardless of name and distance. `pinned`: stop id -> the
    marker position of whatever station that stop ends up in. `ways`: stop id -> its directions of
    travel (see `directions`)."""
    forced, pinned, ways = forced or {}, pinned or {}, ways or {}
    parent = list(range(len(stops)))
    groups: dict[int, list[int]] = {i: [i] for i in range(len(stops))}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        a, b = root(i), root(j)
        if a != b:
            parent[a] = b
            groups[b] += groups.pop(a)

    def may_join(i, j) -> bool:
        """No pair across the two groups travels different ways (unless alike, or one pole of two feeds: same_pole) or
        lies beyond MERGE_METERS; groups sharing a feed only when every pair across them is known to travel the same way."""
        a, b = groups[root(i)], groups[root(j)]
        if a is b:
            return False
        shared = bool({_feed(stops[k]) for k in a} & {_feed(stops[k]) for k in b})
        for x in a:
            for y in b:
                wx, wy = ways.get(stops[x]['id']), ways.get(stops[y]['id'])
                way, d = main_way(wx, wy), meters(stops[x], stops[y])
                if d > MERGE_METERS or (shared and way is None):
                    return False
                if way is False and not (alike(wx, wy) and not opposite(wx, wy)) and not same_pole(stops[x], stops[y], ways, d):
                    return False
        return True

    keys = [normalize(s['name']) for s in stops]
    stations = ['rail' in s['modes'] for s in stops]
    cells: dict[tuple[int, int], list[int]] = {}
    for i, s in enumerate(stops):
        cells.setdefault(_cell(s), []).append(i)
    pairs = []
    for i, a in enumerate(stops):
        cy, cx = _cell(a)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for j in cells.get((cy + dy, cx + dx), ()):
                    if j > i and (d := meters(a, stops[j])) <= MERGE_METERS and (keys[i] == keys[j] or similar(a['name'], stops[j]['name'])):
                        pairs.append((d, i, j))
    # Closest pairs first: a stop joins its nearest fitting namesake before a farther one can.
    for d, i, j in sorted(pairs):
        a, b = stops[i], stops[j]
        namesakes = keys[i] == keys[j]
        if stations[i] or stations[j]:
            if namesakes:
                join(i, j)
        elif _feed(a) == _feed(b) and namesakes and d <= DUPLICATE_METERS:
            join(i, j)
        elif may_join(i, j):
            wa, wb = ways.get(a['id']), ways.get(b['id'])
            way = main_way(wa, wb)
            if d > NEAR_METERS and (two_way(wa) or two_way(wb)):
                continue  # a terminus or loop further off is a place of its own (Litostrojska's LPP turning loop, 106 m)
            if (alike(wa, wb) and not opposite(wa, wb)) or same_pole(a, b, ways, d) or (way and _feed(a) != _feed(b) and (d <= NEAR_METERS or namesakes)):
                join(i, j)
            # Alike names from two feeds ("Slovenija avto", "Ljubljana Slovenija avto") on the same side of the road.
            elif _feed(a) != _feed(b) and ((way and d <= NEAR_METERS) or (way is None and d <= SAME_SPOT_METERS)):
                join(i, j)
    at = {s['id']: i for i, s in enumerate(stops)}
    for member, target in forced.items():
        if member in at and target in at:
            join(at[member], at[target])

    heads: dict[int, dict] = {}
    index: dict[str, list[str]] = {}
    for group in groups.values():
        if len(group) == 1:
            sid = stops[group[0]]['id']
            if sid in pinned:
                heads[group[0]] = {**stops[group[0]], 'latitude': pinned[sid][0], 'longitude': pinned[sid][1]}
            continue
        order = sorted(group, key=lambda i: _head_rank(stops[i]))
        ordered = [stops[i] for i in order]
        head = ordered[0]
        ids = [s['id'] for s in ordered]
        pin = next((pinned[i] for i in ids if i in pinned), None)
        # IJPP often puts a pole on the other side of the road (Gosposvetska, Litostrojska): a city feed's pole places it.
        placed = [s for s in ordered if _feed(s) != 'IJPP' and 'rail' not in s['modes']] or ordered
        # Poles at one spot: between them; poles further apart: at the first (busiest) one, never in the space between.
        if any(meters(x, y) > SAME_SPOT_METERS for x in placed for y in placed):
            placed = placed[:1]
        lat, lon = pin or (sum(s['latitude'] for s in placed) / len(placed), sum(s['longitude'] for s in placed) / len(placed))
        merged = {**head, 'name': head['name'] if stations[order[0]] else _fullest([s['name'] for s in ordered]),
                  'latitude': round(lat, 6), 'longitude': round(lon, 6),
                  'modes': sorted({m for s in ordered for m in s['modes']}),
                  'operatorIds': sorted({o for s in ordered for o in (s.get('operatorIds') or [])}),
                  'memberIds': ids}
        heads[order[0]] = merged
        for sid in ids:
            index[sid] = ids
    out = []
    for i, s in enumerate(stops):
        if i in heads:
            out.append(heads[i])
        elif s['id'] not in index:
            out.append(s)
    return out, index


# ---------------------------------------------------------------- the two sides of a road (spec 2026-10-19 A3)

SIDE_PAIR_METERS = 60   # a stop's two sides (opposite ways, alike names) lie at most this far apart
HALF_ROAD = (4, 12)     # m from the middle of the road to a pole: at least (both drawn on one spot), at most
OSM_METERS = 25         # an OSM bus stop (highway=bus_stop) this close to a side's place is where the pole is


def place_sides(markers: list[dict], stops: list[dict], ways: dict, fixed: set[str] = frozenset(),
                osm: Iterable[tuple[float, float]] = ()) -> int:
    """Puts the two sides of a stop on their own sides of the road (`markers` gets moved copies); returns how many moved.

    Slovenia drives on the right, so the stop for vehicles travelling one way is to the right of the one for the
    opposite way. Where the feeds put both on one spot, or swap them (IJPP often does), each moves across to its
    side, keeping its place along the road: to the OSM bus stop on that side when one is close, else HALF_ROAD
    from the middle (between the two, or as far apart as the feeds had them). Markers with a hand-placed member
    (`fixed` stop ids: stop_overrides.csv) and railway stations stay. `osm`: (lat, lon) of OSM bus stops."""
    by_id = {s['id']: s for s in stops}
    bus = [m for m in markers if 'rail' not in m['modes'] and not fixed & set(m.get('memberIds') or [m['id']])]
    way_of = {m['id']: group_way([by_id[i] for i in m.get('memberIds') or [m['id']] if i in by_id], ways) for m in bus}
    cells: dict[tuple[int, int], list[dict]] = {}
    for m in bus:
        cells.setdefault(_cell(m), []).append(m)
    poles: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for lat, lon in osm:
        poles.setdefault(_cell({'latitude': lat, 'longitude': lon}), []).append((lat, lon))
    pairs = []
    for a in bus:
        wa = way_of[a['id']]
        cy, cx = _cell(a)
        for b in (b for dy in (-1, 0, 1) for dx in (-1, 0, 1) for b in cells.get((cy + dy, cx + dx), ())):
            wb = way_of[b['id']]
            if b['id'] <= a['id'] or not (wa and wb) or wa[0] * wb[0] + wa[1] * wb[1] > -SAME_WAY:
                continue
            if (d := meters(a, b)) <= SIDE_PAIR_METERS and similar(a['name'], b['name']) and right_of(a, b, wa) < SIDE_METERS:
                pairs.append((d, a, b))
    moved: dict[str, tuple[float, float]] = {}
    for _, a, b in sorted(pairs, key=lambda p: p[0]):
        if a['id'] in moved or b['id'] in moved:
            continue
        u = way_of[a['id']]
        lat0, lon0 = (a['latitude'] + b['latitude']) / 2, (a['longitude'] + b['longitude']) / 2
        kx, ky = 111_320 * math.cos(math.radians(lat0)), 110_574
        local = lambda s: ((s['longitude'] - lon0) * kx, (s['latitude'] - lat0) * ky)  # noqa: E731
        right = (u[1], -u[0])
        half = min(max(abs(right_of(a, b, u)) / 2, HALF_ROAD[0]), HALF_ROAD[1])
        my, mx = _cell({'latitude': lat0, 'longitude': lon0})
        near = [p for dy in (-1, 0, 1) for dx in (-1, 0, 1) for p in poles.get((my + dy, mx + dx), ())]
        for stop, sign in ((a, 1), (b, -1)):
            x, y = local(stop)
            along = x * u[0] + y * u[1]
            tx, ty = along * u[0] + sign * half * right[0], along * u[1] + sign * half * right[1]
            # The OSM pole on this side nearest to where the stop goes.
            side = [(math.hypot(px - tx, py - ty), p) for p in near
                    for px, py in [((p[1] - lon0) * kx, (p[0] - lat0) * ky)] if sign * (px * right[0] + py * right[1]) >= 1]
            hit = min(side, default=None)
            moved[stop['id']] = hit[1] if hit and hit[0] <= OSM_METERS else (lat0 + ty / ky, lon0 + tx / kx)
    for i, m in enumerate(markers):
        if m['id'] in moved:
            lat, lon = moved[m['id']]
            markers[i] = {**m, 'latitude': round(lat, 6), 'longitude': round(lon, 6)}
    return len(moved)


def report(stops: list[dict], merged: list[dict]) -> list[dict]:
    """One row per member of every merged station: how far it is from the station marker."""
    by_id = {s['id']: s for s in stops}
    rows = []
    for station in merged:
        for sid in station.get('memberIds') or []:
            s = by_id[sid]
            rows.append({'kind': 'merge', 'stop_id': sid, 'name': s['name'], 'into': station['id'],
                         'meters': round(meters(s, station), 1), 'lat': station['latitude'], 'lon': station['longitude']})
    return rows

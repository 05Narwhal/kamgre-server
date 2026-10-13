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
- they come from the same feed and are exact duplicates (DUPLICATE_METERS);
- the override table says so (`merge_into`, see stopfix.py), which also may pin the marker (the
  three bays of Kozina's bus station).

Opposite sides of a road are different stops for the direction you travel: two groups never join
when any pair across them goes opposite ways, or lies more than MERGE_METERS apart. A group holds
two stops of one feed only when every direction in it is known, so the two sides can't chain into
one through a stop whose direction is unknown. The merged stop takes the fullest of its members'
names; each member keeps its own (line views and board rows show which one it is).
"""
import math
import re
from typing import Iterable, Optional

from .mapping import fold

MERGE_METERS = 150
NEAR_METERS = 75
SAME_SPOT_METERS = 25
DUPLICATE_METERS = 3
# Directions of travel at most ~60° apart (cosine) count as the same way.
SAME_WAY = 0.5
# Words that name the kind of stop rather than the place: "Koper AP" is "Koper".
STOP_WORDS = re.compile(r'\b(avtobusna postaja|avtobusno postajalisce|zelezniska postaja|avt\.? ?post\.?|zel\.? ?post\.?|zel\.? ?p\.|ap|zp)(?=\W|$)')
# A direction added to the name: "Bled / smer Lesce", "Bled (smer Lesce)".
DIRECTION_SUFFIX = re.compile(r'\s*[/(,-]?\s*\bsmer\b.*$')
_CELL = (MERGE_METERS / 110_574, MERGE_METERS / 77_000)  # degrees; 77 km per degree of longitude is Slovenia's minimum


def name_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', fold(name or ''))


def normalize(name: str) -> str:
    """Name key without case, diacritics, punctuation and stop-kind words ("AP", "žel. post.")."""
    return re.sub(r'[^a-z0-9]', '', STOP_WORDS.sub(' ', fold(name or ''))) or name_key(name)


def words(name: str) -> list[str]:
    """The place words of a stop name: folded, without stop-kind words, a direction suffix and punctuation."""
    return re.findall(r'[a-z0-9]+', STOP_WORDS.sub(' ', DIRECTION_SUFFIX.sub('', fold(name or ''))))


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
    next in each pattern's run of stops. `positions`: stop id -> (lat, lon)."""
    out: dict[str, set] = {}
    for run in sequences:
        for i, sid in enumerate(run):
            a, b = positions.get(run[max(0, i - 1)]), positions.get(run[min(len(run) - 1, i + 1)])
            if not a or not b or a == b:
                continue
            dx, dy = (b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0]
            n = math.hypot(dx, dy)
            if n:
                out.setdefault(sid, set()).add((round(dx / n, 2), round(dy / n, 2)))
    return {k: sorted(v) for k, v in out.items()}


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


def _fullest(names: list[str]) -> str:
    """The most complete of a group's names: most place words, then most letters; the first on a tie."""
    return max(names, key=lambda n: (len(words(n)), len(''.join(words(n)))))


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
        """No pair across the two groups travels opposite ways or lies beyond MERGE_METERS; groups sharing a feed only
        when every pair across them is known to travel the same way."""
        a, b = groups[root(i)], groups[root(j)]
        if a is b:
            return False
        shared = bool({_feed(stops[k]) for k in a} & {_feed(stops[k]) for k in b})
        for x in a:
            for y in b:
                way = same_way(ways.get(stops[x]['id']), ways.get(stops[y]['id']))
                if way is False or (shared and way is None) or meters(stops[x], stops[y]) > MERGE_METERS:
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
            way = same_way(ways.get(a['id']), ways.get(b['id']))
            if alike(ways.get(a['id']), ways.get(b['id'])):
                join(i, j)
            elif _feed(a) != _feed(b) and namesakes and ((way and d <= NEAR_METERS) or (way is None and d <= SAME_SPOT_METERS)):
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
        lat, lon = pin or (sum(s['latitude'] for s in ordered) / len(ordered), sum(s['longitude'] for s in ordered) / len(ordered))
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

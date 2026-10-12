"""One stop where people see one stop.

Several feeds describe the same physical stop: the national IJPP feed and a city's own
feed (Kranj's MOKranj stops sit on the IJPP ones; Koper's city stop is ~60 m from the
intercity one). On the map they were separate, overlapping markers with half the departures
each. Stops become one station (the head keeps its id, gains the others as `memberIds`, its
board lists every member's departures, its marker sits at the members' centroid) when their
normalised names match (see `normalize`) and:

- they come from *different* feeds and lie within MERGE_METERS: each stop joins its nearest
  namesake in every other feed, so the two sides of a road (each with its own city-feed twin)
  don't chain into one stop;
- they come from the same feed and are exact duplicates (DUPLICATE_METERS), or STATION_BAYS or
  more namesakes lie within MERGE_METERS of one another — the bays of a bus station (Kozina has
  three). A same-feed *pair* stays apart: opposite sides of a road are different stops for the
  direction you travel;
- the override table says so (`merge_into`, see stopfix.py), which also may pin the marker.
"""
import math
import re
from typing import Optional

from .mapping import fold

MERGE_METERS = 150
DUPLICATE_METERS = 3
STATION_BAYS = 3
# Words that name the kind of stop rather than the place: "Koper AP" is "Koper".
STOP_WORDS = re.compile(r'\b(avtobusna postaja|avtobusno postajalisce|zelezniska postaja|avt\.? ?post\.?|zel\.? ?post\.?|zel\.? ?p\.|ap|zp)(?=\W|$)')
_CELL = (MERGE_METERS / 110_574, MERGE_METERS / 77_000)  # degrees; 77 km per degree of longitude is Slovenia's minimum


def name_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', fold(name or ''))


def normalize(name: str) -> str:
    """Name key without case, diacritics, punctuation and stop-kind words ("AP", "žel. post.")."""
    return re.sub(r'[^a-z0-9]', '', STOP_WORDS.sub(' ', fold(name or ''))) or name_key(name)


def meters(a: dict, b: dict) -> float:
    kx = 111_320 * math.cos(math.radians(a['latitude']))
    return math.hypot((a['longitude'] - b['longitude']) * kx, (a['latitude'] - b['latitude']) * 110_574)


def _feed(stop: dict) -> str:
    return stop['id'].split(':', 1)[0]


def _head_rank(stop: dict):
    # Rail first (stations keep their own map layer), then the national feed, then the busiest.
    return ('rail' not in stop['modes'], _feed(stop) != 'IJPP', -len(stop.get('operatorIds') or []), stop['id'])


def _cell(stop: dict) -> tuple[int, int]:
    return int(stop['latitude'] / _CELL[0]), int(stop['longitude'] / _CELL[1])


def merge(stops: list[dict], forced: Optional[dict[str, str]] = None,
          pinned: Optional[dict[str, tuple[float, float]]] = None) -> tuple[list[dict], dict[str, list[str]]]:
    """Merged stop list (input order kept, members dropped) and member id -> group ids (head first).

    `forced`: stop id -> stop id to join regardless of name and distance. `pinned`: stop id -> the
    marker position of whatever station that stop ends up in."""
    forced, pinned = forced or {}, pinned or {}
    parent = list(range(len(stops)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        parent[root(i)] = root(j)

    keys = [normalize(s['name']) for s in stops]
    cells: dict[tuple[int, int], list[int]] = {}
    for i, s in enumerate(stops):
        cells.setdefault(_cell(s), []).append(i)
    for i, a in enumerate(stops):
        cy, cx = _cell(a)
        nearest: dict[str, tuple[float, int]] = {}
        bays = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for j in cells.get((cy + dy, cx + dx), ()):
                    if j == i or keys[i] != keys[j]:
                        continue
                    b = stops[j]
                    d = meters(a, b)
                    if d > MERGE_METERS:
                        continue
                    if _feed(a) == _feed(b):
                        if d <= DUPLICATE_METERS:
                            join(i, j)
                        bays.append(j)
                    elif d < nearest.get(_feed(b), (MERGE_METERS + 1, -1))[0]:
                        nearest[_feed(b)] = (d, j)
        for _, j in nearest.values():
            join(i, j)
        if len(bays) + 1 >= STATION_BAYS:
            for j in bays:
                join(i, j)
    at = {s['id']: i for i, s in enumerate(stops)}
    for member, target in forced.items():
        if member in at and target in at:
            join(at[member], at[target])

    groups: dict[int, list[int]] = {}
    for i in range(len(stops)):
        groups.setdefault(root(i), []).append(i)
    heads: dict[int, dict] = {}
    index: dict[str, list[str]] = {}
    for members in groups.values():
        if len(members) == 1:
            sid = stops[members[0]]['id']
            if sid in pinned:
                heads[members[0]] = {**stops[members[0]], 'latitude': pinned[sid][0], 'longitude': pinned[sid][1]}
            continue
        order = sorted(members, key=lambda i: _head_rank(stops[i]))
        ordered = [stops[i] for i in order]
        head = ordered[0]
        ids = [s['id'] for s in ordered]
        pin = next((pinned[i] for i in ids if i in pinned), None)
        lat, lon = pin or (sum(s['latitude'] for s in ordered) / len(ordered), sum(s['longitude'] for s in ordered) / len(ordered))
        merged = {**head,
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

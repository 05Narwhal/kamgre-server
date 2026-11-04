"""Which pole each stop of a city timetable is.

A timetable names its stops ("Lipce", twice on line 1A: out and back) but gives no coordinates. Most names have
a pole per direction in the national feed, and OpenStreetMap has the town's poles by name (some tagged with the
feed's stop id). A name's candidates are the bus poles of either source whose name is alike (stopgroups.similar);
an OSM pole tagged with a feed stop, or within SAME_POLE of a feed stop of an alike name, is that stop.

Which of a name's poles a run uses follows from runs that are known: OTP's patterns and OSM's bus route relations
(their platforms in order). A run's poles are chosen so that its consecutive pairs appear in that order, at most
GAP stops apart, in as many known runs as possible (`adjacent`). A stop whose best choices tie is ambiguous and the
build fails: the side of the road alone guessed wrong at Jesenice OŠ Prežihov Voranc, whose two poles stand on two
streets.

Where no known run tells (Piran: OTP has no city runs there, OSM's few relations are short), the road decides
(`length`): the run is routed through each choice of the tied poles, the bus stopping with the pole on its right, and
the shortest choice wins when it is clearly shorter. That settles two streets by distance and one road's two sides by
the turn a wrong side would need. A pole the road still cannot place (one standing at a crossing, where it has no
side) takes the one of its name's two poles that the other direction did not (`avoid`).
"""
import itertools
import math
from typing import Callable, Iterable, Optional

from ..stopgroups import similar

SAME_POLE = 15  # m: an untagged OSM pole this close to a feed stop of an alike name is that stop
GAP = 3         # a known run may have up to GAP - 1 stops between two consecutive stops of the timetable
ROAD_MARGIN = 20  # m: the road's shortest choice must beat every other by this much
MOST_CHOICES = 64  # tied poles' combinations routed for one stretch of a run


def meters(a: dict, b: dict) -> float:
    kx = 111_320 * math.cos(math.radians(a['lat']))
    return math.hypot((a['lon'] - b['lon']) * kx, (a['lat'] - b['lat']) * 110_574)


def unify(feed_stops: list[dict], osm_stops: list[dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """Poles from feed stops ({'id': 'IJPP:…', 'name', 'lat', 'lon'}) and OSM bus poles ({'id': 'osm:…', 'name',
    'lat', 'lon', 'refs': {'IJPP': '1121067'}}): {pole id: pole with 'names'}, and {OSM id: pole id}."""
    poles = {s['id']: {**s, 'names': [s['name']]} for s in feed_stops}
    alias = {}
    for o in osm_stops:
        same = next((f'{feed}:{ref}' for feed, ref in sorted((o.get('refs') or {}).items()) if f'{feed}:{ref}' in poles), None)
        if same is None and o.get('name'):
            near = [p for p in feed_stops if meters(p, o) <= SAME_POLE and similar(p['name'], o['name'])]
            same = min(near, key=lambda p: meters(p, o))['id'] if near else None
        if same:
            alias[o['id']] = same
            if o.get('name') and o['name'] not in poles[same]['names']:
                poles[same]['names'].append(o['name'])
        elif o.get('name'):
            poles[o['id']] = {**o, 'names': [o['name']]}
            alias[o['id']] = o['id']
    return poles, alias


def adjacent(runs: Iterable[list[str]], alias: Optional[dict] = None) -> dict[tuple[str, str], float]:
    """(a, b) -> how many known runs serve pole b at most GAP stops after pole a, each counting 1 / the stops between
    (+1): the next stop counts fully. OSM's relations are not all right (some list the other side's pole), so a
    choice follows the most runs, and OTP's many patterns outweigh them on the main roads."""
    out: dict[tuple[str, str], float] = {}
    for run in runs:
        ids = [(alias or {}).get(s, s) for s in run]
        seen: dict[tuple[str, str], float] = {}
        for i, a in enumerate(ids):
            for gap, b in enumerate(ids[i + 1:i + 1 + GAP], start=1):
                if a != b:
                    seen[(a, b)] = max(seen.get((a, b), 0), 1 / gap)
        for k, w in seen.items():
            out[k] = out.get(k, 0) + w
    return out


def merged(*weights: dict) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for w in weights:
        for k, v in w.items():
            out[k] = out.get(k, 0) + v
    return out


def candidates(name: str, poles: dict[str, dict]) -> list[str]:
    return sorted(pid for pid, p in poles.items() if any(similar(name, n) for n in p['names']))


def choose(names: list[str], poles: dict[str, dict], pairs: dict[tuple[str, str], float],
           length: Optional[Callable[[list[dict]], Optional[float]]] = None,
           avoid: Optional[dict[str, set]] = None) -> tuple[list[Optional[str]], list[str]]:
    """A pole per stop of one run (the choice the most known runs agree with, `adjacent`; ties settled by the road,
    `length`: metres of road through a list of poles, None without a route; then by `avoid`: name -> the poles the
    other direction took), and the problems: no pole, or poles nothing tells apart."""
    options = [candidates(n, poles) for n in names]
    problems = [f'no pole named like "{n}" (stop {i + 1})' for i, (n, o) in enumerate(zip(names, options)) if not o]
    if problems:
        return [None] * len(names), problems
    link = lambda a, b: pairs.get((a, b), 0)  # noqa: E731
    ahead = [{c: 0.0 for c in options[0]}]
    for i in range(1, len(names)):
        ahead.append({c: max(ahead[-1][p] + link(p, c) for p in options[i - 1]) for c in options[i]})
    behind = [{c: 0.0 for c in options[-1]}]
    for i in range(len(names) - 2, -1, -1):
        behind.insert(0, {c: max(behind[0][n] + link(c, n) for n in options[i + 1]) for c in options[i]})
    best = max(ahead[-1].values())
    tops = [[c for c in options[i] if abs(ahead[i][c] + behind[i][c] - best) < 1e-9] for i in range(len(names))]
    chosen = [t[0] if len(t) == 1 else None for t in tops]
    if length and None in chosen:
        _by_road(chosen, tops, poles, length)
    for i, n in enumerate(names):
        if chosen[i] is None and avoid and len(options[i]) == 2:
            left = [c for c in tops[i] if c not in avoid.get(n, ())]
            chosen[i] = left[0] if len(left) == 1 else None
        if chosen[i] is None:
            problems.append(f'"{n}" (stop {i + 1}): no known run or road tells its pole from {", ".join(tops[i])}')
    return chosen, problems


def _by_road(chosen: list, tops: list[list[str]], poles: dict[str, dict], length: Callable) -> None:
    """Each stretch of tied stops, routed from the chosen stop before it to the one after it through every choice of
    their poles: a stop takes the pole that all choices within ROAD_MARGIN of the shortest agree on."""
    i = 0
    while i < len(chosen):
        if chosen[i] is not None:
            i += 1
            continue
        j = i
        while j < len(chosen) and chosen[j] is None:
            j += 1
        combos = list(itertools.islice(itertools.product(*tops[i:j]), MOST_CHOICES + 1))
        if len(combos) <= MOST_CHOICES:
            ends = ([chosen[i - 1]] if i else [], [chosen[j]] if j < len(chosen) else [])
            routed = [(m, c) for c in combos if (m := length([poles[p] for p in ends[0] + list(c) + ends[1]])) is not None]
            if routed:
                shortest = min(m for m, _ in routed)
                near = [c for m, c in routed if m - shortest < ROAD_MARGIN]
                for k in range(i, j):
                    picks = {c[k - i] for c in near}
                    if len(picks) == 1:
                        chosen[k] = picks.pop()
        i = j

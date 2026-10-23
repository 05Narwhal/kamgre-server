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
"""
import math
from typing import Iterable, Optional

from ..stopgroups import similar

SAME_POLE = 15  # m: an untagged OSM pole this close to a feed stop of an alike name is that stop
GAP = 3         # a known run may have up to GAP - 1 stops between two consecutive stops of the timetable


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


def choose(names: list[str], poles: dict[str, dict], pairs: dict[tuple[str, str], float]) -> tuple[list[Optional[str]], list[str]]:
    """A pole per stop of one run (the choice the most known runs agree with, `adjacent`), and the problems: no pole,
    or poles the known runs cannot tell apart."""
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
    chosen = []
    for i, n in enumerate(names):
        top = [c for c in options[i] if abs(ahead[i][c] + behind[i][c] - best) < 1e-9]
        if len(top) == 1:
            chosen.append(top[0])
        else:
            chosen.append(None)
            problems.append(f'"{n}" (stop {i + 1}): no known run tells its pole from {", ".join(top)}')
    return chosen, problems

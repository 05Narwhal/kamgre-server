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
import difflib
import itertools
import math
import re
import unicodedata
from typing import Callable, Iterable, Optional

from ..stopgroups import normalize, similar, words

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


def alike(name: str, pole_name: str, town: str = '') -> bool:
    """stopgroups.similar, but a name that is the town alone after its stop-kind words ("Ptuj AP") is not alike a
    stop that merely ends in it ("Dom upokojencev Ptuj", "Terme Ptuj", "Nova vas pri Ptuju")."""
    if not similar(name, pole_name):
        return False
    short, long = sorted((words(name), words(pole_name)), key=len)
    return not (town and len(short) == 1 and len(long) > 1 and normalize(name) != normalize(pole_name)
                and words(town)[:1] == [short[0]])


def candidates(name: str, poles: dict[str, dict], town: str = '') -> list[str]:
    return sorted(pid for pid, p in poles.items() if any(alike(name, n, town) for n in p['names']))


OCR_LIKE = 0.8     # an OCR'd name no pole is named like takes the pole name this alike (difflib ratio, letters only) ...
OCR_MARGIN = 0.05  # ... when it beats every other pole name by this much


def _letters(name: str) -> str:
    """'Pod gradom - parkirišče' -> 'podgradomparkirisce': two spellings of one place compare equal."""
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().casefold())


def misread(name: str, poles: dict[str, dict]) -> Optional[str]:
    """The pole name an OCR'd stop name stands for ('Zadruizni trg parkirisée' -> 'Zadružni trg parkirišče'), or None
    when none is clearly alike or it would change a house number ('Draženci 21d' never becomes 'Draženci 18e'; a pole
    named without one, 'Suha veja' for 'Suha veja 02', is fine)."""
    digits = lambda s: re.findall(r'\d+', s)  # noqa: E731
    scored = sorted(((difflib.SequenceMatcher(None, _letters(name), _letters(n)).ratio(), n)
                     for n in {n for p in poles.values() for n in p['names']} if not digits(n) or digits(n) == digits(name)), reverse=True)
    if not scored or scored[0][0] < OCR_LIKE or (len(scored) > 1 and scored[0][0] - scored[1][0] < OCR_MARGIN and
                                                 _letters(scored[1][1]) != _letters(scored[0][1])):
        return None
    return scored[0][1]


def choose(names: list[str], poles: dict[str, dict], pairs: dict[tuple[str, str], float],
           length: Optional[Callable[[list[dict]], Optional[float]]] = None,
           avoid: Optional[dict[str, set]] = None, town: str = "") -> tuple[list[Optional[str]], list[str]]:
    """A pole per stop of one run (the choice the most known runs agree with, `adjacent`; ties settled by the road,
    `length`: metres of road through a list of poles, None without a route; then by `avoid`: name -> the poles the
    other direction took), and the problems: no pole, or poles nothing tells apart."""
    options = [candidates(n, poles, town) for n in names]
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
        if chosen[i] is None and len(tops[i]) == 2:
            # A run up a road and back down it (Celje's line 11 to the castle) calls twice at one stop: the visit
            # nothing tells takes the pole the other visit did not.
            taken = {chosen[j] for j, m in enumerate(names) if m == n and j != i and chosen[j] in tops[i]}
            chosen[i] = next(c for c in tops[i] if c not in taken) if len(taken) == 1 else None
        if chosen[i] is None:
            problems.append(f'"{n}" (stop {i + 1}): no known run or road tells its pole from {", ".join(tops[i])}')
    return chosen, problems


def _by_road(chosen: list, tops: list[list[str]], poles: dict[str, dict], length: Callable) -> None:
    """Each stretch of tied stops, routed from the chosen stop before it to the one after it through every choice of
    their poles: a stop takes the pole that all choices within ROAD_MARGIN of the shortest agree on. A stretch with more
    than MOST_CHOICES choices (Celje's line 2b: eight stops in a row with a pole each side) goes a window at a time,
    each routed on from the stop before it, keeping only the first half's picks: the rest is settled with what follows."""
    i = 0
    while i < len(chosen):
        if chosen[i] is not None:
            i += 1
            continue
        j = i
        while j < len(chosen) and chosen[j] is None:
            j += 1
        while i < j:
            w = i + 1
            while w < j and math.prod(len(t) for t in tops[i:w + 1]) <= MOST_CHOICES:
                w += 1
            keep = j if w == j else i + max(1, (w - i) // 2)
            _route(chosen, tops, poles, length, i, w, keep)
            i = keep


def _route(chosen: list, tops: list[list[str]], poles: dict[str, dict], length: Callable, i: int, w: int, keep: int) -> None:
    """Stops i … w - 1 routed through every choice of their poles, between the chosen stops next to them; picks
    stops i … keep - 1."""
    combos = list(itertools.islice(itertools.product(*tops[i:w]), MOST_CHOICES + 1))
    if len(combos) > MOST_CHOICES:
        return
    before = [chosen[i - 1]] if i and chosen[i - 1] is not None else []
    after = [chosen[w]] if w < len(chosen) and chosen[w] is not None else []
    routed = [(m, c) for c in combos if (m := length([poles[p] for p in before + list(c) + after])) is not None]
    if routed:
        shortest = min(m for m, _ in routed)
        near = [c for m, c in routed if m - shortest < ROAD_MARGIN]
        for k in range(i, keep):
            picks = {c[k - i] for c in near}
            if len(picks) == 1:
                chosen[k] = picks.pop()

"""Route variants (contract 4): the lines between the same two places by the same operator are one group.

IJPP publishes each way a bus can take as its own route: Tržič–Ljubljana via Kovor and via Duplje, Kropa–Kranj
via Strahinj and via Podnart. Routes form a group (`groupId`) when their operator and mode match and their
longest patterns run from the same place to the same place (end stop names normalised, in that direction: Ljubljana–
Jesenice and Jesenice–Ljubljana stay apart). Within a group, `via` names the stop on a variant the fewest others pass
by its whole name ("Kovor C", "Duplje/Trž."), then, when some share it, a stop that sets it apart from them ("Kovor C,
Naklo"); ties go to the stop nearest the middle of its way, where variants part. A route alone in its group, or one
with nothing of its own, has `via: null`.
"""
import hashlib
import threading
from collections import defaultdict

from . import sources, stopgroups
from .upstream import UpstreamError

_lock = threading.Lock()
_built: dict = {'key': None, 'value': None}


def _place(name: str) -> str:
    """The place a stop is in or at, by its first word ("Kovor C" -> "Kovor", "Duplje/Trž." -> "Duplje")."""
    words = (name or '').replace(',', ' ').split()
    return words[0].split('/')[0].rstrip('.') if words else ''


def build(routes: dict, patterns: list[dict], names: dict[str, str], operator_of=lambda r: r.get('agencyId')) -> dict[str, dict]:
    """routeId -> {'groupId', 'via'} for every route. `patterns`: [{'routeId', 'stops': [stop ids]}];
    `names`: stop id -> name."""
    longest: dict[str, list[str]] = {}
    served_ids: dict[str, set[str]] = defaultdict(set)
    for p in patterns:
        rid = p.get('routeId')
        if rid not in routes or not p['stops']:
            continue
        if len(p['stops']) > len(longest.get(rid, [])):
            longest[rid] = p['stops']
        served_ids[rid].update(p['stops'])
    groups: dict[str, list[str]] = defaultdict(list)
    out = {}
    for rid, r in routes.items():
        stops = longest.get(rid)
        if stops:
            ends = [stopgroups.normalize(names.get(s, s)) for s in (stops[0], stops[-1])]
            key = f'{operator_of(r) or rid.split(":", 1)[0]}|{r.get("mode")}|{ends[0]}|{ends[1]}'
        else:
            key = f'route|{rid}'
        group = 'g:' + hashlib.sha1(key.encode()).hexdigest()[:12]
        groups[group].append(rid)
        out[rid] = {'groupId': group, 'via': None}
    for members in groups.values():
        if len(members) < 2:
            continue
        # Towns every variant passes: their stops name a way last (a village names it better than a city street).
        towns = frozenset.intersection(*(frozenset(_place(names.get(x, x)) for x in served_ids[rid]) for rid in members))
        place_of = lambda name: (name or '').strip()
        places = {rid: {place_of(names.get(x, x)) for x in served_ids[rid]} for rid in members}
        # Variants by the places they serve: a route listed once per direction is one variant.
        kinds = {frozenset(places[rid]) for rid in members}
        holders = lambda place: frozenset(k for k in kinds if place in k)
        for rid in members if len(kinds) > 1 else []:
            mine = frozenset(places[rid])
            stops = longest.get(rid) or []
            middle = {}  # place -> (inside a shared town, distance from the middle of the way)
            for i, s in enumerate(stops):
                name = names.get(s, s)
                middle.setdefault(place_of(name), (_place(name) in towns, abs(i - (len(stops) - 1) / 2) / max(1, len(stops))))
            cands = [p for p in mine if p and p in middle and holders(p) != kinds]
            if not cands:
                continue
            # The place the fewest other variants pass (Duplje, Kovor), nearest the middle; when some variants share
            # it, a place that sets this one apart from them (Naklo).
            # Places outside the towns every variant passes come first: a village names a way better than a city street.
            first = min(cands, key=lambda p: (middle[p][0], len(holders(p)), middle[p][1], p))
            way = holders(first)
            inner = [p for p in cands if way & holders(p) < way and middle[p][0] <= middle[first][0]]
            second = min(inner, key=lambda p: (middle[p][0], len(way & holders(p)), middle[p][1], p), default=None)
            out[rid]['via'] = f'{first}, {second}' if second else first
        _distinct(members, out, places, {rid: frozenset(names.get(x, x) for x in served_ids[rid]) for rid in members})
    return out


def _distinct(members: list[str], out: dict, places: dict[str, set[str]], stops: dict[str, frozenset[str]]) -> None:
    """Variants that serve different stops get different labels: while some share one, each adds what sets it apart
    from the others sharing it, a place first, else a stop of its own ("Meja" and "Meja, Bohinjska Bistrica OŠ").
    Routes serving the same stops are one variant (IJPP lists a line twice) and keep one label."""
    by_stops: dict[frozenset, list[str]] = defaultdict(list)
    for rid in members:
        by_stops[stops[rid]].append(rid)
    if len(by_stops) < 2:
        return
    label = {kind: out[rids[0]]['via'] for kind, rids in by_stops.items()}
    place_set = {kind: frozenset(places[rids[0]]) for kind, rids in by_stops.items()}
    for _ in range(4):
        shared: dict = defaultdict(list)
        for kind, text in label.items():
            shared[text].append(kind)
        clashes = [kinds for kinds in shared.values() if len(kinds) > 1]
        if not clashes:
            break
        for kinds in clashes:
            for kind in kinds:
                others = [k for k in kinds if k != kind]
                text = label[kind]
                used = set((text or '').split(', '))
                own_places = [p for p in place_set[kind] - used if p and any(p not in place_set[k] for k in others)]
                own_stops = [s for s in kind - used if any(s not in k for k in others)]
                pick = min(own_places, key=lambda p: (sum(p in place_set[k] for k in others), p), default=None) \
                    or min(own_stops, key=lambda s: (sum(s in k for k in others), s), default=None)
                if pick:
                    label[kind] = f'{text}, {pick}' if text else pick
    for kind, rids in by_stops.items():
        for rid in rids:
            out[rid]['via'] = label[kind]


def table() -> dict[str, dict]:
    """routeId -> {'groupId', 'via'}, rebuilt when the routes or the patterns are reloaded."""
    try:
        routes, pats = sources.routes.get(), sources.patterns.get()
        stops = sources.stops.get()
    except UpstreamError:
        return _built['value'] or {}
    key = (id(routes.value), id(pats.value), id(stops.value))
    with _lock:
        if _built['key'] != key:
            from . import operators as companies
            ids = companies.table()['canonical']
            _built.update(key=key, value=build(routes.value, pats.value['patterns'], sources.stop_names(),
                                               lambda r: companies.canonical(r.get('agencyId'), ids)))
        return _built['value']


def of(route_id: str) -> dict:
    """{'groupId', 'via'} of one route (its own group when unknown)."""
    return table().get(route_id) or {'groupId': 'g:' + hashlib.sha1(f'route|{route_id}'.encode()).hexdigest()[:12], 'via': None}


def siblings(route_id: str) -> list[dict]:
    """The route's group, itself included: [{'routeId', 'via', 'name'}], busiest-named first."""
    from . import mapping
    t = table()
    mine = t.get(route_id)
    if not mine:
        return []
    routes = sources.routes.peek()
    names = routes.value if routes else {}
    members = [rid for rid, v in t.items() if v['groupId'] == mine['groupId']]
    return [{'routeId': rid, 'via': t[rid]['via'], 'name': mapping.route_name(names.get(rid) or {}) or rid} for rid in sorted(members)]

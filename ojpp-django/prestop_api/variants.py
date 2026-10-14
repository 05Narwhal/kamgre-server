"""Route variants (contract 4): the lines between the same two places by the same operator are one group.

IJPP publishes each way a bus can take as its own route: Tržič–Ljubljana via Kovor and via Duplje, Kropa–Kranj
via Strahinj and via Podnart. Routes form a group (`groupId`) when their operator and mode match and their
longest patterns run between the same two places (end stop names normalised, either direction). Within a group,
`via` names the place on a variant the fewest others pass ("Kovor", "Duplje"), then, when some share it, a place
that sets it apart from them ("Kovor, Naklo"); ties go to the place nearest the middle of its way, where variants
part. A route alone in its group, or one with nothing of its own, has `via: null`.
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


def _in_town(name: str) -> str:
    """Where in its town a stop is ("Ljubljana Šentvid" -> "Šentvid"); the whole name for a bare code ("Ruše GD")."""
    place = _place(name.split(None, 1)[1])
    return name if len(place) <= 3 or place.isupper() else place


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
            ends = sorted(stopgroups.normalize(names.get(s, s)) for s in (stops[0], stops[-1]))
            key = f'{operator_of(r) or rid.split(":", 1)[0]}|{r.get("mode")}|{ends[0]}|{ends[1]}'
        else:
            key = f'route|{rid}'
        group = 'g:' + hashlib.sha1(key.encode()).hexdigest()[:12]
        groups[group].append(rid)
        out[rid] = {'groupId': group, 'via': None}
    for members in groups.values():
        if len(members) < 2:
            continue
        # A town every variant passes names the stops in it ("Ljubljana Šentvid" is at Šentvid).
        towns = frozenset.intersection(*(frozenset(_place(names.get(x, x)) for x in served_ids[rid]) for rid in members))
        place_of = lambda name: _in_town(name) if _place(name) in towns and len(name.split()) > 1 else _place(name)
        places = {rid: {place_of(names.get(x, x)) for x in served_ids[rid]} for rid in members}
        # Variants by the places they serve: a route listed once per direction is one variant.
        kinds = {frozenset(places[rid]) for rid in members}
        if len(kinds) < 2:
            continue
        holders = lambda place: frozenset(k for k in kinds if place in k)
        for rid in members:
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
    return out


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

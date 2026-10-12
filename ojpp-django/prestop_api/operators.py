"""One operator per company, whichever feed lists it.

The same company appears under several ids: LPP is `LPP:lpp` in its own feed and `IJPP:1118` in
the national one, Nomago is `IJPP:1119` and `Postojna:Postojna`, Bolt is one rental provider per
vehicle type. Every operator id that leaves the API is canonical, so the app's operator filter
hides a company everywhere:

- ids whose names normalize the same (lowercase, no diacritics, legal suffixes such as d.o.o. and
  d.d. removed, spaces collapsed) are one operator; the id with the most routes is canonical;
- `data/operator_aliases.csv` (source_id, canonical_id, name) decides what a name cannot ("AP Murska
  Sobota, d.d." and "Avtobusni promet Murska Sobota d.d." are one company) and names the merged row.

Request parameters may name any source id: `same()` compares by canonical id, so ids the app saved
before the merge still filter correctly.
"""
import csv
import logging
import os
import re
import threading
from pathlib import Path
from typing import Iterable, Optional

from .mapping import fold, provider_name

logger = logging.getLogger(__name__)

ALIASES = Path(__file__).resolve().parent / 'data' / 'operator_aliases.csv'
SUFFIX = re.compile(r'\s+(?:d\s?o\s?o|d\s?d|s\s?p|k\s?d|gmbh|s\s?r\s?l|ltd)$')
KEYS = ('operatorId', 'agencyId', 'providerId')


def normalize(name: str) -> str:
    """'Ljubljanski potniški promet, d.o.o.' → 'ljubljanski potniski promet'; 'NOMAGO d.o.o.' → 'nomago'."""
    text = re.sub(r'[^a-z0-9]+', ' ', fold(name or '')).strip()
    while True:
        shorter = SUFFIX.sub('', text).strip()
        if shorter == text:
            return text
        text = shorter


def read_aliases(path: Path = ALIASES) -> dict[str, tuple[str, str]]:
    """source id -> (canonical id, name). Bad rows are logged and skipped."""
    out = {}
    if not path.exists():
        return out
    with open(path, newline='', encoding='utf-8') as handle:
        for n, row in enumerate(csv.DictReader(line for line in handle if not line.startswith('#')), start=2):
            source, target = (row.get('source_id') or '').strip(), (row.get('canonical_id') or '').strip()
            if ':' not in source or ':' not in target:
                logger.warning('operator_aliases.csv line %s skipped: %s', n, row)
                continue
            out[source] = (target, (row.get('name') or '').strip())
    return out


def build(known: dict[str, tuple[str, int]], aliases: dict[str, tuple[str, str]]) -> dict:
    """From {id: (name, route count)} and the alias table: {'canonical': id -> canonical id,
    'names': canonical id -> name, 'labels': canonical id -> name from the alias table, 'sources': canonical id -> [ids]}."""
    groups: dict[str, list[str]] = {}
    for op_id, (name, _) in known.items():
        groups.setdefault(normalize(name) or op_id, []).append(op_id)
    canonical = {}
    for ids in groups.values():
        head = sorted(ids, key=lambda i: (-known[i][1], i))[0]
        canonical.update({i: head for i in ids})
    for source, (target, _) in aliases.items():  # the source's and the target's groups become one, led by the target
        joined = {canonical.get(source, source), canonical.get(target, target)}
        for i, c in list(canonical.items()):
            if c in joined:
                canonical[i] = target
        canonical[source] = canonical[target] = target
    labels = {canonical[target]: name for _, (target, name) in aliases.items() if name}
    names = {**{c: known[c][0] for c in set(canonical.values()) if c in known}, **labels}
    sources: dict[str, list[str]] = {}
    for i, c in canonical.items():
        sources.setdefault(c, []).append(i)
    return {'canonical': canonical, 'names': names, 'labels': labels, 'sources': {c: sorted(ids) for c, ids in sources.items()}}


# ---------------------------------------------------------------- serving-time table

_lock = threading.Lock()
_table: dict = {'key': None, 'value': {'canonical': {}, 'names': {}, 'labels': {}, 'sources': {}}}


def _known() -> tuple[tuple, dict[str, tuple[str, int]]]:
    """Every operator and rental provider the sources list, with its name and route count."""
    from . import sources
    # Peek only: the route index is loaded by every endpoint that lists operators; until then the alias table applies.
    route_snap, rental_snap = sources.routes.peek(), sources.rentals.peek()
    known: dict[str, list] = {}
    for r in (route_snap.value.values() if route_snap else []):
        if r.get('agencyId'):
            entry = known.setdefault(r['agencyId'], [r.get('agencyName') or r['agencyId'], 0])
            entry[1] += 1
    for item in (rental_snap.value if rental_snap else []):
        known.setdefault(item['providerId'], [provider_name(item['providerId']), 0])
    key = (route_snap.value if route_snap else None, rental_snap.value if rental_snap else None)
    return key, {k: (v[0], v[1]) for k, v in known.items()}


def table() -> dict:
    key, known = _known()
    try:
        stamp = os.stat(ALIASES).st_mtime
    except OSError:
        stamp = None
    with _lock:
        old = _table['key']
        if old is None or old[0] is not key[0] or old[1] is not key[1] or old[2] != stamp:
            _table.update(key=(*key, stamp), value=build(known, read_aliases()))
        return _table['value']


def canonical(op_id: Optional[str], mapping: Optional[dict] = None) -> Optional[str]:
    if not op_id:
        return op_id
    return (mapping if mapping is not None else table()['canonical']).get(op_id, op_id)


def same(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two operator ids (canonical or not) are the same operator."""
    ids = table()['canonical']
    return canonical(a, ids) == canonical(b, ids)


def expand(op_ids: Iterable[str]) -> list[str]:
    """Each operator id with every id merged into its company (for filters upstream, e.g. OTP agencies)."""
    t = table()
    out = []
    for op_id in op_ids:
        c = canonical(op_id, t['canonical'])
        out.extend([op_id, *t['sources'].get(c, [c])])
    return list(dict.fromkeys(out))


def rewrite(data):
    """The response payload with every operator id canonical (operatorId, agencyId, providerId,
    operatorIds). Lists of coordinates are skipped. Returns new containers where something changed."""
    ids = table()['canonical']
    if not ids:
        return data
    return _walk(data, ids)


def _walk(value, ids: dict):
    if isinstance(value, dict):
        out = None
        for k, v in value.items():
            if k in KEYS and isinstance(v, str):
                new = ids.get(v, v)
                changed = new != v
            elif k == 'operatorIds' and isinstance(v, list):
                new = list(dict.fromkeys(ids.get(i, i) for i in v))
                changed = new != v
            elif isinstance(v, (dict, list)):
                new = _walk(v, ids)
                changed = new is not v
            else:
                continue
            if changed:
                out = out if out is not None else dict(value)
                out[k] = new
        return out if out is not None else value
    if isinstance(value, list):
        if not value or not isinstance(value[0], (dict, list)) or (isinstance(value[0], list) and value[0] and not isinstance(value[0][0], (dict, list))):
            return value  # numbers, strings or coordinates
        out = None
        for i, v in enumerate(value):
            new = _walk(v, ids)
            if new is not v:
                out = out if out is not None else list(value)
                out[i] = new
        return out if out is not None else value
    return value


def merge_rows(rows: Iterable[dict]) -> list[dict]:
    """Capability rows ({id, name, modes}) merged per canonical operator, with the ids merged into it as `sourceIds`.
    The name is the alias table's, else the canonical row's own (e.g. a GBFS system name), else the first row's."""
    t = table()
    merged: dict[str, dict] = {}
    for row in rows:
        c = canonical(row['id'], t['canonical'])
        entry = merged.setdefault(c, {'id': c, 'name': row['name'], 'modes': set(), 'sourceIds': set()})
        if row['id'] == c:
            entry['name'] = row['name']
        entry['modes'] |= set(row['modes'])
        entry['sourceIds'].add(row['id'])
    for c, entry in merged.items():
        entry['name'] = t['labels'].get(c) or entry['name']
    return [{**e, 'modes': sorted(e['modes']), 'sourceIds': sorted(e['sourceIds'] | {e['id']})} for e in merged.values()]


def merges() -> list[tuple[str, str, list[str]]]:
    """(canonical id, name, merged ids) of every operator that joins more than one id, for a person to check."""
    t = table()
    return sorted((c, t['names'].get(c, ''), ids) for c, ids in t['sources'].items() if len(ids) > 1)

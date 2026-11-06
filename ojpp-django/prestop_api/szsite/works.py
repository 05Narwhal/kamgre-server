"""SŽ's works on the lines ("DELA NA PROGI") as lineWorks, the shape `zamudil.line_works` gives, from our reader's copy
of the status page's `var roadworks` (`<PRESTOP_SZSITE_DIR>/works.json`, read from the file, not over HTTP).

SŽ groups what happens at one place in one item: `Naslov`, `Cas`, `Relacija`, `Vrsta`, `Opis`, `ID_ovire` are lists
of the same length, one entry per notice, and the item has one point (`Koordinate`, [lon, lat] as strings). Only the
entries of kind "Dela na progi" are works (the others are replacement buses and cancelled trains, read with the
notices). An entry's line is the railway between the stations its `Relacija` names ("Ljubljana - Borovnica";
"Jesenice / Kranj - Ljubljana" is a line from each): the feed's railway stations of those names, the one nearest the
item's point, joined along the track (`railtrack.along`, worked out once). A relation we cannot place on the track is
left out: no straight line across the country.

`line_works()` is None when SŽ's copy does not lead (PRESTOP_SZSITE_WORKS off, no copy, or older than FRESH), and
zamudil.si's maintenance is read instead.
"""
import logging
import re
import time
from datetime import date
from typing import Callable, Optional

from django.conf import settings

from .client import BASE, SOLVE_PAGE
from .parse import DAYS

logger = logging.getLogger(__name__)
FRESH = 3600  # s: the reader saves the works every 15 minutes; an older copy no longer leads
KIND = 'dela na progi'
# SŽ files some notices under "Dela na progi" that are not works: "DODATNO: Avtobusni prevoz …", "OBVESTILO: Vlak vozi
# samo do/s …", "OPOZORILO: Nakladanje vozil …". A title with its own capital label is a work only with this one.
LABEL = re.compile(r'^\s*([A-ZČŠŽĆĐ][A-ZČŠŽĆĐ ]{3,}):')
WORK_LABEL = 'DELA NA PROGI'
NEAR_STATION = 1000.0  # m: a relation's name with no station ("Kresnica" for Kresnice) is the station this near the item
SOURCE = BASE + SOLVE_PAGE
_memo: dict = {'stamp': None, 'value': None}


def _at(value, i: int):
    """Entry `i` of one of an item's parallel lists (a bare value counts for every entry)."""
    if isinstance(value, list):
        return value[i] if i < len(value) else None
    return value


def entries(item: dict) -> list[dict]:
    """An item's notices, one dict each: {id, kind, title, days, relation, body}."""
    kinds = item.get('Vrsta')
    count = len(kinds) if isinstance(kinds, list) else 1
    return [{'id': _at(item.get('ID_ovire'), i), 'kind': str(_at(kinds, i) or ''), 'title': str(_at(item.get('Naslov'), i) or ''),
             'days': str(_at(item.get('Cas'), i) or ''), 'relation': str(_at(item.get('Relacija'), i) or ''),
             'body': str(_at(item.get('Opis'), i) or '')} for i in range(count)]


def point(item: dict) -> Optional[list[float]]:
    try:
        lon, lat = (float(x) for x in item.get('Koordinate') or ())
    except (TypeError, ValueError):
        return None
    return [lon, lat] if 13 < lon < 17 and 45 < lat < 47.5 else None


def days(text: str) -> tuple[Optional[str], Optional[str]]:
    found = DAYS.search(text or '')
    if not found:
        return None, None
    d1, m1, y1, d2, m2, y2 = (int(x) for x in found.groups())
    try:
        return date(y1, m1, d1).isoformat(), date(y2, m2, d2).isoformat()
    except ValueError:
        return None, None


def pairs(relation: str) -> list[tuple[str, str]]:
    """The station pairs of a relation: 'Ljubljana - Borovnica', 'Šentjur-Celje', 'Jesenice / Kranj - Ljubljana'
    (each to Ljubljana); 'Lesce-Bled - Bled Jezero' splits at the spaced dash."""
    sides = re.split(r'\s+[-–]\s+', relation.strip())
    if len(sides) != 2:
        sides = re.split(r'\s*[-–]\s*', relation.strip())
    if len(sides) != 2:
        return []
    a, b = ([n.strip() for n in side.split('/') if n.strip()] for side in sides)
    return [(x, y) for x in a for y in b if x != y]


def _text(body: str) -> tuple[str, Optional[str]]:
    from .. import sz_list
    link = re.search(r'href="([^"]+)"', body or '')
    return sz_list._text(body or ''), link.group(1) if link else None


def convert(items: list, station: Callable[[str, list], Optional[list]], follow: Callable[[list], list]) -> list[dict]:
    """lineWorks of SŽ's `roadworks` items. `station(name, near)`: [lon, lat] of the railway station of that name
    nearest `near`, or None; `follow(chord)`: the chord between two stations along the track (as it was when it
    cannot be followed)."""
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        near = point(item)
        for entry in entries(item):
            label = LABEL.match(entry['title'])
            if KIND not in entry['kind'].lower() or (label and label.group(1).strip() != WORK_LABEL):
                continue
            start, end = days(entry['days'])
            found = pairs(entry['relation'])
            if not start or not end or not near or not found:
                logger.info('SŽ work %s left out: days %r, relation %r', entry['id'], entry['days'], entry['relation'])
                continue
            text, url = _text(entry['body'])
            title = entry['title'].strip()
            lines = []
            for a, b in found:
                pa, pb = station(a, near), station(b, near)
                line = follow([pa, pb]) if pa and pb else None
                if line and len(line) > 2:
                    lines.append([[round(float(p[0]), 6), round(float(p[1]), 6)] for p in line])
                else:
                    logger.info('SŽ work %s: %s - %s not on the track', entry['id'], a, b)
            for k, line in enumerate(lines):
                key = f"sz-{entry['id'] or item.get('Lokacija') or ''}"
                out.append({'id': key if len(lines) == 1 else f'{key}-{k + 1}', 'title': title or entry['relation'], 'message': text,
                            'relation': entry['relation'], 'validFrom': start, 'validTo': end, 'geometry': line,
                            'sourceUrl': url or SOURCE})
    return out


def _station_finder(stop_index: dict) -> Callable[[str, list], Optional[list]]:
    from .. import closures, geometry
    stations = closures.stations_of(stop_index)

    def station(name: str, near: list) -> Optional[list]:
        # A name the feed spells otherwise: the railway station at the item's point, if there is one.
        found = stations.railway(name) or stations.rail
        best = min(found, key=lambda s: geometry.distance(near, [s['longitude'], s['latitude']]), default=None)
        if best and found is stations.rail and geometry.distance(near, [best['longitude'], best['latitude']]) > NEAR_STATION:
            best = None
        return [best['longitude'], best['latitude']] if best else None
    return station


def copy(now: Optional[float] = None) -> Optional[dict]:
    """The reader's last good works copy ({'at', 'count', 'data'}) while it leads, else None."""
    directory = getattr(settings, 'PRESTOP_SZSITE_DIR', '')
    if not getattr(settings, 'PRESTOP_SZSITE_WORKS', False) or not directory:
        return None
    from .store import Store
    saved = Store(directory).load('works')
    if not saved or not isinstance(saved.get('data'), list):
        return None
    return saved if (time.time() if now is None else now) - float(saved.get('at') or 0) < FRESH else None


def line_works(now: Optional[float] = None) -> Optional[list[dict]]:
    """SŽ's works as lineWorks while our reader's copy leads, else None. Worked out once per copy."""
    saved = copy(now)
    if saved is None:
        return None
    from .. import railtrack, sources
    try:
        stop_index = sources.stops.get().value
    except Exception as e:  # noqa: BLE001 - no stops (OTP down): zamudil.si's works instead
        logger.warning('SŽ works: no stops to place them (%r)', e)
        return None
    stamp = saved['at'], id(stop_index)
    if _memo['stamp'] != stamp:
        _memo.update(stamp=stamp, value=convert(saved['data'], _station_finder(stop_index), railtrack.along))
    return _memo['value']

"""SŽ's own list of where its replacement buses stop.

SŽ publishes, per railway line, where the bus stops for each station when buses replace trains
("Lokacije postankov nadomestnih prevozov", potniski.sz.si/vozni-redi/lokacije-postankov-
nadomestnih-prevozov/): "Zunanja stran železniške postaje", "Avtobusno postajališče Polje
kolodvor, ob podvozu", … each with a Google Maps link. The page sits behind a bot check, so it is
scraped by hand and imported with `manage.py import_sz_stops <json>` into
`data/sz_replacement_stops.csv` (route, station, position, the rider-facing description and where
the position came from).

Positions taken from a map's camera centre (`map_camera_only`) only say roughly where the map was
looking, so they count as unverified. A station named on several lines (Ljubljana, Zidani Most)
can have a different stop per line: the line sharing the most stations with the bus wins.
"""
import csv
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from . import geometry, mapping

logger = logging.getLogger(__name__)

FILE = Path(__file__).resolve().parent / 'data' / 'sz_replacement_stops.csv'
FIELDS = ['route', 'station', 'lat', 'lon', 'label', 'source']
APPROXIMATE = {'map_camera_only'}
MAX_FROM_STATION = 3000   # m: an entry further than this from the station is another station's namesake

_cache: dict = {'stamp': None, 'rows': [], 'checked': 0.0}
STAMP_EVERY = 10  # s between checks for a re-imported file
_lock = threading.Lock()


def _tokens(name: str) -> list[str]:
    return re.findall(r'[a-z0-9]+', mapping.fold((name or '').split('(')[0]))


def same_station(listed: str, station: str) -> bool:
    """'Lesce Bled' ~ 'Lesce-Bled', 'Ljubljana' ~ 'Ljubljana' but not 'Ljubljana Zalog'."""
    a, b = _tokens(listed), _tokens(station)
    return bool(a) and len(a) == len(b) and all(y.startswith(x) or x.startswith(y) for x, y in zip(a, b))


def read(path: Path = FILE) -> list[dict]:
    """The list's rows with float positions; bad rows are logged and skipped."""
    out = []
    try:
        with open(path, encoding='utf-8', newline='') as f:
            for row in csv.DictReader(line for line in f if not line.startswith('#')):
                try:
                    out.append({**row, 'lat': float(row['lat']), 'lon': float(row['lon'])})
                except (KeyError, TypeError, ValueError):
                    logger.warning('Bad SŽ replacement stop row: %r', row)
    except OSError:
        return []
    return out


def rows() -> list[dict]:
    """The list, re-read when the file changes (checked every STAMP_EVERY s)."""
    now = time.monotonic()
    if _cache['stamp'] is not None and now - _cache['checked'] < STAMP_EVERY:
        return _cache['rows']
    try:
        stamp = os.stat(FILE).st_mtime
    except OSError:
        return []
    with _lock:
        _cache['checked'] = now
        if _cache['stamp'] != stamp:
            _cache.update(stamp=stamp, rows=read())
        return _cache['rows']


def lookup(station: dict, context: Iterable[str] = (), table: Optional[list[dict]] = None) -> Optional[dict]:
    """Where SŽ's replacement bus stops for `station` ({'name', 'lat', 'lon'}): {'lat', 'lon', 'label',
    'unverified'}, or None. `context`: names of the other stations the bus calls at, to pick the
    right line's entry where a station is listed on several lines."""
    table = rows() if table is None else table
    here = [station['lon'], station['lat']]
    found = [r for r in table if same_station(r['station'], station.get('name') or '')
             and geometry.distance(here, [r['lon'], r['lat']]) <= MAX_FROM_STATION]
    if not found:
        return None
    others = [n for n in context if n]

    def shared(route: str) -> int:
        on_line = [r['station'] for r in table if r['route'] == route]
        return sum(1 for n in others if any(same_station(s, n) for s in on_line))
    best = max(found, key=lambda r: (shared(r['route']), r.get('source') not in APPROXIMATE))
    return {'lat': best['lat'], 'lon': best['lon'], 'label': best.get('label') or '', 'unverified': best.get('source') in APPROXIMATE}


def from_scrape(data: dict) -> list[dict]:
    """CSV rows from the hand scrape's JSON (`stops` with route, station, description, latitude,
    longitude, coordinate_source), one per route and station."""
    out, seen = [], set()
    for s in data.get('stops') or []:
        if s.get('latitude') is None or s.get('longitude') is None:
            continue
        key = (s.get('route'), s.get('station'))
        if key in seen:
            continue
        seen.add(key)
        label = re.sub(r'\s+', ' ', (s.get('description') or '').strip()).rstrip(' :').removesuffix(' in').strip()
        out.append({'route': s['route'], 'station': s['station'], 'lat': f'{float(s["latitude"]):.6f}', 'lon': f'{float(s["longitude"]):.6f}',
                    'label': label, 'source': s.get('coordinate_source') or ''})
    return out

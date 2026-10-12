"""Stop positions we correct on top of the feeds.

Feeds misplace stops: Koper's intercity station sat ~170 m south of the bus station, and
GPS-surveyed stops drift off the road. Two corrections apply, in this order of trust:

1. `data/stop_overrides.csv` (hand-maintained, version-controlled) wins over everything.
   Row types: `stop` moves one stop (and with `merge_into` joins it to another stop's
   station), `station` pins the marker of the merged station the stop belongs to, and
   `replacement` adds the stop where SŽ's replacement buses leave from (next to the station,
   not at it) — see replacement.py.
2. Automatic snapping: a stop more than SNAP_METERS from a road buses can use moves to the
   nearest road point (Valhalla `locate`, cached in `data/stop_snaps.json` by stop id and
   position). A stop that would move more than MAX_SNAP_METERS stays put and is listed in the
   report for a person to check. `manage.py snap_stops` fills the cache and writes the report;
   serving never calls Valhalla for snaps.

Both are pure functions of the feed and these files, so applying them twice changes nothing.
"""
import csv
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from . import geometry

logger = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parent / 'data'
OVERRIDES = DATA / 'stop_overrides.csv'
SNAPS = DATA / 'stop_snaps.json'
REPORT = DATA / 'stop_report.csv'
SNAP_METERS = 40       # a stop further than this from a bus road is snapped onto it
MAX_SNAP_METERS = 150  # ... unless the road is further than this: then a person checks it
TYPES = {'stop', 'station', 'replacement'}


def _float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_overrides(path: Path = OVERRIDES) -> dict:
    """{'stops': id -> (lat, lon), 'stations': id -> (lat, lon), 'merge': id -> target id,
    'replacement': station id -> [{'lat', 'lon', 'label'}]}. Bad rows are logged and skipped."""
    out = {'stops': {}, 'stations': {}, 'merge': {}, 'replacement': {}}
    if not path.exists():
        return out
    with open(path, newline='', encoding='utf-8') as handle:
        for n, row in enumerate(csv.DictReader(line for line in handle if not line.startswith('#')), start=2):
            stop_id = (row.get('stop_id') or '').strip()
            kind = (row.get('type') or 'stop').strip() or 'stop'
            lat, lon = _float(row.get('lat')), _float(row.get('lon'))
            if not stop_id or kind not in TYPES or (lat is None) != (lon is None):
                logger.warning('stop_overrides.csv line %s skipped: %s', n, row)
                continue
            if kind == 'replacement':
                if lat is not None:
                    out['replacement'].setdefault(stop_id, []).append({'lat': lat, 'lon': lon, 'label': (row.get('label') or '').strip()})
                continue
            if lat is not None:
                out['stations' if kind == 'station' else 'stops'][stop_id] = (lat, lon)
            target = (row.get('merge_into') or '').strip()
            if target and target != stop_id:
                out['merge'][stop_id] = target
    return out


def snap_key(stop_id: str, lat: float, lon: float) -> str:
    return f'{stop_id}@{lat:.5f},{lon:.5f}'


def read_snaps(path: Path = SNAPS) -> dict:
    """snap key -> [road lat, road lon, metres off the road]."""
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def snapped(stop_id: str, lat: float, lon: float, snaps: dict) -> Optional[tuple[float, float]]:
    """The road position for a stop that is off the road by more than SNAP_METERS but not MAX_SNAP_METERS."""
    hit = snaps.get(snap_key(stop_id, lat, lon))
    if hit and SNAP_METERS < hit[2] <= MAX_SNAP_METERS:
        return hit[0], hit[1]
    return None


def corrected(stop_id: str, lat: float, lon: float, overrides: dict, snaps: dict) -> tuple[float, float]:
    """A stop's position after the override table, then the road snap."""
    if stop_id in overrides['stops']:
        return overrides['stops'][stop_id]
    return snapped(stop_id, lat, lon, snaps) or (lat, lon)


def correct(raw_stops: Iterable[dict], overrides: dict, snaps: dict) -> list[dict]:
    """OTP stops with corrected `lat`/`lon` (copies; the feed's position kept as `feedLat`/`feedLon`)."""
    out = []
    for s in raw_stops:
        if s.get('lat') is None or s.get('lon') is None:
            out.append(s)
            continue
        lat, lon = corrected(s['gtfsId'], s['lat'], s['lon'], overrides, snaps)
        out.append(s if (lat, lon) == (s['lat'], s['lon']) else {**s, 'lat': lat, 'lon': lon, 'feedLat': s['lat'], 'feedLon': s['lon']})
    return out


# ---------------------------------------------------------------- serving-time lookup

_lock = threading.Lock()
_loaded: dict = {'stamp': None, 'overrides': None, 'snaps': None, 'checked': 0.0}
STAMP_EVERY = 10  # s between checks for an edited file (a stat per stop was most of a 10 s rebuild)


def _stamp():
    return tuple(os.stat(p).st_mtime if p.exists() else None for p in (OVERRIDES, SNAPS))


def tables() -> tuple[dict, dict]:
    """(overrides, snaps), re-read when either file changes (checked every STAMP_EVERY s)."""
    now = time.monotonic()
    if _loaded['overrides'] is not None and now - _loaded['checked'] < STAMP_EVERY:
        return _loaded['overrides'], _loaded['snaps']
    stamp = _stamp()
    with _lock:
        _loaded['checked'] = now
        if _loaded['stamp'] != stamp:
            _loaded.update(stamp=stamp, overrides=read_overrides(), snaps=read_snaps())
        return _loaded['overrides'], _loaded['snaps']


def position(stop_id: Optional[str], lat: float, lon: float) -> tuple[float, float]:
    """Corrected position for a stop seen in a trip or journey (the feed's when there is no correction)."""
    if not stop_id:
        return lat, lon
    overrides, snaps = tables()
    return corrected(stop_id, lat, lon, overrides, snaps)


def replacement_stops(station_ids: Iterable[str]) -> list[dict]:
    overrides, _ = tables()
    return [{**r, 'stationId': sid} for sid in station_ids for r in overrides['replacement'].get(sid, [])]


# ---------------------------------------------------------------- Valhalla locate (snap_stops command)

def road_point(answer: dict) -> Optional[tuple[float, float, float]]:
    """Nearest correlated road point of one `locate` answer and its distance from the input."""
    best = None
    for edge in answer.get('edges') or []:
        lat, lon = edge.get('correlated_lat'), edge.get('correlated_lon')
        if lat is None or lon is None:
            continue
        d = geometry.distance([answer['input_lon'], answer['input_lat']], [lon, lat])
        if best is None or d < best[2]:
            best = (round(lat, 6), round(lon, 6), round(d, 1))
    return best


def stop_name(label: str, station: str) -> str:
    """What to call a replacement-bus stop: SŽ's description where it names the place ("Avtobusna postaja
    Ljubljana (peroni 37, 38 in 39)", "Avtobusno postajališče SŽ Šiška"), with the station put first where
    it doesn't ("Zunanja stran železniške postaje" → "Črnomelj · Zunanja stran železniške postaje")."""
    from .mapping import fold
    label, station = (label or '').strip(), (station or '').strip()
    if not label:
        return station
    words = [w for w in fold(station).replace('-', ' ').split() if len(w) > 2]
    if not station or any(w in fold(label) for w in words):
        return label
    return f'{station} · {label}'

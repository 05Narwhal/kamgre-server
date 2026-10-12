"""Which bay a bus leaves from at a big bus station, and where in that bay it stands.

The feeds have one stop for a whole bus station (Ljubljana AP is IJPP:1126954, 46 bays), so every
departure would start at the same point. Two sources fix that:

- Where each bay is: `data/platform_bays.json`, read from OpenStreetMap by `manage.py platform_bays`
  (each bay's position, the direction a bus stands in it and its piece of road). Checked in, and
  correctable by hand.
- Which bay a departure uses: the station's own departure board. AP Ljubljana's site lists the
  next departures with their bay (`/api/upcoming`: time, operator, destination, "platform").
  Every poll (the delay collector calls `learn()` every few minutes) is remembered in the
  `PlatformSeen` table under the departure's time and destination, so a departure seen once keeps
  its bay on later days, also when it is not on the board yet.

A trip that starts at such a station starts in its bay (`place`): its first stop is moved there
and its line begins with the bay's road, so a waiting bus is drawn in the right bay, facing out.
Rows in `data/platform_overrides.csv` (station, time, destination, bay) win over the board.
"""
import csv
import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from django.conf import settings

from . import mapping
from .upstream import UpstreamError, get_json

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
DATA = Path(__file__).resolve().parent / 'data'
BAYS = DATA / 'platform_bays.json'
OVERRIDES = DATA / 'platform_overrides.csv'

# Stations with bays: the feed stop, where to look for bays in OSM, the station's own ground (`ground`
# m around lat/lon: bays 1-46, the aisles and the driveways), and the departure board.
STATIONS = {
    'IJPP:1126954': {'name': 'Avtobusna postaja Ljubljana', 'lat': 46.05805, 'lon': 14.51475, 'radius': 200, 'ground': 130, 'board': 'ap-ljubljana'},
}
# Stops whose replacement buses leave from a bus station's bays, when SŽ names them ("peroni 37, 38 in 39").
NEXT_DOOR = {'IJPP:1122804': 'IJPP:1126954'}  # Ljubljana railway station -> Ljubljana AP
LEARN_EVERY = 180   # s between polls of a departure board
# A departure the board has not shown yet gets its destination's usual bay if this share of that
# destination's departures used it (measured 2026-10-12: the usual bay was right for 86%).
USUAL_SHARE = 0.5
PERON = re.compile(r'peron\w*\s+((?:\d+\s*(?:,|in|-|–)?\s*)+)', re.IGNORECASE)
STOPWORDS = {'ap', 'avtobusna', 'postaja', 'zp', 'center', 'bs', 'k', 'pri', 'na', 'v', 'ob'}

_bays: dict = {'stamp': None, 'value': {}}
_lock = threading.Lock()
_last_learn: dict[str, float] = {}


# ---------------------------------------------------------------- bays

def read_bays() -> dict:
    try:
        return json.loads(BAYS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def bays(station_id: str) -> dict:
    """ref -> {'lat', 'lon', 'heading', 'path'} for a station (re-read when the file changes)."""
    try:
        stamp = BAYS.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _bays['stamp'] != stamp:
            _bays.update(stamp=stamp, value=read_bays())
        return (_bays['value'].get(station_id) or {}).get('bays') or {}


def first_bay(platform: str, known: dict) -> Optional[str]:
    """The bay to draw for a board's platform text: '13' → '13', '27-29' → '27', '37, 38 in 39' → '37'."""
    for ref in re.findall(r'\d+', platform or ''):
        if ref in known:
            return ref
    return None


# ---------------------------------------------------------------- departure boards

def _words(name: str) -> set[str]:
    return {w for w in re.findall(r'[a-z0-9]+', mapping.fold((name or '').split('(')[0])) if w not in STOPWORDS and len(w) > 1}


def same_place(a: str, b: str) -> bool:
    """'Bohinj Ukanc' ~ 'Ukanc', 'Novo mesto' ~ 'Novo mesto AP', 'Videm v Dobrepolju' ~ 'Videm (Dobrepolje)'."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return bool(wa & wb) or any(x.startswith(y) or y.startswith(x) for x in wa for y in wb if min(len(x), len(y)) >= 4)


def board_rows(raw: list) -> list[dict]:
    """AP Ljubljana's upcoming departures as {'time': 'HH:MM', 'destination', 'operator', 'platform'}."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not item.get('platform') or not item.get('formatted_time'):
            continue
        out.append({'time': str(item['formatted_time'])[:5], 'destination': item.get('online_heading') or '',
                    'operator': item.get('company') or '', 'platform': str(item['platform']).strip()})
    return out


def _board_url(board: str) -> str:
    return getattr(settings, 'PRESTOP_AP_LJUBLJANA_URL', '') if board == 'ap-ljubljana' else ''


def learn(now: Optional[float] = None) -> int:
    """Poll the departure boards (at most every LEARN_EVERY s) and remember each departure's bay."""
    from .models import PlatformSeen
    now = now or time.time()
    stored = 0
    for station_id, spec in STATIONS.items():
        url = _board_url(spec['board'])
        if not url or now - _last_learn.get(station_id, 0) < LEARN_EVERY:
            continue
        _last_learn[station_id] = now
        try:
            rows = board_rows(get_json(url, limit=2 * 1024 * 1024, timeout=(4, 15)))
        except UpstreamError as e:
            logger.info('Departure board %s unavailable: %r', spec['board'], e)
            continue
        for row in rows:
            key = f'{station_id}|{row["time"]}|{" ".join(sorted(_words(row["destination"])))}'[:200]
            PlatformSeen.objects.update_or_create(key=key, defaults={'platform': row['platform'][:16], 'destination': row['destination'][:120], 'operator': row['operator'][:80]})
            stored += 1
    return stored


def overrides() -> list[dict]:
    try:
        with open(OVERRIDES, encoding='utf-8', newline='') as f:
            return [r for r in csv.DictReader(line for line in f if not line.startswith('#')) if r.get('bay')]
    except OSError:
        return []


def departure_platform(station_id: str, departure: float, destination: str, seen: Optional[Iterable] = None) -> Optional[str]:
    """The platform text for a departure at `departure` (unix time) to `destination`, from the
    overrides or what the board said for that time and destination; None when unknown."""
    hhmm = datetime.fromtimestamp(departure, LOCAL).strftime('%H:%M')
    for row in overrides():
        if row.get('station') == station_id and row.get('time') == hhmm and same_place(row.get('destination', ''), destination):
            return row['bay']
    if seen is None:
        try:
            from .models import PlatformSeen
            seen = list(PlatformSeen.objects.filter(key__startswith=f'{station_id}|{hhmm}|'))
        except Exception as e:  # no database: no bays
            logger.warning('Platforms unavailable: %r', e)
            return None
    matches = [s for s in seen if same_place(s.destination, destination)]
    return max(matches, key=lambda s: s.updated).platform if matches else None


def station_seen(station_id: str) -> Optional[list]:
    try:
        from .models import PlatformSeen
        return list(PlatformSeen.objects.filter(key__startswith=f'{station_id}|'))
    except Exception as e:  # no database: no bays
        logger.warning('Platforms unavailable: %r', e)
        return None


def usual_platform(station_id: str, departure: float, destination: str, seen: Optional[Iterable] = None, share: float = USUAL_SHARE) -> Optional[str]:
    """The bay departures to `destination` usually leave from, at any time of day (the board only
    reaches ~50 minutes ahead; a line keeps its bay): the most frequent one, if at least `share` of
    that destination's departures used it; of equally frequent bays, the one seen nearest that time."""
    if seen is None:
        seen = station_seen(station_id)
        if seen is None:
            return None
    matches = [s for s in seen if s.key.startswith(f'{station_id}|') and same_place(s.destination, destination)]
    # 'Bled' also matches 'Bled shuttle': the same destination's own departures first.
    words = _words(destination)
    matches = [s for s in matches if _words(s.destination) == words] or matches
    if not matches:
        return None
    minute = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:5]) if re.fullmatch(r'\d\d:\d\d', hhmm) else 0
    at = minute(datetime.fromtimestamp(departure, LOCAL).strftime('%H:%M'))
    counts: dict[str, list[int]] = {}
    for s in matches:
        gap = abs(minute(s.key.split('|')[1]) - at)
        counts.setdefault(s.platform, []).append(min(gap, 1440 - gap))
    best = max(counts, key=lambda p: (len(counts[p]), -min(counts[p])))
    return best if len(counts[best]) >= share * len(matches) else None


def platform_for(station_id: str, departure: float, destination: str, seen: Optional[Iterable] = None) -> tuple[Optional[str], bool]:
    """(platform text, usual): the departure's own bay (overrides, board), else the bay its destination
    usually leaves from (`usual` True), else (None, False)."""
    if seen is not None:
        seen = list(seen)
    hhmm = datetime.fromtimestamp(departure, LOCAL).strftime('%H:%M')
    exact = departure_platform(station_id, departure, destination, None if seen is None else [s for s in seen if s.key.startswith(f'{station_id}|{hhmm}|')])
    if exact:
        return exact, False
    usual = usual_platform(station_id, departure, destination, seen)
    return (usual, True) if usual else (None, False)


# ---------------------------------------------------------------- trips

def bay_for(stop: dict, departure: Optional[float], destination: str, label: str = '') -> Optional[dict]:
    """The bay a trip leaving `stop` stands in, or None. `label`: a replacement stop's description,
    which may name its bays ("peroni 37, 38 in 39")."""
    station = stop.get('gtfsId') or ''
    named = PERON.search(label or '')
    if named and not bays(station):
        station = NEXT_DOOR.get(station, station)
    known = bays(station)
    if not known:
        return None
    ref = first_bay(named.group(1), known) if named else None
    usual = False
    if ref is None and departure is not None:
        seen = station_seen(station)
        platform, usual = platform_for(station, departure, destination, seen)
        ref = first_bay(platform or '', known)
    return {**known[ref], 'ref': ref, 'usual': usual, 'station': station} if ref else None


def origin_area(station_id: str) -> Optional[dict]:
    """The ground of a bus station with bays, as {'latitude', 'longitude', 'radius'}: a bus there
    before its departure is waiting in its bay, wherever its GPS puts it inside; one there at the end
    of its trip has arrived and parks where it is."""
    spec = STATIONS.get(station_id)
    return {'latitude': spec['lat'], 'longitude': spec['lon'], 'radius': spec['ground']} if spec else None


def place(stops: list[dict], departure: Optional[float], destination: str) -> tuple[list[dict], Optional[dict]]:
    """Stops with the first one moved into its bay (a copy), and that bay (or None)."""
    if not stops:
        return stops, None
    bay = bay_for(stops[0], departure, destination, stops[0].get('replacementLabel') or '')
    if not bay:
        return stops, None
    first = {**stops[0], 'lat': bay['lat'], 'lon': bay['lon'], 'bay': bay['ref'], 'bayUsual': bay['usual']}
    return [first, *stops[1:]], bay

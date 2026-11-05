"""Which bay a bus leaves from at a big bus station, and where in that bay it stands.

The feeds have one stop for a whole bus station (Ljubljana AP, 46 bays; see STATIONS), so every
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
and its line begins with the bay's road, so a waiting bus is drawn in the right bay, facing out. One that ends at such
a station ends in the free bay it parks in, and the line page's patterns do the same.
Rows in `data/platform_overrides.csv` (station, time, destination, bay) are the hand route for stations with no
board: a row with a time is that one departure's bay and wins over the board; a row with an empty time is the bay
"every departure to this destination" usually uses, read as `usual` (after the board, before the board's history).
"""
import csv
import json
import logging
import math
import re
import threading
import time
import zlib
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

# Stations with bays, by a name of our own (feeds renumber their stops: Ljubljana AP was IJPP:1126954, is
# IJPP:1168813 since Nov 2026): where to look for bays in OSM (`radius` m), the station's own ground (`ground` m around
# lat/lon: bays 1-46, the aisles and the driveways), the departure board, and `ids`: the feed stops it had (rows of
# `PlatformSeen` keyed by an old id are still read). Which feed stop the station is now is found by place and name
# when the stop index loads (`resolve`); a station that finds none is reported in /health (`unresolved`).
# `next_door`: a railway station whose replacement buses leave from this station's bays, when SŽ names them
# ("peroni 37, 38 in 39"). A station without `board` has bays in OSM but no source for which departure uses which: its
# buses wait in a free bay on the map and no bay is named (Kranj, Maribor, Idrija; checked 2026-11-03: no station
# there publishes bays per departure). `plain`: its feed stop is named just the place ("Idrija"), not "... AP".
STATIONS = {
    'ljubljana-ap': {'name': 'Avtobusna postaja Ljubljana', 'place': 'Ljubljana', 'lat': 46.05805, 'lon': 14.51475, 'radius': 200, 'ground': 130,
                     'board': 'ap-ljubljana', 'ids': ['IJPP:1168813', 'IJPP:1126954'],
                     'next_door': {'place': 'Ljubljana', 'lat': 46.058509, 'lon': 14.512924, 'radius': 150, 'ids': ['IJPP:1122804']}},
    'kranj-ap': {'name': 'Avtobusna postaja Kranj', 'place': 'Kranj', 'lat': 46.2463, 'lon': 14.3547, 'radius': 120, 'ground': 130,
                 'ids': ['IJPP:1121237', 'IJPP:1121238']},
    'maribor-ap': {'name': 'Avtobusna postaja Maribor', 'place': 'Maribor', 'lat': 46.55956, 'lon': 15.65575, 'radius': 120, 'ground': 110,
                   'ids': ['IJPP:1127365']},
    'idrija-ap': {'name': 'Avtobusna postaja Idrija', 'place': 'Idrija', 'lat': 46.00098, 'lon': 14.02571, 'radius': 80, 'ground': 60,
                  'plain': True, 'ids': ['IJPP:1120993']},
}
BUS_STATION = re.compile(r'(^|\W)(ap|avtobusna postaja|avt\.? ?post\.?)(\W|$)')
LEARN_EVERY = 180   # s between polls of a departure board
# A departure the board has not shown yet gets its destination's usual bay if this share of that
# destination's departures used it (measured 2026-10-12: the usual bay was right for 86%).
USUAL_SHARE = 0.5
DEPARTURE_WINDOW = 10  # min: a departure seen this close to the time is the same departure (A5)
PERON = re.compile(r'peron\w*\s+((?:\d+\s*(?:,|in|-|–)?\s*)+)', re.IGNORECASE)
STOPWORDS = {'ap', 'avtobusna', 'postaja', 'zp', 'center', 'bs', 'k', 'pri', 'na', 'v', 'ob'}

_bays: dict = {'stamp': None, 'value': {}}
_lock = threading.Lock()
_warned: set = set()   # hand rows already reported (once per process)
_last_learn: dict[str, float] = {}


# ---------------------------------------------------------------- which feed stop a station is

def _meters(lat: float, lon: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat2 - lat) * 111_320, (lon2 - lon) * 111_320 * math.cos(math.radians(lat)))


def _nearby(stops: list[dict], spec: dict, mode: str) -> list[dict]:
    """Feed stops of `mode` within the spec's radius whose name is the spec's place, nearest first; a bus station
    takes stops that are not also a railway station's."""
    out = []
    for s in stops:
        modes = set(s.get('modes') or [])
        if mode not in modes or (mode == 'bus' and 'rail' in modes) or not same_place(s.get('name') or '', spec['place']):
            continue
        d = _meters(spec['lat'], spec['lon'], s.get('latitude') or 0, s.get('longitude') or 0)
        if d <= spec['radius']:
            out.append((d, s))
    return [s for _, s in sorted(out, key=lambda x: x[0])]


def resolve(stops: list[dict]) -> dict:
    """Station key -> {'ids': its feed stops now, 'nextDoor': its railway station's}: from the stop index (feed
    stops with 'id', 'name', 'latitude', 'longitude', 'modes'). A station's stops are the bus stops at that place in
    its radius whose name says bus station ("Ljubljana AP", "Avtobusna postaja Ljubljana"), nearest first."""
    out = {}
    for key, spec in STATIONS.items():
        ids = [s['id'] for s in _nearby(stops, spec, 'bus') if _station_name(s.get('name') or '', spec)]
        door = spec.get('next_door')
        out[key] = {'ids': ids, 'nextDoor': [s['id'] for s in _nearby(stops, door, 'rail')][:1] if door else []}
    return out


def _station_name(name: str, spec: dict) -> bool:
    """Whether a stop's name says it is the bus station: "Kranj AP", "Avtobusna postaja Maribor"; for a `plain`
    station also the bare place name ("Idrija", not "Idrija Uta")."""
    folded = mapping.fold(name)
    return bool(BUS_STATION.search(folded)) or (bool(spec.get('plain')) and _words(name) == _words(spec['place']))


def _resolved() -> Optional[dict]:
    """What `resolve` found when the stop index last loaded (None before it has)."""
    try:
        from .sources import stops
        snap = stops.peek()
    except Exception:  # no stop index in this process
        return None
    return snap.value.get('bayStations') if snap else None


def station_ids(key: str) -> list[str]:
    """The feed stops of a station with bays: the ones found now, then the ones it had."""
    found = (_resolved() or {}).get(key) or {}
    return list(dict.fromkeys([*(found.get('ids') or []), *STATIONS[key].get('ids', [])]))


def station_key(stop_id: Optional[str]) -> Optional[str]:
    """The station with bays a feed stop (or a station key) is, or None."""
    if not stop_id:
        return None
    if stop_id in STATIONS:
        return stop_id
    return next((key for key in STATIONS if stop_id in station_ids(key)), None)


def next_door(stop_id: Optional[str]) -> Optional[str]:
    """The station with bays whose railway station `stop_id` is, or None."""
    found = _resolved() or {}
    for key, spec in STATIONS.items():
        door = spec.get('next_door') or {}
        if stop_id and stop_id in [*((found.get(key) or {}).get('nextDoor') or []), *door.get('ids', [])]:
            return key
    return None


def unresolved() -> list[str]:
    """Stations with bays that match no stop of the loaded stop index (renumbered or moved in the feed): their buses
    would all stand at one point again. Empty before the index loads."""
    found = _resolved()
    return [] if found is None else sorted(key for key in STATIONS if not (found.get(key) or {}).get('ids'))


# ---------------------------------------------------------------- bays

def read_bays() -> dict:
    try:
        return json.loads(BAYS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def bays(station_id: str) -> dict:
    """ref -> {'lat', 'lon', 'heading', 'path'} for a station (its key or feed stop; re-read when the file changes)."""
    key = station_key(station_id)
    if not key:
        return {}
    try:
        stamp = BAYS.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _bays['stamp'] != stamp:
            _bays.update(stamp=stamp, value=read_bays())
        return (_bays['value'].get(key) or {}).get('bays') or {}


def first_bay(platform: str, known: dict) -> Optional[str]:
    """The bay to draw for a board's platform text: '13' → '13', '27-29' → '27', '37, 38 in 39' → '37'."""
    refs = bay_refs(platform, known)
    return refs[0] if refs else None


def bay_refs(platform: str, known: dict) -> list[str]:
    """Every known bay a board's platform text names, in order: '27-29' → ['27', '28', '29'] (a range is each bay
    in it), '37, 38 in 39' → ['37', '38', '39']."""
    out: list[str] = []
    for a, b in re.findall(r'(\d+)(?:\s*[-–]\s*(\d+))?', platform or ''):
        span = range(int(a), int(b) + 1) if b and 0 <= int(b) - int(a) <= 10 else [int(a)]
        out += [str(n) for n in span if str(n) in known and str(n) not in out]
    return out


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
        url = _board_url(spec.get('board') or '')
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
    """The rows of `platform_overrides.csv` that name a bay (see the file's header). A row naming a bay its station
    has no position for is reported once and kept (its text still shows); `bay_for` never moves a bus to it."""
    try:
        with open(OVERRIDES, encoding='utf-8', newline='') as f:
            rows = [{k: (v or '').strip() for k, v in r.items() if k} for r in csv.DictReader(line for line in f if not line.startswith('#'))]
    except OSError:
        return []
    rows = [r for r in rows if r.get('bay')]
    for r in rows:
        key = station_key(r.get('station'))
        known = bays(key) if key else {}
        problem = ('is no station with bays; the row is ignored' if not key
                   else 'is no bay we have a position for; a bus never moves there' if known and not bay_refs(r['bay'], known) else '')
        if problem and (r['station'], r['bay']) not in _warned:
            _warned.add((r['station'], r['bay']))
            logger.warning('platform_overrides.csv: station %r, bay %r %s', r['station'], r['bay'], problem)
    return [r for r in rows if station_key(r.get('station'))]


def usual_override(station_id: str, destination: str) -> Optional[str]:
    """The bay a hand row with no time gives for every departure to `destination` at this station, or None."""
    key = station_key(station_id)
    for row in overrides():
        if not row.get('time') and station_key(row.get('station')) == key and same_place(row.get('destination', ''), destination):
            return row['bay']
    return None


def departure_platform(station_id: str, departure: float, destination: str, seen: Optional[Iterable] = None) -> Optional[str]:
    """The platform text for a departure at `departure` (unix time) to `destination`, from the
    overrides or what the board said for that time and destination; None when unknown."""
    hhmm = datetime.fromtimestamp(departure, LOCAL).strftime('%H:%M')
    key = station_key(station_id)
    for row in overrides():
        if row.get('time') == hhmm and station_key(row.get('station')) == key and same_place(row.get('destination', ''), destination):
            return row['bay']
    if seen is None:
        seen = station_seen(station_id)
        if seen is None:
            return None
        seen = [s for s in seen if _hhmm(s) == hhmm]
    matches = [s for s in seen if same_place(s.destination, destination)]
    return max(matches, key=lambda s: s.updated).platform if matches else None


def _hhmm(row) -> str:
    parts = row.key.split('|')
    return parts[1] if len(parts) > 1 else ''


def station_seen(station_id: str) -> Optional[list]:
    """The station's `PlatformSeen` rows: under its key, and under the feed stops it had (rows from before a
    renumbering; of one departure seen under both, the newer row)."""
    key = station_key(station_id)
    if not key:
        return []
    try:
        from django.db.models import Q
        from .models import PlatformSeen
        prefixes = [key, *STATIONS[key].get('ids', [])]
        query = Q()
        for p in prefixes:
            query |= Q(key__startswith=f'{p}|')
        rows = list(PlatformSeen.objects.filter(query))
    except Exception as e:  # no database: no bays
        logger.warning('Platforms unavailable: %r', e)
        return None
    newest: dict = {}
    for r in rows:
        departure = r.key.split('|', 1)[-1]
        if departure not in newest or r.updated > newest[departure].updated:
            newest[departure] = r
    return list(newest.values())


def usual_platform(station_id: str, departure: float, destination: str, seen: Optional[Iterable] = None, share: float = USUAL_SHARE) -> Optional[str]:
    """The bay this departure usually leaves from: the one its own departure (to `destination`, within
    DEPARTURE_WINDOW minutes of that time: timetables shift a little) was seen at, else the one departures to
    `destination` usually leave from at any time of day (the board only reaches ~50 minutes ahead; a line keeps its
    bay): the most frequent one, if at least `share` of those departures used it; of equally frequent bays, the one
    seen nearest that time."""
    if seen is None:
        seen = station_seen(station_id)
        if seen is None:
            return None
    matches = [s for s in seen if same_place(s.destination, destination)]
    # 'Bled' also matches 'Bled shuttle': the same destination's own departures first.
    words = _words(destination)
    matches = [s for s in matches if _words(s.destination) == words] or matches
    if not matches:
        return None
    minute = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:5]) if re.fullmatch(r'\d\d:\d\d', hhmm) else 0
    at = minute(datetime.fromtimestamp(departure, LOCAL).strftime('%H:%M'))
    gaps = []
    for s in matches:
        gap = abs(minute(_hhmm(s)) - at)
        gaps.append((s, min(gap, 1440 - gap)))
    for pool in ([(s, g) for s, g in gaps if g <= DEPARTURE_WINDOW], gaps):  # this departure's, then the destination's
        counts: dict[str, list[int]] = {}
        for s, gap in pool:
            counts.setdefault(s.platform, []).append(gap)
        if not counts:
            continue
        best = max(counts, key=lambda p: (len(counts[p]), -min(counts[p])))
        if len(counts[best]) >= share * len(pool):
            return best
    return None


def platform_for(station_id: str, departure: float, destination: str, seen: Optional[Iterable] = None) -> tuple[Optional[str], bool]:
    """(platform text, usual): the departure's own bay (a hand row with its time, else the board), else the bay its
    destination usually leaves from (`usual` True): a hand row with no time, else the board's history; else (None, False)."""
    if seen is not None:
        seen = list(seen)
    hhmm = datetime.fromtimestamp(departure, LOCAL).strftime('%H:%M')
    exact = departure_platform(station_id, departure, destination, None if seen is None else [s for s in seen if _hhmm(s) == hhmm])
    if exact:
        return exact, False
    if hand := usual_override(station_id, destination):
        return hand, True
    usual = usual_platform(station_id, departure, destination, seen)
    return (usual, True) if usual else (None, False)


# ---------------------------------------------------------------- trips

def bay_for(stop: dict, departure: Optional[float], destination: str, label: str = '') -> Optional[dict]:
    """The bay a trip leaving `stop` stands in, or None. `label`: a replacement stop's description,
    which may name its bays ("peroni 37, 38 in 39")."""
    station = stop.get('gtfsId') or ''
    named = PERON.search(label or '')
    if named and not bays(station):
        station = next_door(station) or station
    station = station_key(station) or station
    known = bays(station)
    if not known:
        return None
    refs = bay_refs(named.group(1), known) if named else []
    usual = False
    if not refs and departure is not None:
        seen = station_seen(station)
        platform, usual = platform_for(station, departure, destination, seen)
        refs = bay_refs(platform or '', known)
    if not refs:  # nothing says which bay: it waits in a free one, and none is named
        free = free_bays(station, known, destination)
        alternates = [{'ref': r, 'lat': known[r]['lat'], 'lon': known[r]['lon'], 'heading': known[r].get('heading')} for r in free[1:PARK_BAYS]]
        return {**known[free[0]], 'ref': free[0], 'usual': True, 'named': False, 'station': station, 'alternates': alternates}
    # The other bays the board names for it ("27-29"): a bus finding its bay taken stands in a free one of them.
    alternates = [{'ref': r, 'lat': known[r]['lat'], 'lon': known[r]['lon'], 'heading': known[r].get('heading')} for r in refs[1:]]
    return {**known[refs[0]], 'ref': refs[0], 'usual': usual, 'named': True, 'station': station, 'alternates': alternates}


def announces(station_id: str) -> bool:
    """Whether a station's departure board says which bay a departure leaves from."""
    return bool(STATIONS.get(station_key(station_id) or '', {}).get('board'))


def origin_area(station_id: str) -> Optional[dict]:
    """The ground of a bus station with bays, as {'latitude', 'longitude', 'radius'}: a bus there
    before its departure is waiting in its bay, wherever its GPS puts it inside; one there at the end
    of its trip has arrived and parks where it is."""
    spec = STATIONS.get(station_key(station_id) or '')
    return {'latitude': spec['lat'], 'longitude': spec['lon'], 'radius': spec['ground']} if spec else None


PARK_BAYS = 8  # bays a bus ending at a bus station may park in (or one waiting for a bay nothing names)


def least_used(station: str, known: dict, seen: Optional[Iterable] = None) -> list[str]:
    """A station's bays, those departures use least first (by the board's history; none: by number)."""
    if seen is None:
        seen = station_seen(station) or []
    used = {ref: 0 for ref in known}
    for s in seen:
        for ref in bay_refs(getattr(s, 'platform', '') or '', known):
            used[ref] += 1
    return sorted(known, key=lambda r: (used[r], int(r) if r.isdigit() else 10**6, r))


def free_bays(station: str, known: dict, towards: str, seen: Optional[Iterable] = None) -> list[str]:
    """The PARK_BAYS bays departures use least, starting at the one `towards` (the place at the trip's other end)
    always gets: the same in a trip, on any day, and on the line page's pattern, and lines don't all share one bay."""
    order = least_used(station, known, seen)[:PARK_BAYS]
    start = zlib.crc32(' '.join(sorted(_words(towards))).encode()) % len(order) if order else 0
    return order[start:] + order[:start]


def destination_bays(station_id: str, seen: Optional[Iterable] = None, towards: str = '') -> list[dict]:
    """Bays a bus ending its trip at a bus station parks in, as [{'lat', 'lon', 'heading'}]: no source says where
    buses arrive, so the PARK_BAYS bays departures use least (by the board's history), the one its line ends in first
    (`free_bays`; `towards`: where the trip came from). No numbers: the map draws the bus there, nothing names the bay."""
    station = station_key(station_id) or station_id
    known = bays(station)
    if not known:
        return []
    return [{'lat': known[r]['lat'], 'lon': known[r]['lon'], 'heading': known[r].get('heading')} for r in free_bays(station, known, towards, seen)]


def place(stops: list[dict], departure: Optional[float], destination: str) -> tuple[list[dict], Optional[dict]]:
    """Stops (a copy) with the first one moved into its bay and the last into the free bay it parks in (`parked`,
    never named: no source says where buses arrive), and the first one's bay (or None)."""
    if not stops:
        return stops, None
    out = list(stops)
    bay = bay_for(stops[0], departure, destination, stops[0].get('replacementLabel') or '')
    if bay:
        out[0] = {**stops[0], 'lat': bay['lat'], 'lon': bay['lon'], **({'bay': bay['ref'], 'bayUsual': bay['usual']} if bay.get('named', True) else {})}
    parks = destination_bays(stops[-1].get('gtfsId') or '', towards=stops[0].get('name') or '') if len(stops) > 1 else []
    if parks:
        out[-1] = {**stops[-1], 'lat': parks[0]['lat'], 'lon': parks[0]['lon'], 'parked': True}
    return out, bay


def place_leg(stops: list[dict], departure: Optional[float], first: dict, last: dict) -> tuple[list[dict], Optional[dict]]:
    """A planner's leg (`stops`: gtfsId, name, lat, lon) with its ends where `place` has them on the whole trip, whose
    first and last stops are `first` and `last`; an end the trip only calls at on its way stays on the feed's point, as
    the trip's own line does. Also the bay the leg leaves from (or None), as `place`."""
    if not stops:
        return stops, None
    out = list(stops)
    bay = None
    if first.get('gtfsId') and stops[0].get('gtfsId') == first['gtfsId']:
        bay = bay_for(first, departure, last.get('name') or '')
        if bay:
            out[0] = {**stops[0], 'lat': bay['lat'], 'lon': bay['lon']}
    if len(stops) > 1 and last.get('gtfsId') and stops[-1].get('gtfsId') == last['gtfsId']:
        parks = destination_bays(last['gtfsId'], towards=first.get('name') or '')
        if parks:
            out[-1] = {**stops[-1], 'lat': parks[0]['lat'], 'lon': parks[0]['lon'], 'parked': True}
    return out, bay

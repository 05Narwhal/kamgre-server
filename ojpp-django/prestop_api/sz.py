"""SŽ live trains: delays and (when published) positions, per train number.

SŽ publishes no GTFS-RT. derp-si's sz-platform-scraper (`/active_trains`, SŽ's own "aktivni vlaki" rows, read by
derp-si/ijpp-rt since 2026-10-19) lists running trains with their number (`St_vlaka`), category (`Rang`), next
station (`Postaja`), delay in minutes (`Zamuda_cas`) and coordinates (`Koordinate`, "lon,lat"). The older community
feed `api.modra.ninja/sz/lokacije` (`st_vlaka`, `rang_vlaka`, `naslednja_postaja`, `zamuda_min`) is read the same
way when it answers. Feeds are polled in the background only: a request never waits on them, and while all are down
trains fall back to the GTFS-RT trip updates or their timetable positions (quality "scheduled"). As soon as one
answers again, trains move by their live delay (quality "inferred") or by reported coordinates (quality "observed").

`PRESTOP_SZ_LIVE_URL` lists the feed's URLs, tried in order (upstream.Mirrors; empty turns it off).
"""
import logging
import re
import threading
import time
from typing import Any, Callable, Optional

from .mapping import fold
from .upstream import Mirrors, UpstreamError

logger = logging.getLogger(__name__)

POLL = 20            # s between polls while the feed works
FRESH = 180          # s a train's report stays usable
BACKOFF = (30, 600)  # s, doubling while the feed fails
CATEGORY = re.compile(r'^([A-Za-zŠŽČšžč]+)\s*(\d+)$')


def train_parts(route_name: str) -> tuple[Optional[str], Optional[str]]:
    """'LPV 2904' -> ('LPV', '2904'); '4292' -> (None, '4292')."""
    name = (route_name or '').strip()
    m = CATEGORY.match(name.replace(' ', '')) if name else None
    if m:
        return m.group(1).upper(), m.group(2)
    if name.isdigit():
        return None, name
    return None, None


def _number(value) -> Optional[str]:
    digits = re.sub(r'\D', '', str(value or ''))
    return digits.lstrip('0') or None


def _float(value) -> Optional[float]:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        return float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def _first(raw: dict, *keys):
    """The first of `keys` the row has a value for (feeds spell the same field differently)."""
    return next((raw[k] for k in keys if raw.get(k) not in (None, '')), None)


def _text(value) -> Optional[str]:
    return str(value).strip() or None if value not in (None, '') else None


def _coords(raw: dict) -> Optional[tuple[float, float]]:
    """(lat, lon) from whichever coordinate fields the feed uses, if they lie in Slovenia."""
    lat = _float(_first(raw, 'lat', 'latitude', 'Lat', 'sirina', 'y'))
    lon = _float(_first(raw, 'lon', 'lng', 'longitude', 'Lon', 'dolzina', 'x'))
    pair = raw.get('koordinate') or raw.get('Koordinate')
    if isinstance(pair, str):
        pair = pair.split(',')  # the scraper's "lon,lat"
    if (lat is None or lon is None) and isinstance(pair, (list, tuple)) and len(pair) >= 2:
        lon, lat = _float(pair[0]), _float(pair[1])  # SŽ lists longitude first
    if lat is None or lon is None:
        return None
    if not (45.3 < lat < 47) and 45.3 < lon < 47:
        lat, lon = lon, lat
    return (lat, lon) if 45.3 < lat < 47 and 13.3 < lon < 16.7 else None


def normalize(raw: dict, now: float) -> Optional[dict]:
    """One train row of either feed (the scraper's SŽ field names or modra.ninja's)."""
    number = _number(_first(raw, 'St_vlaka', 'st_vlaka', 'vlak', 'number'))
    if not number:
        return None
    delay = _float(_first(raw, 'Zamuda_cas', 'zamuda_min', 'zamuda'))
    track = _first(raw, 'tir', 'peron', 'track')
    return {
        'number': number,
        'category': (_text(_first(raw, 'Rang', 'rang_vlaka')) or '').upper() or None,
        'next': _text(_first(raw, 'Postaja', 'naslednja_postaja')),
        'delay': int(delay * 60) if delay is not None else None,
        'coords': _coords(raw),
        'platform': _text(track),
        'relation': _text(_first(raw, 'Relacija', 'relacija')),
        'at': now,
    }


def train_rows(data: Any) -> list:
    """The rows of a live-trains answer: a list, or modra.ninja's {'vlaki': [...]}. An empty list is a valid answer
    (no trains at 3 am); anything else is not this feed."""
    if isinstance(data, dict):
        data = data.get('vlaki') if 'vlaki' in data else data.get('trains')
    if not isinstance(data, list):
        raise ValueError('not a list of trains')
    return data


def station_key(name: str) -> str:
    """Station names compared the way the SŽ feed spells them ('Ljubljana Tivoli' ~ 'LJUBLJANA TIVOLI')."""
    return re.sub(r'[^a-z0-9]', '', fold((name or '').split('(')[0]))


class Feed:
    """One SŽ source polled in the background: `parse(json, now)` -> {key: item with 'at'}. Items stay usable for
    FRESH s; a failing source keeps them that long, then has none. `since`: when it last answered."""

    def __init__(self, setting: str, parse: Callable[[Any, float], dict], poll: float = POLL, name: str = 'sz'):
        self.mirrors = Mirrors(setting)
        self.parse = parse
        self.poll = poll
        self.name = name
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._polling = False
        self._next_poll = 0.0
        self._backoff = BACKOFF[0]
        self.last_ok: Optional[float] = None
        self.last_error: Optional[str] = None

    @property
    def url(self) -> str:
        """The URLs this feed reads ('' when off)."""
        return ','.join(self.mirrors.urls)

    @property
    def used(self) -> Optional[str]:
        """The URL that answered last."""
        return self.mirrors.good

    def get(self, now: Optional[float] = None) -> dict[str, dict]:
        """Fresh items by key. Never blocks; starts a background poll when due."""
        now = now or time.time()
        if self.url and now >= self._next_poll:
            self._poll_in_background(now)
        with self._lock:
            return {k: v for k, v in self._items.items() if now - v['at'] < FRESH}

    def _poll_in_background(self, now: float):
        with self._lock:
            if self._polling:
                return
            self._polling = True
            self._next_poll = now + self.poll
        threading.Thread(target=self._poll, daemon=True, name=self.name).start()

    def _poll(self):
        try:
            now = time.time()
            items = self.mirrors.get_json(check=lambda data: self.parse(data, now), limit=4 * 1024 * 1024, timeout=(4, 10))
            with self._lock:
                self._items.update(items)
                self._items = {k: v for k, v in self._items.items() if now - v['at'] < FRESH}
            self.last_ok, self.last_error = now, None
            self._backoff = BACKOFF[0]
        except UpstreamError as e:
            self.last_error = str(e)
            with self._lock:
                self._next_poll = time.time() + self._backoff
            if self._backoff == BACKOFF[0]:
                logger.info('%s unavailable: %r', self.name, e)
            self._backoff = min(BACKOFF[1], self._backoff * 2)
        finally:
            self._polling = False

    def status(self) -> str:
        if self.last_ok and time.time() - self.last_ok < FRESH:
            return 'live'
        return 'stale' if self.last_ok else 'unavailable'


def parse_trains(data: Any, now: float) -> dict[str, dict]:
    return {t['number']: t for t in (normalize(r, now) for r in train_rows(data) if isinstance(r, dict)) if t}


class LiveTrains(Feed):
    """SŽ's running trains by number (`PRESTOP_SZ_LIVE_URL`)."""

    def __init__(self):
        super().__init__('PRESTOP_SZ_LIVE_URL', parse_trains, POLL, 'sz-live')


live = LiveTrains()

"""SŽ live trains: delays and (when published) positions, per train number.

SŽ publishes no GTFS-RT. The community feed `api.modra.ninja/sz/lokacije` (used by
derp-si/ijpp-rt) lists running trains with their number (`st_vlaka`), category
(`rang_vlaka`), next station (`naslednja_postaja`) and delay in minutes
(`zamuda_min`), sometimes with coordinates. It has been unreachable for long
stretches, so it is polled in the background only: a request never waits on it, and
while it is down trains fall back to their timetable positions (quality
"scheduled"). As soon as it answers again, trains move by their live delay (quality
"inferred") or by reported coordinates (quality "observed").

`PRESTOP_SZ_LIVE_URL` points at the feed ('' turns it off).
"""
import logging
import re
import threading
import time
from typing import Optional

from django.conf import settings

from .mapping import fold
from .upstream import UpstreamError, get_json

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


def _coords(raw: dict) -> Optional[tuple[float, float]]:
    """(lat, lon) from whichever coordinate fields the feed uses, if they lie in Slovenia."""
    lat = next((_float(raw[k]) for k in ('lat', 'latitude', 'Lat', 'sirina', 'y') if raw.get(k) not in (None, '')), None)
    lon = next((_float(raw[k]) for k in ('lon', 'lng', 'longitude', 'Lon', 'dolzina', 'x') if raw.get(k) not in (None, '')), None)
    pair = raw.get('koordinate') or raw.get('Koordinate')
    if (lat is None or lon is None) and isinstance(pair, (list, tuple)) and len(pair) >= 2:
        lon, lat = _float(pair[0]), _float(pair[1])  # SŽ lists longitude first
    if lat is None or lon is None:
        return None
    if not (45.3 < lat < 47) and 45.3 < lon < 47:
        lat, lon = lon, lat
    return (lat, lon) if 45.3 < lat < 47 and 13.3 < lon < 16.7 else None


def normalize(raw: dict, now: float) -> Optional[dict]:
    number = _number(raw.get('st_vlaka') or raw.get('vlak') or raw.get('number'))
    if not number:
        return None
    delay = _float(raw.get('zamuda_min') if raw.get('zamuda_min') is not None else raw.get('zamuda'))
    track = raw.get('tir') or raw.get('peron') or raw.get('track')
    return {
        'number': number,
        'category': (str(raw.get('rang_vlaka') or '').strip().upper() or None),
        'next': (str(raw.get('naslednja_postaja') or '').strip() or None),
        'delay': int(delay * 60) if delay is not None else None,
        'coords': _coords(raw),
        'platform': str(track).strip() if track not in (None, '') else None,
        'at': now,
    }


def station_key(name: str) -> str:
    """Station names compared the way the SŽ feed spells them ('Ljubljana Tivoli' ~ 'LJUBLJANA TIVOLI')."""
    return re.sub(r'[^a-z0-9]', '', fold((name or '').split('(')[0]))


class LiveTrains:
    def __init__(self):
        self._trains: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._polling = False
        self._next_poll = 0.0
        self._backoff = BACKOFF[0]
        self.last_ok: Optional[float] = None
        self.last_error: Optional[str] = None

    @property
    def url(self) -> str:
        return getattr(settings, 'PRESTOP_SZ_LIVE_URL', '')

    def get(self, now: Optional[float] = None) -> dict[str, dict]:
        """Fresh reports by train number. Never blocks; starts a background poll when due."""
        now = now or time.time()
        if self.url and now >= self._next_poll:
            self._poll_in_background(now)
        with self._lock:
            return {k: v for k, v in self._trains.items() if now - v['at'] < FRESH}

    def _poll_in_background(self, now: float):
        with self._lock:
            if self._polling:
                return
            self._polling = True
            self._next_poll = now + POLL
        threading.Thread(target=self._poll, daemon=True, name='sz-live').start()

    def _poll(self):
        try:
            data = get_json(self.url, limit=4 * 1024 * 1024, timeout=(4, 10))
            items = data if isinstance(data, list) else (data.get('vlaki') or data.get('trains') or []) if isinstance(data, dict) else []
            now = time.time()
            trains = {t['number']: t for t in (normalize(r, now) for r in items if isinstance(r, dict)) if t}
            with self._lock:
                self._trains.update(trains)
                self._trains = {k: v for k, v in self._trains.items() if now - v['at'] < FRESH}
            self.last_ok, self.last_error = now, None
            self._backoff = BACKOFF[0]
        except (UpstreamError, ValueError, TypeError, AttributeError) as e:
            self.last_error = str(e)
            with self._lock:
                self._next_poll = time.time() + self._backoff
            if self._backoff == BACKOFF[0]:
                logger.info('SŽ live feed unavailable, trains use their timetable: %r', e)
            self._backoff = min(BACKOFF[1], self._backoff * 2)
        finally:
            self._polling = False

    def status(self) -> str:
        if self.last_ok and time.time() - self.last_ok < FRESH:
            return 'live'
        return 'stale' if self.last_ok else 'unavailable'


live = LiveTrains()

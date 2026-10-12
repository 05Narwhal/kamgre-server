"""Which track an SŽ train uses at a station.

No timetable carries track numbers (OTP has no `platformCode`). SŽ's station boards do ("Tir"), and
derp-si's sz-platform-scraper (gitlab.com/derp-si/sz-platform-scraper, also used by brezavta.si)
reads them for every station every few minutes and serves them per day (`train_data?date=`:
train number, IJPP stop id, track such as '3' or '6-A'). Two uses:

- Today's announced tracks, polled in the background (`PRESTOP_SZ_TRACKS_URL`, '' turns it off).
  A request never waits on it.
- Each train's usual track at each station, from that history (`data/sz_tracks.json`, rebuilt by
  `manage.py sz_tracks`): a train keeps its track from day to day, so before its track is announced
  (or while the scraper's source is down) it is shown as the usual one ("usually track 3").
  Measured 2026-10-12 over 85 days: a track the train used on at least USUAL_SHARE of its days there
  was the right one 98.5 % of the time; a train/station pair without such a track gets none.
"""
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from django.conf import settings

from .upstream import UpstreamError, get_json

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
USUAL = Path(__file__).resolve().parent / 'data' / 'sz_tracks.json'
POLL = 300            # s between polls of today's tracks
BACKOFF = (60, 1800)  # s, doubling while the scraper fails
USUAL_SHARE = 0.8     # of a train's observed days at a station
USUAL_DAYS = 3        # observed days needed before a track counts as usual


def number(route_name: str) -> Optional[str]:
    """The train number in a route name: 'LPV 2606' -> '2606', 'IC 518' -> '518'."""
    from .sz import train_parts
    return train_parts(route_name)[1]


def usual_tracks(rows: list[dict], share: float = USUAL_SHARE, days: int = USUAL_DAYS) -> dict:
    """{train: {stop id: track}} from scraper rows of several days ({'train_id', 'ijpp_id', 'platform', 'date'})."""
    seen: dict[tuple[str, str], dict[str, set]] = {}
    for r in rows:
        train, stop, track = str(r.get('train_id') or '').strip(), r.get('ijpp_id'), str(r.get('platform') or '').strip()
        if train and stop and track:
            seen.setdefault((train, stop), {}).setdefault(track, set()).add(r.get('date'))
    out: dict[str, dict[str, str]] = {}
    for (train, stop), tracks in seen.items():
        total = sum(len(d) for d in tracks.values())
        best = max(tracks, key=lambda t: (len(tracks[t]), max(tracks[t])))
        if total >= days and len(tracks[best]) >= share * total:
            out.setdefault(train, {})[stop] = best
    return out


class Tracks:
    def __init__(self):
        self._lock = threading.Lock()
        self._today: dict[str, dict[str, str]] = {}
        self._day: Optional[str] = None
        self._polling = False
        self._next_poll = 0.0
        self._backoff = BACKOFF[0]
        self._usual: dict = {'stamp': None, 'value': {}}
        self.last_ok: Optional[float] = None

    @property
    def url(self) -> str:
        return getattr(settings, 'PRESTOP_SZ_TRACKS_URL', '')

    def usual(self) -> dict:
        try:
            stamp = USUAL.stat().st_mtime
        except OSError:
            return {}
        with self._lock:
            if self._usual['stamp'] != stamp:
                try:
                    value = json.loads(USUAL.read_text(encoding='utf-8')).get('trains') or {}
                except (OSError, ValueError):
                    value = {}
                self._usual.update(stamp=stamp, value=value)
            return self._usual['value']

    def today(self, now: Optional[float] = None) -> dict:
        """Today's announced tracks {train: {stop: track}}. Never blocks; polls in the background."""
        now = now or time.time()
        day = datetime.fromtimestamp(now, LOCAL).date().isoformat()
        if self.url and now >= self._next_poll:
            self._poll_in_background(now, day)
        with self._lock:
            return self._today if self._day == day else {}

    def _poll_in_background(self, now: float, day: str):
        with self._lock:
            if self._polling:
                return
            self._polling = True
            self._next_poll = now + POLL
        threading.Thread(target=self._poll, args=(day,), daemon=True, name='sz-tracks').start()

    def _poll(self, day: str):
        try:
            data = get_json(f'{self.url}?date={day}', limit=8 * 1024 * 1024, timeout=(4, 20))
            found: dict[str, dict[str, str]] = {}
            for r in (data.get('trains') or []) if isinstance(data, dict) else []:
                train, stop, track = str(r.get('train_id') or '').strip(), r.get('ijpp_id'), str(r.get('platform') or '').strip()
                if train and stop and track:
                    found.setdefault(train, {})[stop] = track
            with self._lock:
                self._today, self._day = found, day
            self.last_ok, self._backoff = time.time(), BACKOFF[0]
        except (UpstreamError, ValueError, TypeError, AttributeError) as e:
            with self._lock:
                self._next_poll = time.time() + self._backoff
            if self._backoff == BACKOFF[0]:
                logger.info('SŽ tracks unavailable, trains show their usual track: %r', e)
            self._backoff = min(BACKOFF[1], self._backoff * 2)
        finally:
            self._polling = False

    def track(self, route_name: str, stop_id: str, when: Optional[float] = None) -> tuple[Optional[str], bool]:
        """(track, usual) of the train named `route_name` at `stop_id`, for a stop at `when` (unix time;
        announced tracks only apply on their own day); (None, False) when unknown."""
        train = number(route_name)
        if not train or not stop_id:
            return None, False
        now = time.time()
        today = self.today(now)
        if when is None or datetime.fromtimestamp(when, LOCAL).date() == datetime.fromtimestamp(now, LOCAL).date():
            announced = (today.get(train) or {}).get(stop_id)
            if announced:
                return announced, False
        usual = (self.usual().get(train) or {}).get(stop_id)
        return (usual, True) if usual else (None, False)


tracks = Tracks()

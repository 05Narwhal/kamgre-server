"""Which track an SŽ train uses at a station.

No timetable carries track numbers (OTP has no `platformCode`). SŽ's station boards do ("Tir"), and
derp-si's sz-platform-scraper (gitlab.com/derp-si/sz-platform-scraper, also used by brezavta.si)
reads them for every station every few minutes and serves them per day (`train_data?date=`:
train number, IJPP stop id, track such as '3' or '6-A'). Two uses:

- Today's announced tracks, polled in the background (`PRESTOP_SZ_TRACKS_URL`, a URL list; empty turns it off).
  A request never waits on it.
- Each train's usual track at each station, from that history (`data/sz_tracks.json`, rebuilt by
  `manage.py sz_tracks`): a train keeps its track from day to day, so before its track is announced
  (or while the scraper's source is down) it is shown as the usual one ("usually track 3").
  Measured 2026-10-12 over 85 days: a track the train used on at least USUAL_SHARE of its days there
  was the right one 98.5 % of the time; a train/station pair without such a track gets none.
- Where there is none, the track it used on at least COMMON_SHARE of its days (`common` in the same file) places the
  train on a lane in 3D and 2D (spec 2026-11-03 L2). It was right ~95.6 % of the time, too seldom to say it as text:
  it is never shown, only drawn.
- A train's last station has no departure row of its own: where its set goes on as another train (train_stays), that
  train's track is the one it stands on (always shown as usual, never announced).
"""
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .upstream import Mirrors, UpstreamError

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
USUAL = Path(__file__).resolve().parent / 'data' / 'sz_tracks.json'


def usual_file() -> Path:
    """Where each train's usual track is read from and written to: PRESTOP_SZ_USUAL_TRACKS_FILE (on the server, the
    night window's weekly rebuild, outside the deployed code), else the copy checked in with the app. A configured file
    that doesn't exist yet reads the checked-in one."""
    from django.conf import settings
    path = getattr(settings, 'PRESTOP_SZ_USUAL_TRACKS_FILE', '')
    return Path(path) if path else USUAL


def _readable_usual() -> Path:
    path = usual_file()
    return path if path.exists() else USUAL
POLL = 300            # s between polls of today's tracks
BACKOFF = (60, 1800)  # s, doubling while the scraper fails
USUAL_SHARE = 0.8     # of a train's observed days at a station
USUAL_DAYS = 3        # observed days needed before a track counts as usual
COMMON_SHARE = 0.5    # of a train's observed days: the track it is drawn on when it has no usual one (never shown)
STAMP_CHECK = 10      # s between checks whether the usual-track file changed


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


def common_tracks(rows: list[dict], share: float = COMMON_SHARE, days: int = USUAL_DAYS) -> dict:
    """{train: {stop id: track}} of the pairs `usual_tracks` leaves out where one track still has `share` of the days
    (backtested 2026-11-03: 99.3 % of pairs covered with usual ones, 95.6 % right; the extra ones ~62 %): drawn, never said."""
    usual = usual_tracks(rows)
    out: dict[str, dict[str, str]] = {}
    for train, stops in usual_tracks(rows, share, days).items():
        for stop, track in stops.items():
            if stop not in usual.get(train, {}):
                out.setdefault(train, {})[stop] = track
    return out


class Tracks:
    def __init__(self):
        self._lock = threading.Lock()
        self._today: dict[str, dict[str, str]] = {}
        self._day: Optional[str] = None
        self._polling = False
        self._next_poll = 0.0
        self._backoff = BACKOFF[0]
        self._usual: dict = {'stamp': None, 'value': {}, 'common': {}}
        self.last_ok: Optional[float] = None
        self.mirrors = Mirrors('PRESTOP_SZ_TRACKS_URL')

    @property
    def url(self) -> str:
        """The scraper's `train_data` URLs, tried in order ('' when off)."""
        return ','.join(self.mirrors.urls)

    def common(self) -> dict:
        """{train: {stop: track}} the most common track of pairs without a usual one (lane only, see the module doc)."""
        self.usual()
        return self._usual.get('common') or {}

    def usual(self) -> dict:
        # The file changes a few times a year: its stamp is checked at most every STAMP_CHECK s, not per board row.
        if time.monotonic() < self._usual.get('checked', float('-inf')) + STAMP_CHECK:
            return self._usual['value']
        try:
            source = _readable_usual()
            stamp = (str(source), source.stat().st_mtime)
        except OSError:
            return {}
        with self._lock:
            self._usual['checked'] = time.monotonic()
            if self._usual['stamp'] != stamp:
                try:
                    loaded = json.loads(source.read_text(encoding='utf-8'))
                    value, common = loaded.get('trains') or {}, loaded.get('common') or {}
                except (OSError, ValueError, AttributeError):
                    value, common = {}, {}
                self._usual.update(stamp=stamp, value=value, common=common)
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
            data = self.mirrors.get_json(f'?date={day}', check=lambda d: d['trains'], limit=8 * 1024 * 1024, timeout=(4, 20))
            found: dict[str, dict[str, str]] = {}
            for r in data if isinstance(data, list) else []:
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

    def _find(self, train: str, stop_id: str, when: Optional[float]) -> tuple[Optional[str], bool]:
        now = time.time()
        if when is None or datetime.fromtimestamp(when, LOCAL).date() == datetime.fromtimestamp(now, LOCAL).date():
            announced = (self.today(now).get(train) or {}).get(stop_id)
            if announced:
                return announced, False
        usual = (self.usual().get(train) or {}).get(stop_id)
        return (usual, True) if usual else (None, False)

    def terminus(self, route_name: str, stop_id: str, when: Optional[float] = None) -> tuple[Optional[str], bool]:
        """(track, True) of a train at its LAST station: the track of the train its set goes on as there (a learned
        'continues' stay, train_stays), whose departure the scraper reports; never announced, so always usual.
        (None, False) when the set doesn't go on or that train has no track there."""
        train = number(route_name)
        if not train or not stop_id:
            return None, False
        try:
            from prestop_statistics import train_stays
            stay = train_stays.continues_as(train)
        except Exception as e:  # noqa: BLE001 - optional: the stop stands without a track
            logger.info('Stay of %s unavailable for its last track: %r', train, e)
            return None, False
        if not stay or stay.get('kind') != 'continues' or stay.get('level') not in ('sure', 'likely'):
            return None, False
        track, _ = self._find(str(stay['to_number']), stop_id, when)
        return (track, True) if track else (None, False)

    def track(self, route_name: str, stop_id: str, when: Optional[float] = None, last: bool = False) -> tuple[Optional[str], bool]:
        """(track, usual) of the train named `route_name` at `stop_id`, for a stop at `when` (unix time;
        announced tracks only apply on their own day); (None, False) when unknown. `last`: it is the train's last stop,
        which has no departure of its own (see `terminus`)."""
        train = number(route_name)
        if not train or not stop_id:
            return None, False
        found = self._find(train, stop_id, when)
        if found[0] or not last:
            return found
        return self.terminus(route_name, stop_id, when)

    def lane(self, route_name: str, stop_id: str, when: Optional[float] = None, last: bool = False) -> Optional[str]:
        """The track to draw the train on at `stop_id` when none can be said: its most common one there (see module doc),
        at its last station that of the train it goes on as. None when unknown; callers use it only without `track`."""
        train = number(route_name)
        if not train or not stop_id:
            return None
        common = (self.common().get(train) or {}).get(stop_id)
        if common or not last:
            return common
        try:
            from prestop_statistics import train_stays
            stay = train_stays.continues_as(train)
        except Exception:  # noqa: BLE001
            return None
        if not stay or stay.get('kind') != 'continues' or stay.get('level') not in ('sure', 'likely'):
            return None
        return (self.common().get(str(stay['to_number'])) or {}).get(stop_id)


tracks = Tracks()

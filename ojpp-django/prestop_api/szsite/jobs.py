"""What the reader fetches and when (spec N-B5; the polling plan is in docs/research/2026-11-05-sz-website-reader.md).

- `live`: aktivni_vlaki every 30 s in service hours (04:30-00:30), every 2 min at night (a few trains run then too):
  every running train and SŽ bus with its delay.
- `status`: page 438 every 15 min: notices (-> sz_list.save), works, highlighted delays.
- `boards`: the BOARDS busiest stations' departure boards, one station per request, spread over 5 minutes: tracks.
  At night one every 3 min, and only while the last live list had trains.
- `sets`: the planned train set of every train (the timetable finder, one search per SET_PAIRS pair, a minute apart),
  once a service day from 01:00, or at once when no list is stored: `train_sets` {'date', 'trains'} for
  szsite/sets.py (zamudil.si fills the trains these searches do not reach).
- One job at a time, each task with its own Backoff; a challenge or an IP block holds every task back (the site is
  refusing us, not one page).

The board's station is told to the API as its IJPP stop ids: the board names it ("Ljubljana"), `StationIds` finds the
railway stops of the feed with the same name (sz.station_key), once, from one OTP stops query kept for six hours.
"""
import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from django.conf import settings

from .. import mapping, sz, sz_list
from . import parse
from .client import SOLVE_PAGE, Backoff, Client, SiteError
from .store import Store, in_service

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
BOARDS = {'42300': 'Ljubljana', '43400': 'Maribor', '43100': 'Celje', '42200': 'Zidani Most', '43300': 'Pragersko',
          '42307': 'Kranj', '42400': 'Jesenice', '42600': 'Novo mesto', '44352': 'Koper', '44009': 'Postojna'}
LIVE_EVERY, STATUS_EVERY, BOARD_EVERY = 30, 900, 30  # s; 10 boards every 30 s = each every 5 min
NIGHT_LIVE_EVERY, NIGHT_BOARD_EVERY = 120, 180  # s outside service hours
# Timetable-finder searches for the train sets: both ways along each main line between BOARDS stations (a search
# lists the trains of every connection, through trains and changes alike). Branch-line trains are not reached.
SET_PAIRS = [(a, b) for x, y in (('42300', '43400'), ('42300', '42400'), ('42300', '44352'), ('42300', '42600'))
             for a, b in ((x, y), (y, x))]
SETS_EVERY, SETS_FROM = 60, 1  # s between searches; local hour the night's run starts
STATIONS_TTL = 6 * 3600
STATIONS_RETRY = 300
RAIL_STOPS_Q = '{ stops { gtfsId name lat lon routes { gtfsId mode agency { gtfsId } } } }'


def today() -> datetime:
    return datetime.now(LOCAL)


def _json(text: str, what: str):
    try:
        return json.loads(text)
    except ValueError as e:
        raise SiteError('layout', f'{what} is not JSON') from e


class StationIds:
    """The feed's railway stop ids of a station by name (sz.station_key compares names the way SŽ spells them). The stop
    list comes from `provider()` (default: one OTP stops query), is read once and again after STATIONS_TTL; a failing
    provider keeps the old list and is tried again in STATIONS_RETRY s. Unknown names have no ids."""

    def __init__(self, provider: Optional[Callable[[], list[dict]]] = None, clock: Callable[[], float] = time.monotonic):
        self.provider = provider or self._otp
        self._clock = clock
        self._index: dict[str, list[str]] = {}
        self._due = float('-inf')
        self._lock = threading.Lock()

    @staticmethod
    def _otp() -> list[dict]:
        from ..upstream import otp
        return [s for s in mapping.build_stops(otp().query(RAIL_STOPS_Q)['stops']) if 'rail' in s['modes']]

    def ids(self, name: str) -> list[str]:
        with self._lock:
            if self._clock() >= self._due:
                try:
                    index: dict[str, list[str]] = {}
                    for s in self.provider():
                        index.setdefault(sz.station_key(s.get('name') or ''), []).append(s['id'])
                    self._index, self._due = index, self._clock() + STATIONS_TTL
                except Exception as e:  # noqa: BLE001 - OTP down: boards go without ids until the next try
                    self._due = self._clock() + STATIONS_RETRY
                    logger.warning('SŽ site: railway stops unavailable: %r', e)
            return list(self._index.get(sz.station_key(name), []))


# ---------------------------------------------------------------- one fetch each

def fetch_live(client: Client, store: Store, **_) -> dict:
    raw = client.ajax('aktivni_vlaki')
    rows = parse.active_trains(_json(raw, 'aktivni_vlaki'))
    kept, error = store.keep('active_trains', rows)
    if not kept:
        raise SiteError(error or 'layout', 'the list collapsed')
    return {'count': len(rows), 'bytes': len(raw.encode('utf-8'))}


def fetch_status(client: Client, store: Store, **_) -> dict:
    page = client.get(SOLVE_PAGE)
    found = parse.status_page(page)
    refused = None
    for job, items in (('notices', found['notices']), ('works', found['works']), ('delays', found['delays'])):
        kept, error = store.keep(job, items)
        if not kept:
            refused = refused or error
        elif job == 'notices':
            if getattr(settings, 'PRESTOP_SZ_LIST_FILE', ''):
                sz_list.save(items)
            else:
                logger.warning('SŽ site: PRESTOP_SZ_LIST_FILE is not set, the notices are not handed to the API')
    if refused:
        raise SiteError(refused, 'a list collapsed')
    return {'count': len(found['notices']), 'works': len(found['works']), 'delays': len(found['delays']),
            'bytes': len(page.encode('utf-8'))}


class Boards:
    """The departure boards of BOARDS, one station per call in turn. `job` names the board of the last call (for status)."""

    def __init__(self, ids: Optional[StationIds] = None, codes: Optional[list[str]] = None):
        self.ids = ids or StationIds()
        self.codes = codes or list(BOARDS)
        self.next = 0
        self.job = 'board'

    def __call__(self, client: Client, store: Store, code: Optional[str] = None, **_) -> dict:
        if code is None:
            code, self.next = self.codes[self.next % len(self.codes)], self.next + 1
        self.job = f'board-{code}'
        day = today().date()
        page = client.get('/odhodi-in-prihodi-na-postaji/', {'postaja': code, 'datum': day.strftime('%d.%m.%Y')})
        board = parse.departures(page)
        if board['code'] != code:
            raise SiteError('layout', f'asked for station {code}, got {board["code"]}')
        data = {'code': code, 'name': board['name'], 'date': day.isoformat(), 'ids': self.ids.ids(board['name']), 'rows': board['rows']}
        kept, error = store.keep(self.job, data, count=len(board['rows']))
        if not kept:
            raise SiteError(error or 'layout', 'the board collapsed')
        return {'count': len(board['rows']), 'bytes': len(page.encode('utf-8')), 'ids': len(data['ids'])}


def train_data(store: Store, day: str) -> list[dict]:
    """The rows `tracks.py` reads for `day` (YYYY-MM-DD): {'train_id', 'ijpp_id', 'platform'} of each departure with a
    train number and a track, once per IJPP railway stop of its station; stations whose stops are unknown add none."""
    rows = []
    for job in store.jobs('board-'):
        board = (store.load(job) or {}).get('data') or {}
        if board.get('date') != day:
            continue
        for row in board.get('rows') or []:
            if row.get('kind') == 'departure' and row.get('train') and row.get('track'):
                rows += [{'train_id': row['train'], 'ijpp_id': stop, 'platform': row['track']} for stop in board.get('ids') or []]
    return rows


class TrainSets:
    """One finder search per call through SET_PAIRS; after the last, today's {'date', 'trains': {number: {'set', 'slug'}}}
    is kept as `train_sets`. A search without trains adds nothing; a page with trains but no set starts over."""

    def __init__(self, pairs: Optional[list[tuple[str, str]]] = None):
        self.pairs = pairs or SET_PAIRS
        self.day, self.next, self.found = None, 0, {}

    def wanted(self, store: Store, wall: float) -> bool:
        """Today's list is missing, and it is after SETS_FROM (or no list of any day is stored)."""
        local = datetime.fromtimestamp(wall, LOCAL)
        data = (store.load('train_sets') or {}).get('data') or {}
        return data.get('date') != local.date().isoformat() and (local.hour >= SETS_FROM or not data)

    def __call__(self, client: Client, store: Store, **_) -> dict:
        day = today().date()
        if self.day != day:
            self.day, self.next, self.found = day, 0, {}
        a, b = self.pairs[self.next]
        page = client.get('/vozni-redi-results/', {'action': 'timetables_search', 'current-language': 'sl', 'entry-station': a,
                                                   'exit-station': b, 'departure-date': day.strftime('%d.%m.%Y')})
        try:
            sets = parse.train_sets(page)
        except SiteError:
            if 'Vlak:' in page:
                self.next = 0
                raise
            sets = {}
        for number, found in sets.items():
            self.found.setdefault(number, found)
        self.next += 1
        summary = {'count': len(sets), 'bytes': len(page.encode('utf-8')), 'search': f'{self.next}/{len(self.pairs)}'}
        if self.next >= len(self.pairs):
            self.next = 0
            kept, error = store.keep('train_sets', {'date': day.isoformat(), 'trains': self.found}, count=len(self.found))
            if not kept:
                raise SiteError(error or 'layout', 'the train sets collapsed')
            summary['trains'] = len(self.found)
        return summary


# ---------------------------------------------------------------- the schedule

class Task:
    """`night`: the interval outside service hours (None: the task rests then); `when(wall)`: a further condition."""

    def __init__(self, name: str, every: float, run: Callable[..., dict], jobs: tuple[str, ...], night: Optional[float] = None,
                 when: Optional[Callable[[float], bool]] = None):
        self.name, self.every, self.run, self.jobs, self.night, self.when = name, every, run, jobs, night, when
        self.backoff = Backoff()
        self.next_at = 0.0

    def interval(self, wall: float) -> float:
        return self.every if in_service(wall) or self.night is None else self.night

    def due(self, now: float, wall: float) -> bool:
        return (now >= self.next_at and self.backoff.due(now) and (in_service(wall) or self.night is not None)
                and (self.when is None or self.when(wall)))


# The stored jobs (what /status and /health name) each task fills; a board's job is `board-<code>`.
JOBS = {'live': ('active_trains',), 'status': ('notices', 'works', 'delays'), 'sets': ('train_sets',)}


class Loop:
    """Runs the tasks one at a time, forever (or until `stop` is set)."""

    def __init__(self, client: Client, store: Store, ids: Optional[StationIds] = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
        self.client, self.store, self.clock, self.wall = client, store, clock, wall
        self.boards = Boards(ids)
        self.sets = TrainSets()
        self.tasks = [Task('live', LIVE_EVERY, fetch_live, JOBS['live'], night=NIGHT_LIVE_EVERY),
                      Task('status', STATUS_EVERY, fetch_status, JOBS['status'], night=STATUS_EVERY),
                      Task('boards', BOARD_EVERY, self.boards, (), night=NIGHT_BOARD_EVERY, when=self._boards_wanted),
                      Task('sets', SETS_EVERY, self.sets, JOBS['sets'], night=SETS_EVERY, when=lambda wall: self.sets.wanted(self.store, wall))]

    def _boards_wanted(self, wall: float) -> bool:
        """Boards in service hours; at night only while the last live list had trains."""
        return in_service(wall) or bool((self.store.load('active_trains') or {}).get('count'))

    def step(self) -> Optional[str]:
        """Run the one task that is due first, if any; its name, or None."""
        now = self.clock()
        due = [t for t in self.tasks if t.due(now, self.wall())]
        if not due:
            return None
        task = min(due, key=lambda t: t.next_at)
        started = self.clock()
        try:
            summary = task.run(self.client, self.store)
        except SiteError as e:
            for job in task.jobs or (self.boards.job,):
                self.store.fail(job, e.kind)
            held = [task] if e.kind not in ('challenge', 'blocked') else self.tasks  # the site refuses us, not one page
            delay = max(t.backoff.failed(e.kind, self.clock()) for t in held)
            logger.warning('SŽ site %s: %s; waiting %d s', task.name, e, delay)
        except Exception as e:  # noqa: BLE001 - a bug in one job must not stop the others
            logger.exception('SŽ site %s failed: %r', task.name, e)
            for job in task.jobs or (self.boards.job,):
                self.store.fail(job, 'layout')
            task.backoff.failed('layout', self.clock())
        else:
            task.backoff.ok()
            task.next_at = started + task.interval(self.wall())
            logger.debug('SŽ site %s: %s in %.1f s', task.name, summary, self.clock() - started)
        return task.name

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            if self.step() is None:
                stop.wait(1.0)


def run_once(name: str, client: Client, store: Store, ids: Optional[StationIds] = None, code: Optional[str] = None) -> dict:
    """One fetch of a job ('live', 'status', 'boards' or 'sets': all its searches) for `manage.py szsite --once`: its
    summary plus 'seconds'. A SiteError is recorded under the job's stored names, as the loop does, then raised."""
    started = time.monotonic()
    code = code or next(iter(BOARDS))
    if name not in ('live', 'status', 'boards', 'sets'):
        raise ValueError(f'unknown job {name!r} (live, status, boards or sets)')
    try:
        if name == 'live':
            summary = fetch_live(client, store)
        elif name == 'status':
            summary = fetch_status(client, store)
        elif name == 'sets':
            sets = TrainSets()
            for _ in sets.pairs:
                summary = sets(client, store)
        else:
            summary = Boards(ids)(client, store, code=code)
    except SiteError as e:
        for job in JOBS.get(name, (f'board-{code}',)):
            store.fail(job, e.kind)
        raise
    return {**summary, 'seconds': round(time.monotonic() - started, 1)}

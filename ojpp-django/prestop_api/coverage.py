"""Which buses the app hides (spec 2026-10-22 D2): what the live feeds and the timetable say runs, against what
the API returns. The pipeline notes each item it leaves out (`note`, with the file:line that leaves it out);
the functions below compare and tally. `manage.py coverage_audit` gathers the data and prints the tables.

Board rows and vehicles are matched by trip id; a row of the same line at the same time under another feed's
trip id (LPP's suburban lines are in the IJPP feed too) counts as shown, as a copy.

D6: the collector runs the audit against its own server for a few fixed stops (`Sampler`) and keeps the counts, no
ids, for /health (`latest`) and `server:top`."""
import io
import logging
import os
import sys
import threading
import time
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

EXAMPLES = 10
COPY_SECONDS = 60  # s: a row of the same line this close to the expected time is the same run under another feed's id
SHOWN = ('shown', 'shown as copy')
# Train rows a replacement bus stands for, and the feed's buses a replacement timetable runs instead of (replacement.py).
REPLACED = ('shown as its replacement bus', 'replaced by a bus on the board', 'run by a replacement timetable')
GONE = 'left before its board was read'
# Left out rightly: nothing to draw, a copy or a bus standing between runs (D4), outside the service area; a run OTP
# lacks there (upstream, D3), or a board of the other kind for that call. /health counts any other reason as unexplained.
EXPLAINED = (GONE, 'gone before the board starts', 'no trip id', 'no trip id, a drawn vehicle', 'no trip id, no run fits',
             'no trip id, two on one run', 'no position', 'stale', 'same vehicle twice', 'abroad', 'outside the map area',
             'trip not in OTP (upstream)', 'trip not running that day in OTP (upstream)', 'OTP has the trip, not at this stop',
             'starts here', 'ends here', 'no setting down', 'no picking up')
SAMPLE_STOPS = 'Kranj AP,Radovljica,Trzin Ind. cona,Polhov Gradec'  # where buses were reported missing (spec D2)
SAMPLE_EVERY = 15 * 60  # s between the collector's samples (warm: ~40 s, ~14 s CPU, most of it the boards' replacement-bus plan)
FIRST_SAMPLE = 120      # s after the collector starts: the API warms up first
CACHE_KEY = 'prestop:coverage'


def note(drops: Optional[list], reason: str, *items) -> None:
    """Record that `items` were left out for `reason`, at the caller's file:line. Nothing without `drops`."""
    if drops is None or not items:
        return
    caller = sys._getframe(1)
    at = f'{os.path.basename(caller.f_code.co_filename)}:{caller.f_lineno}'
    drops.extend({'reason': reason, 'at': at, 'item': item} for item in items)


def feed(qualified_id: Optional[str]) -> str:
    return (qualified_id or '').split(':', 1)[0] or '?'


def trip_of(item: dict) -> Optional[str]:
    """The trip id of a noted item: a feed entity, an OTP stoptime, a board row or a timetable trip."""
    if 'vehicle' in item:
        return ((item['vehicle'] or {}).get('trip') or {}).get('tripId')
    if isinstance(item.get('trip'), dict):
        return item['trip'].get('gtfsId')
    return item.get('tripId') or item.get('id')


def drop_for(drops: list, trip_id: str) -> Optional[dict]:
    """The first note about `trip_id` (the earliest step that left it out)."""
    return next((d for d in drops if trip_of(d['item']) == trip_id), None)


# ---------------------------------------------------------------- map

def map_rows(entities: Iterable[dict], drops: list, kept: set, target: Optional[set], key) -> list[dict]:
    """One row per feed entity: drawn, or why not. `kept`: vehicle ids this code builds from the feed; `target`:
    the ids the audited API returned (None: this code is the target); `key(entity)`: the id build_vehicles gives it."""
    noted = {id(d['item']): d for d in drops}
    rows = []
    for e in entities:
        vid, trip = key(e), trip_of(e)
        d = noted.get(id(e))
        if d and target is not None and vid in target:
            status, at = 'shown', ''  # the target drew it (a bus without a trip it has followed longer than this run)
        elif d:
            status, at = d['reason'], d['at']
        elif vid in kept:
            status, at = ('shown', '') if target is None or vid in target else ('missing on target', 'target API')
        else:
            status, at = 'other', ''
        rows.append({'feed': feed(trip or vid), 'status': status, 'at': at, 'example': vid or e.get('id') or '?'})
    return rows


# ---------------------------------------------------------------- boards

def stop_time(update: dict) -> Optional[int]:
    """Epoch seconds of a stop time update's departure, else its arrival."""
    for key in ('departure', 'arrival'):
        value = (update.get(key) or {}).get('time')
        if value not in (None, '', 0, '0'):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def time_at(update: Optional[dict], stop_id: str) -> Optional[int]:
    """The update's time at `stop_id` (None: it gives none)."""
    for u in (update or {}).get('updates') or []:
        if u.get('stopId') == stop_id:
            return stop_time(u)
    return None


def upcoming(update: dict, now: float, horizon: int, count: int = 2) -> list[tuple[str, int, Optional[int]]]:
    """(stop id, time, delay) of the next `count` stops a trip update gives times for, from now to `horizon` s ahead."""
    from .mapping import update_delay
    out = []
    for u in update.get('updates') or []:
        if u.get('scheduleRelationship') in ('SKIPPED', 'NO_DATA') or not u.get('stopId'):
            continue
        at = stop_time(u)
        if at is not None and now <= at <= now + horizon:
            out.append((u['stopId'], at, update_delay(u)))
            if len(out) == count:
                break
    return out


def find_on_board(rows: Iterable[dict], trip_id: str, route_name: Optional[str], scheduled: Optional[int]) -> Optional[str]:
    """'shown' when the board lists `trip_id`, 'shown as copy' when it lists the same run under another feed's
    trip id (same line name, scheduled within COPY_SECONDS), else None."""
    from .mapping import iso
    rows = list(rows or [])
    if any(r.get('tripId') == trip_id for r in rows):
        return 'shown'
    if route_name and scheduled is not None:
        lo, hi = iso(scheduled - COPY_SECONDS), iso(scheduled + COPY_SECONDS)
        if any(r.get('routeName') == route_name and lo <= (r.get('scheduledAt') or '') <= hi and feed(r.get('tripId')) != feed(trip_id) for r in rows):
            return 'shown as copy'
    return None


def timetable_departures(patterns: Iterable[dict], stop_id: str, start: int, end: int, kind: str = 'departure') -> list[dict]:
    """The runs OTP's timetable (`stop.stoptimesForServiceDate`) has at `stop_id` from `start` to `end`, as
    {'tripId', 'routeId', 'routeName', 'at'}: picking up (setting down) there, not ending (starting) there."""
    from .mapping import is_trip_end, route_name
    out = []
    for p in patterns:
        route = (p.get('pattern') or {}).get('route') or {}
        for st in p.get('stoptimes') or []:
            trip = st.get('trip') or {}
            if kind == 'departure' and (is_trip_end(st, stop_id, 'arrivalStoptime') or st.get('pickupType') == 'NONE'):
                continue
            if kind == 'arrival' and (is_trip_end(st, stop_id, 'departureStoptime') or st.get('dropoffType') == 'NONE'):
                continue
            at = st['serviceDay'] + st['scheduledDeparture' if kind == 'departure' else 'scheduledArrival']
            if start <= at <= end:
                out.append({'tripId': trip.get('gtfsId'), 'routeId': route.get('gtfsId'), 'routeName': route_name(route), 'at': at})
    return out


def duplicates(rows: Iterable[dict]) -> list[tuple[dict, dict]]:
    """Pairs of rows of one board that are the same run twice: the same row id, or another feed's copy of a run
    (mapping.copy_of: the same line and scheduled time with alike destinations; a feed's own trips are each a bus)."""
    from .mapping import copy_of
    ids: dict = {}
    runs: dict = {}
    out = []
    for r in rows:
        first = ids.setdefault(r.get('id'), r)
        if first is not r or (first := copy_of(r, runs)) is not None:
            out.append((first, r))
    return out


def board_status(expected: dict, target_rows: Optional[list], here_rows: Optional[list], drops: list) -> tuple[str, str]:
    """(status, at) of one expected run: shown on the audited board, or the reason this code leaves it out."""
    found = find_on_board(target_rows, expected['tripId'], expected.get('routeName'), expected.get('scheduled'))
    if found:
        return found, ''
    if target_rows is None:
        return 'stop has no board', 'target API'
    # Our board first: a note can be about the run's other call here (a loop's arrival, D3: N6172 at Idrija).
    if find_on_board(here_rows, expected['tripId'], expected.get('routeName'), expected.get('scheduled')):
        return 'missing on target', 'target API'
    d = drop_for(drops, expected['tripId'])
    if d:
        return d['reason'], d['at']
    return expected.get('otp') or 'not returned by OTP for the board', 'sources._member_board'


def next_page(rows: Optional[list], limit: int, at: int) -> Optional[int]:
    """Where the app goes on from a board asked for at `at` ("Later", StationBoardPage.tsx): a full one (`limit` rows,
    sources.BOARD_MAX) from its last row's own time (a minute on when that is no later); a shorter one is the rest of
    the service day (None)."""
    if not rows or len(rows) < limit:
        return None
    from datetime import datetime
    last = int(max(datetime.fromisoformat(r.get('effectiveAt') or r['scheduledAt']) for r in rows).timestamp())
    return last if last > at else at + 60


# ---------------------------------------------------------------- report

def tally(rows: Iterable[dict], ok: tuple = SHOWN) -> tuple[dict, dict, dict]:
    """(count by status, count by (feed, status), up to EXAMPLES examples per (status, at)) of `rows`
    ({'feed', 'status', 'at', 'example'})."""
    by_status: dict = {}
    by_feed: dict = {}
    examples: dict = {}
    for r in rows:
        by_status[r['status']] = by_status.get(r['status'], 0) + 1
        by_feed[(r['feed'], r['status'])] = by_feed.get((r['feed'], r['status']), 0) + 1
        if r['status'] not in ok:
            bucket = examples.setdefault((r['status'], r['at']), [])
            if len(bucket) < EXAMPLES:
                bucket.append(r['example'])
    return by_status, by_feed, examples


def table(title: str, rows: list[dict], ok: tuple = SHOWN) -> list[str]:
    """Printable lines: totals by reason, a feed x reason table, then examples per reason with its file:line."""
    by_status, by_feed, examples = tally(rows, ok)
    missed = sum(n for s, n in by_status.items() if s not in ok)
    lines = [f'== {title}: {len(rows)} checked, {missed} not shown']
    statuses = sorted(by_status, key=lambda s: (s not in ok, -by_status[s]))
    lines += [f'   {by_status[s]:6d}  {s}' for s in statuses]
    feeds = sorted({f for f, _ in by_feed})
    if feeds and missed:
        width = max(len(f) for f in feeds)
        lines.append('   ' + ' ' * width + ''.join(f'  {s[:18]:>18}' for s in statuses))
        lines += ['   ' + f'{f:<{width}}' + ''.join(f'  {by_feed.get((f, s), 0):>18}' for s in statuses) for f in feeds]
    for (status, at), ids in sorted(examples.items(), key=lambda kv: -by_status[kv[0][0]]):
        lines.append(f'   - {status} ({at or "?"}): ' + ', '.join(ids))
    return lines


# ---------------------------------------------------------------- /health (D6)

def health_block(map_rows: Optional[list], board_rows: Optional[list], twice: Optional[list], stops: int, minutes: int, now: float) -> dict:
    """Counts only, from the audit's rows (None: that check did not run): the feed's vehicles drawn or left out by
    reason; the runs due at the stops shown or not by reason; and how many of those, plus runs listed twice, no
    EXPLAINED reason covers."""
    from .mapping import iso

    def counts(rows, ok):
        out: dict = {}
        for r in rows:
            if r['status'] not in ok:
                out[r['status']] = out.get(r['status'], 0) + 1
        return out, sum(n for s, n in out.items() if s not in EXPLAINED)
    block: dict = {'sampledAt': iso(now), 'map': None, 'boards': None}
    if map_rows is not None:
        dropped, odd = counts(map_rows, SHOWN)
        block['map'] = {'inFeed': len(map_rows), 'drawn': len(map_rows) - sum(dropped.values()), 'dropped': dropped, 'unexplained': odd}
    if board_rows is not None:
        missed, odd = counts(board_rows, SHOWN + REPLACED)
        block['boards'] = {'stops': stops, 'minutes': minutes, 'checked': len(board_rows), 'shown': len(board_rows) - sum(missed.values()),
                           'notShown': missed, 'twice': len(twice or []), 'unexplained': odd + len(twice or [])}
    block['unexplained'] = sum((block[k] or {}).get('unexplained', 0) for k in ('map', 'boards'))
    return block


def health_line(block: dict) -> str:
    """One line for the collector's log (`server:top` prints the same from /health)."""
    parts = []
    if block.get('map'):
        parts.append(f'map {block["map"]["drawn"]}/{block["map"]["inFeed"]} drawn')
    if block.get('boards'):
        b = block['boards']
        parts.append(f'boards {b["shown"]}/{b["checked"]} shown at {b["stops"]} stops, {b["minutes"]} min')
    return ' · '.join(parts + [f'{block["unexplained"]} unexplained'])


def save(block: dict) -> None:
    from django.core.cache import cache
    cache.set(CACHE_KEY, block, 3 * SAMPLE_EVERY)  # a sampler that stopped leaves /health without the block


def latest() -> Optional[dict]:
    """The collector's last sample, or None: none in the last 3 periods, or the cache is down (/health answers anyway)."""
    from django.core.cache import cache
    try:
        return cache.get(CACHE_KEY)
    except Exception as e:
        log.warning('coverage: cache unavailable: %r', e)
        return None


def run_sample() -> None:
    """The audit against this server for SAMPLE_STOPS, saved for /health; its tables with their ids are dropped, the
    log gets the counts."""
    from django.core.management import call_command
    from django.db import connection
    try:
        call_command('coverage_audit', against='local', stops=SAMPLE_STOPS, sample=0, checks='map,live,timetable', save=True, stdout=io.StringIO())
        block = latest()
        if block:
            log.info('coverage: %s', health_line(block))
    except Exception as e:  # never let the sample stop the collector
        log.warning('coverage sample failed: %r', e)
    finally:
        connection.close()  # this thread's own


class Sampler:
    """The collector's coverage sample: `poll` each loop starts `run` in a thread of its own (the polls keep their
    pace) `first` s after the start and every `every` s after, one at a time."""

    def __init__(self, first: float = FIRST_SAMPLE, every: float = SAMPLE_EVERY, run: Callable[[], None] = run_sample, now: Optional[float] = None):
        self.every, self.run = every, run
        self.next = (time.monotonic() if now is None else now) + first
        self.thread: Optional[threading.Thread] = None

    def poll(self, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        if now < self.next or (self.thread and self.thread.is_alive()):
            return False
        self.next = now + self.every
        self.thread = threading.Thread(target=self.run, name='coverage sample', daemon=True)
        self.thread.start()
        return True

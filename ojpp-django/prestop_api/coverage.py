"""Which buses the app hides (spec 2026-10-22 D2): what the live feeds and the timetable say runs, against what
the API returns. The pipeline notes each item it leaves out (`note`, with the file:line that leaves it out);
the functions below compare and tally. `manage.py coverage_audit` gathers the data and prints the tables.

Board rows and vehicles are matched by trip id; a row of the same line at the same time under another feed's
trip id (LPP's suburban lines are in the IJPP feed too) counts as shown, as a copy."""
import os
import sys
from typing import Iterable, Optional

EXAMPLES = 10
COPY_SECONDS = 60  # s: a row of the same line this close to the expected time is the same run under another feed's id
SHOWN = ('shown', 'shown as copy')
# Train rows a replacement bus stands for, and the feed's buses a replacement timetable runs instead of (replacement.py).
REPLACED = ('shown as its replacement bus', 'replaced by a bus on the board', 'run by a replacement timetable')


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
        if d:
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
    d = drop_for(drops, expected['tripId'])
    if d:
        return d['reason'], d['at']
    if find_on_board(here_rows, expected['tripId'], expected.get('routeName'), expected.get('scheduled')):
        return 'missing on target', 'target API'
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

"""Which vehicle runs which trip, and what it does in between, recorded from the vehicle positions feed.

`record` (every collector poll) writes, for each vehicle on a trip, a VehicleTrip row: the vehicle, the trip's
scheduled start and end, its stop pattern, the delay it set off with and its delay when last seen. Between two trips
of a vehicle a VehicleGap row sums up what it did (GapTracker), and RecorderDay counts how much of each day was
recorded. Rows are kept KEEP_DAYS days. stays.py learns from all three: which departure a vehicle goes on to, where
it comes from (depot or not), and whether a rider can stay on.
"""
import hashlib
import logging
import math
import time
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Optional

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from prestop_api import mapping
from prestop_statistics.models import RecorderDay, VehicleGap, VehicleTrip

logger = logging.getLogger(__name__)
KEEP_DAYS = 56     # eight weeks
MAX_GAP = 30 * 60  # s at most between the previous trip's scheduled end and this trip's start
LIVE_AGE = 10 * 60  # s: a previous trip last seen longer ago gives no live delay
RECORDER_VERSION = 2   # rows written with gaps and coverage (VehicleGap, RecorderDay)
TERMINUS_METERS = 200  # m: standing this close to the last stop is waiting at the terminus
STILL_METERS = 60      # m: moving less than this between polls is standing still
IDLE_SECONDS = 10 * 60  # s stood still in one spot: an idle spot (depots are learned from these)
MAX_OPEN = 20 * 3600   # s: a gap open longer than this (no next trip seen) is closed without one
POLL_CREDIT = 180      # s: polls further apart than this count only this much (the collector polls every 60 s)
_pruned: dict = {'day': None}


# ---------------------------------------------------------------- recording

def _span(schedule: dict) -> tuple[int, int]:
    times = schedule['bySequence'].values()
    return min(s['scheduledDeparture'] for s in times), max(s['scheduledArrival'] for s in times)


def _ordered(schedule: dict) -> list[dict]:
    return [schedule['bySequence'][k] for k in sorted(schedule['bySequence'])]


def pattern_key(schedule: dict) -> str:
    """The trip's stops in order, hashed: the same departure with other stops (a timetable change) is another one."""
    return hash_stops([(s.get('stop') or {}).get('gtfsId') or '' for s in _ordered(schedule)])


def hash_stops(stop_ids: list[str]) -> str:
    return hashlib.sha1('|'.join(stop_ids).encode()).hexdigest()[:16]


def _terminus(schedule: dict) -> Optional[tuple[float, float]]:
    last = (_ordered(schedule)[-1].get('stop') or {}) if schedule['bySequence'] else {}
    return (last['lat'], last['lon']) if last.get('lat') is not None else None


def _metres(a: tuple, b: tuple) -> float:
    kx = 111320 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * 110540, (a[1] - b[1]) * kx)


def _tz():
    from prestop_statistics.collector import LJUBLJANA
    return LJUBLJANA


class GapTracker:
    """What each vehicle does between its trips, poll by poll, in the collector's memory: from its last poll on a
    trip to its first poll on the next one. Closed gaps are written as VehicleGap rows. A collector restart loses
    the gaps in progress; those pairs then have no gap row and their origin stays unknown (see learn)."""

    def __init__(self):
        self.vehicles: dict[str, dict] = {}

    def observe(self, vehicle_id: str, trip_id: Optional[str], day: Optional[date], terminus: Optional[tuple],
                at: Optional[tuple], now: float) -> Optional[VehicleGap]:
        """One poll's report of a vehicle: on `trip_id`, or between trips (None); `at` is (lat, lon). A gap the
        vehicle has just closed by starting another trip is returned."""
        st = self.vehicles.get(vehicle_id)
        if trip_id:
            closed = None
            if st and st.get('trip') != trip_id and (st.get('trip') or st.get('gap')):
                closed = self._close(vehicle_id, st, trip_id, day, now)
            self.vehicles[vehicle_id] = {'trip': trip_id, 'day': day, 'terminus': terminus, 'last': now, 'gap': None}
            return closed
        if not st:  # first seen between trips: no known trip before
            st = self.vehicles[vehicle_id] = {'trip': None, 'day': None, 'terminus': None, 'last': now, 'gap': None}
        if st.get('gap') is None:
            st['gap'] = self._open(st, now)
        gap = st['gap']
        gap['seen'] += 1
        if at:
            if st.get('terminus'):
                d = _metres(at, st['terminus'])
                gap['far'] = max(gap['far'], d)
                if d <= TERMINUS_METERS and gap.get('prev_at') is not None:
                    gap['wait'] += now - gap['prev_at']
            still = gap.get('still')
            if still and _metres(at, still[0]) <= STILL_METERS:
                gap['still'] = (still[0], still[1], now)
            else:
                self._idle(gap)
                gap['still'] = (at, now, now)
        gap['prev_at'] = now
        st['last'] = now
        return None

    def missing(self, present: set, now: float) -> list[VehicleGap]:
        """Vehicles not in this poll: a missing poll on their gap. Gaps open longer than MAX_OPEN are closed."""
        out = []
        for vehicle_id, st in list(self.vehicles.items()):
            if vehicle_id in present:
                continue
            if st.get('gap') is None:
                st['gap'] = self._open(st, now)
            st['gap']['unseen'] += 1
            st['gap']['prev_at'] = None
            if now - st['gap']['ended'] > MAX_OPEN:
                out.append(self._close(vehicle_id, st, None, None, None))
                del self.vehicles[vehicle_id]
        return out

    @staticmethod
    def _open(st: dict, now: float) -> dict:
        return {'ended': st.get('last') or now, 'seen': 0, 'unseen': 0, 'far': 0.0, 'wait': 0.0, 'idle': [], 'still': None, 'prev_at': None}

    @staticmethod
    def _idle(gap: dict):
        still = gap.get('still')
        if still and still[2] - still[1] >= IDLE_SECONDS and len(gap['idle']) < 8:
            gap['idle'].append([round(still[0][0], 5), round(still[0][1], 5), int(still[2] - still[1])])

    def _close(self, vehicle_id: str, st: dict, next_trip: Optional[str], next_day: Optional[date], now: Optional[float]) -> VehicleGap:
        gap = st.get('gap') or self._open(st, now or time.time())
        self._idle(gap)
        day = st.get('day') or next_day or datetime.fromtimestamp(gap['ended'], _tz()).date()
        return VehicleGap(service_date=day, vehicle_id=vehicle_id, after_trip_id=st.get('trip') or '', before_trip_id=next_trip or '',
                          ended=datetime.fromtimestamp(gap['ended'], dt_timezone.utc),
                          started=datetime.fromtimestamp(now, dt_timezone.utc) if now else None,
                          terminus_wait=int(gap['wait']), max_distance=int(gap['far']), seen_polls=gap['seen'],
                          unseen_polls=gap['unseen'], idle=gap['idle'])


_tracker = GapTracker()
_coverage: dict = {'last': None}


def _covered(feeds: set, now: float):
    """This poll's seconds for the collector ('*') and for each feed that had vehicles in it (RecorderDay)."""
    last, _coverage['last'] = _coverage['last'], now
    step = int(min(now - last, POLL_CREDIT)) if last else 0
    if step <= 0:
        return
    day = datetime.fromtimestamp(now, _tz()).date()
    for feed in {'*', *feeds}:
        row, _ = RecorderDay.objects.get_or_create(day=day, feed=feed)
        RecorderDay.objects.filter(pk=row.pk).update(seconds=F('seconds') + step, polls=F('polls') + 1, version=RECORDER_VERSION)


def record(schedules, positions: list[dict], updates: dict, now: Optional[float] = None) -> dict:
    """Write who serves which trip now, what vehicles do between trips (VehicleGap) and how much of the day was
    recorded (RecorderDay). `schedules`: collector.ScheduleCache; `updates`: mapping.trip_update_index."""
    from prestop_statistics.collector import _service_days
    now = now or time.time()
    seen: dict[str, tuple] = {}
    between: dict[str, Optional[tuple]] = {}  # vehicle -> (lat, lon): in the feed without a trip ("MARPROM:")
    feeds: set = set()
    for e in positions:
        v = e.get('vehicle') or {}
        trip = v.get('trip') or {}
        trip_id = trip.get('tripId') or ''
        vehicle = (v.get('vehicle') or {}).get('id')
        source = trip_id if ':' in trip_id else e.get('id') or ''
        feed = source.split(':', 1)[0] if ':' in source else ''
        if not vehicle or not feed or now - int(v.get('timestamp') or 0) > LIVE_AGE:
            continue
        feeds.add(feed)
        pos = v.get('position') or {}
        at = (pos['latitude'], pos['longitude']) if pos.get('latitude') is not None and pos.get('longitude') is not None else None
        if ':' not in trip_id or not trip_id.split(':', 1)[1]:
            between[mapping.qualify(vehicle, feed)] = at
            continue
        seen[trip_id] = (mapping.qualify(vehicle, feed), trip, v, at)
    keys = [(t, d) for t, (_, trip, _, _) in seen.items() for d in _service_days(trip, now)]
    found = schedules.get_many(keys)
    rows = {}
    gaps: list[VehicleGap] = []
    for trip_id, (vehicle_id, trip, v, at) in seen.items():
        for day in _service_days(trip, now):
            schedule = found.get((trip_id, day))
            if schedule:
                break
        else:
            continue
        start, end = _span(schedule)
        delay = mapping.current_delay(updates.get(trip_id), v.get('stopId'), v.get('currentStopSequence'))
        first = min(schedule['bySequence']) if schedule['bySequence'] else None
        # Setting off (at its first stop or the next): the delay it started with, before the road adds any.
        sequence = v.get('currentStopSequence')
        starting = first is not None and sequence is not None and int(sequence) <= first + 1
        service_date = datetime.strptime(day, '%Y%m%d').date()
        rows[(service_date, trip_id)] = {
            'vehicle_id': vehicle_id, 'route_id': schedule['routeId'], 'block_id': schedule.get('blockId') or '',
            'start': start, 'end': end, 'delay': delay, 'start_delay': delay if starting else None, 'pattern': pattern_key(schedule)}
        closed = _tracker.observe(vehicle_id, trip_id, service_date, _terminus(schedule), at, now)
        if closed:
            gaps.append(closed)
    for vehicle_id, at in between.items():
        _tracker.observe(vehicle_id, None, None, None, at, now)
    gaps += _tracker.missing({r['vehicle_id'] for r in rows.values()} | set(between), now)
    stamp = timezone.now()
    with transaction.atomic():
        existing = {(r.service_date, r.trip_id): r for r in VehicleTrip.objects.select_for_update().filter(
            service_date__in={k[0] for k in rows}, trip_id__in={k[1] for k in rows})}
        new, changed = [], []
        for (day, trip_id), row in rows.items():
            current = existing.get((day, trip_id))
            if current:
                current.vehicle_id, current.last_seen = row['vehicle_id'], stamp
                if row['delay'] is not None:
                    current.end_delay = row['delay']
                if current.start_delay is None and row['start_delay'] is not None:
                    current.start_delay = row['start_delay']
                current.pattern, current.version = current.pattern or row['pattern'], RECORDER_VERSION
                changed.append(current)
            else:
                new.append(VehicleTrip(service_date=day, trip_id=trip_id, vehicle_id=row['vehicle_id'], route_id=row['route_id'],
                                       block_id=row['block_id'][:200], start=row['start'], end=row['end'], end_delay=row['delay'],
                                       start_delay=row['start_delay'], pattern=row['pattern'], version=RECORDER_VERSION,
                                       first_seen=stamp, last_seen=stamp))
        VehicleTrip.objects.bulk_create(new, ignore_conflicts=True)
        VehicleTrip.objects.bulk_update(changed, ['vehicle_id', 'end_delay', 'start_delay', 'pattern', 'version', 'last_seen'])
        VehicleGap.objects.bulk_create(gaps)
        _covered(feeds, now)
    return {'vehicles': len(rows), 'new': len(new), 'between': len(between), 'gaps': len(gaps), 'pruned': prune(now)}


def prune(now: Optional[float] = None) -> int:
    """Once a day: drop rows older than KEEP_DAYS."""
    from prestop_statistics.collector import LJUBLJANA
    today = datetime.fromtimestamp(now or time.time(), LJUBLJANA).date()
    if _pruned['day'] == today:
        return 0
    _pruned['day'] = today
    deleted, _ = VehicleTrip.objects.filter(service_date__lt=today - timedelta(days=KEEP_DAYS)).delete()
    deleted += VehicleGap.objects.filter(service_date__lt=today - timedelta(days=KEEP_DAYS)).delete()[0]
    return deleted


# ---------------------------------------------------------------- today

def vehicle_on(trip_id: str, today: date) -> Optional[str]:
    """The vehicle seen on a trip today (fresh), if any."""
    row = VehicleTrip.objects.filter(trip_id=trip_id, service_date=today).only('vehicle_id', 'last_seen').first()
    return row.vehicle_id if row and (timezone.now() - row.last_seen).total_seconds() <= 3 * 3600 else None

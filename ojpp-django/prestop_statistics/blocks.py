"""Which vehicle runs which trip, learned from the vehicle positions feed.

`record` (every collector poll) writes, for each vehicle on a trip, a VehicleTrip row: the vehicle, the
trip's scheduled start and end and its delay when last seen. Rows are kept KEEP_DAYS days.

`learn` reads those rows back. Once MIN_DAYS service days are recorded, each departure of a route either
continues a vehicle's previous trip (on at least SAME_SHARE of the observed days of that kind the same
vehicle came off the same departure, at most MAX_GAP before) or starts fresh from the depot. Departures are
keyed by route and scheduled start, not trip id: some feeds give a trip a new id every day.

`predict` uses that: the next trip's expected delay is the previous trip's live delay minus the layover
slack (the scheduled gap between the two), never below 0. Until MIN_DAYS days are recorded nothing is
predicted here and the planner falls back to history ("usually x late", aggregation.usual_delays).
"""
import logging
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from prestop_api import mapping
from prestop_statistics.aggregation import day_kind
from prestop_statistics.models import VehicleTrip

logger = logging.getLogger(__name__)
KEEP_DAYS = 56     # eight weeks
MIN_DAYS = 7       # service days recorded before blocks are trusted
SAME_SHARE = 0.6   # the same previous departure on at least this share of days
MAX_GAP = 30 * 60  # s between the previous trip's scheduled end and this trip's start
LIVE_AGE = 10 * 60  # s: a previous trip last seen longer ago gives no live delay
LEARN_TTL = 3600
_pruned: dict = {'day': None}
_learned: dict = {}  # (routeId, day, kind) -> (time, model)
_days: dict = {'at': 0.0, 'count': 0}


# ---------------------------------------------------------------- recording

def _span(schedule: dict) -> tuple[int, int]:
    times = schedule['bySequence'].values()
    return min(s['scheduledDeparture'] for s in times), max(s['scheduledArrival'] for s in times)


def record(schedules, positions: list[dict], updates: dict, now: Optional[float] = None) -> dict:
    """Write who serves which trip now. `schedules`: collector.ScheduleCache; `updates`: mapping.trip_update_index."""
    from prestop_statistics.collector import _service_days
    now = now or time.time()
    seen: dict[str, tuple] = {}
    for e in positions:
        v = e.get('vehicle') or {}
        trip = v.get('trip') or {}
        trip_id = trip.get('tripId')
        vehicle = (v.get('vehicle') or {}).get('id')
        if not trip_id or not vehicle or ':' not in trip_id or now - int(v.get('timestamp') or 0) > LIVE_AGE:
            continue
        seen[trip_id] = (mapping.qualify(vehicle, trip_id.split(':', 1)[0]), trip, v)
    keys = [(t, d) for t, (_, trip, _) in seen.items() for d in _service_days(trip, now)]
    found = schedules.get_many(keys)
    rows = {}
    for trip_id, (vehicle_id, trip, v) in seen.items():
        for day in _service_days(trip, now):
            schedule = found.get((trip_id, day))
            if schedule:
                break
        else:
            continue
        start, end = _span(schedule)
        delay = mapping.current_delay(updates.get(trip_id), v.get('stopId'), v.get('currentStopSequence'))
        rows[(datetime.strptime(day, '%Y%m%d').date(), trip_id)] = {
            'vehicle_id': vehicle_id, 'route_id': schedule['routeId'], 'block_id': schedule.get('blockId') or '',
            'start': start, 'end': end, 'delay': delay}
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
                changed.append(current)
            else:
                new.append(VehicleTrip(service_date=day, trip_id=trip_id, vehicle_id=row['vehicle_id'], route_id=row['route_id'],
                                       block_id=row['block_id'][:200], start=row['start'], end=row['end'], end_delay=row['delay'],
                                       first_seen=stamp, last_seen=stamp))
        VehicleTrip.objects.bulk_create(new, ignore_conflicts=True)
        VehicleTrip.objects.bulk_update(changed, ['vehicle_id', 'end_delay', 'last_seen'])
    return {'vehicles': len(rows), 'new': len(new), 'pruned': prune(now)}


def prune(now: Optional[float] = None) -> int:
    """Once a day: drop rows older than KEEP_DAYS."""
    from prestop_statistics.collector import LJUBLJANA
    today = datetime.fromtimestamp(now or time.time(), LJUBLJANA).date()
    if _pruned['day'] == today:
        return 0
    _pruned['day'] = today
    deleted, _ = VehicleTrip.objects.filter(service_date__lt=today - timedelta(days=KEEP_DAYS)).delete()
    return deleted


# ---------------------------------------------------------------- learning

def recorded_days() -> int:
    if time.monotonic() - _days['at'] > 600:
        _days.update(at=time.monotonic(), count=VehicleTrip.objects.values('service_date').distinct().count())
    return _days['count']


def learn(route_id: str, today: date, kind: Optional[str] = None) -> dict[int, dict]:
    """start -> {'samples', 'previous': {'routeId', 'start', 'end'} | None, 'share', 'slack'} for the route's departures
    on days of `kind` (default: today's) before today. Empty until MIN_DAYS days are recorded."""
    kind = kind or day_kind(today)
    key = (route_id, today, kind)
    hit = _learned.get(key)
    if hit and time.monotonic() - hit[0] < LEARN_TTL:
        return hit[1]
    model = _learn(route_id, today, kind) if recorded_days() >= MIN_DAYS else {}
    _learned[key] = (time.monotonic(), model)
    return model


def _learn(route_id: str, today: date, kind: str) -> dict[int, dict]:
    since = today - timedelta(days=KEEP_DAYS)
    own = [r for r in VehicleTrip.objects.filter(route_id=route_id, service_date__range=(since, today - timedelta(days=1)))
           .only('service_date', 'vehicle_id', 'start', 'trip_id') if day_kind(r.service_date) == kind]
    if not own:
        return {}
    runs: dict[tuple, list] = defaultdict(list)
    for r in VehicleTrip.objects.filter(vehicle_id__in={r.vehicle_id for r in own}, service_date__in={r.service_date for r in own}) \
            .only('service_date', 'vehicle_id', 'route_id', 'start', 'end', 'trip_id'):
        runs[(r.vehicle_id, r.service_date)].append(r)
    votes: dict[int, Counter] = defaultdict(Counter)
    ends: dict[tuple, list] = defaultdict(list)
    for r in own:
        before = [o for o in runs[(r.vehicle_id, r.service_date)] if o.trip_id != r.trip_id and o.end <= r.start and r.start - o.end <= MAX_GAP]
        prev = max(before, key=lambda o: o.end, default=None)
        pick = (prev.route_id, prev.start) if prev else None
        votes[r.start][pick] += 1
        if prev:
            ends[pick].append(prev.end)
    model = {}
    for start, counter in votes.items():
        samples = sum(counter.values())
        pick, n = counter.most_common(1)[0]
        share = n / samples
        if pick and share >= SAME_SHARE:
            end = sorted(ends[pick])[len(ends[pick]) // 2]
            model[start] = {'samples': samples, 'share': round(share, 2), 'slack': start - end,
                            'previous': {'routeId': pick[0], 'start': pick[1], 'end': end}}
        else:
            model[start] = {'samples': samples, 'share': round(share, 2), 'slack': None, 'previous': None}
    return model


# ---------------------------------------------------------------- predicting

def previous_run(route_id: str, start: int, today: date) -> Optional[dict]:
    """Today's run of the departure that usually comes before this one on the same vehicle:
    {'tripId', 'vehicleId', 'routeId', 'delaySeconds' (live, or None), 'slack'}; None for a fresh start or when unknown."""
    m = learn(route_id, today).get(start)
    if not m or not m['previous']:
        return None
    prev = m['previous']
    row = VehicleTrip.objects.filter(route_id=prev['routeId'], start=prev['start'], service_date=today).order_by('-last_seen').first()
    if not row:
        return {'tripId': None, 'vehicleId': None, 'routeId': prev['routeId'], 'delaySeconds': None, 'slack': m['slack']}
    fresh = (timezone.now() - row.last_seen).total_seconds() <= LIVE_AGE
    return {'tripId': row.trip_id, 'vehicleId': row.vehicle_id, 'routeId': row.route_id,
            'delaySeconds': row.end_delay if fresh else None, 'slack': m['slack']}


def predict(route_id: str, start: int, today: date) -> Optional[int]:
    """Expected delay (s) of a departure from its vehicle's previous trip, or None (no previous trip, or not running)."""
    prev = previous_run(route_id, start, today)
    if not prev or prev['delaySeconds'] is None:
        return None
    return max(0, prev['delaySeconds'] - max(0, prev['slack'] or 0))


def vehicle_on(trip_id: str, today: date) -> Optional[str]:
    """The vehicle seen on a trip today (fresh), if any."""
    row = VehicleTrip.objects.filter(trip_id=trip_id, service_date=today).only('vehicle_id', 'last_seen').first()
    return row.vehicle_id if row and (timezone.now() - row.last_seen).total_seconds() <= 3 * 3600 else None

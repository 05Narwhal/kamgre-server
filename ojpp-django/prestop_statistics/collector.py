"""Turns GTFS-RT trip updates into per-trip observed delays.

A stop's delay is recorded once its event time (scheduled + delay, or the absolute
time the provider reports) has passed. Later polls overwrite the same stop, so the
stored value is the provider's last word on it.
"""
import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from prestop_api import mapping
from prestop_api.upstream import UpstreamError, get_json, otp
from prestop_statistics.models import CollectorState, TripDelay

logger = logging.getLogger(__name__)
LJUBLJANA = ZoneInfo('Europe/Ljubljana')
MAX_UPDATE_AGE = 30 * 60
MAX_ABS_DELAY = 4 * 3600
SOURCE = 'gtfs-rt-trip-updates'


class ScheduleCache:
    """(tripId, YYYYMMDD) -> scheduled stop times, route, operator and direction."""

    CHUNK = 60

    def __init__(self):
        self._data: dict[tuple[str, str], Optional[dict]] = {}
        self.updates: dict = {}  # the last poll's trip updates (mapping.trip_update_index)

    def get_many(self, keys: list[tuple[str, str]]) -> dict[tuple[str, str], Optional[dict]]:
        missing = [k for k in dict.fromkeys(keys) if k not in self._data]
        for i in range(0, len(missing), self.CHUNK):
            self._fetch(missing[i:i + self.CHUNK])
        return {k: self._data.get(k) for k in keys}

    def _fetch(self, keys):
        fields = 'directionId blockId route { gtfsId agency { gtfsId } } stoptimesForDate(serviceDate: %s) { stopPosition scheduledArrival scheduledDeparture serviceDay stop { gtfsId lat lon } }'
        query = ' '.join(f't{i}: trip(id: {json.dumps(trip)}) {{ {fields % json.dumps(day)} }}' for i, (trip, day) in enumerate(keys))
        try:
            data = otp().query('{ ' + query + ' }')
        except UpstreamError as e:
            logger.warning('Schedule lookup failed: %r', e)
            return
        for i, key in enumerate(keys):
            t = data.get(f't{i}')
            stoptimes = (t or {}).get('stoptimesForDate') or []
            self._data[key] = {
                'routeId': t['route']['gtfsId'], 'operatorId': (t['route'].get('agency') or {}).get('gtfsId') or '',
                'direction': mapping.direction_key(t.get('directionId')), 'blockId': t.get('blockId'),
                'bySequence': {s['stopPosition']: s for s in stoptimes},
                'byStop': {s['stop']['gtfsId']: s for s in stoptimes},
            } if stoptimes else None

    def forget_before(self, day: str):
        self._data = {k: v for k, v in self._data.items() if k[1] >= day}


def _abs_time(update: dict) -> Optional[int]:
    for key in ('arrival', 'departure'):
        value = (update.get(key) or {}).get('time')
        if value:
            return int(value)
    return None


def passed_stop_delays(updates: list[dict], schedule: dict, now: float) -> dict[str, int]:
    """{stopSequence: delay} for stops whose event time has passed."""
    out = {}
    for u in updates:
        sched = schedule['bySequence'].get(u.get('stopSequence')) or schedule['byStop'].get(u.get('stopId'))
        if not sched:
            continue
        planned = sched['serviceDay'] + sched['scheduledArrival']
        delay, absolute = mapping.update_delay(u), _abs_time(u)
        if delay is None and absolute is not None:
            delay = absolute - planned
        if delay is None or abs(delay) > MAX_ABS_DELAY:
            continue
        event = absolute if absolute is not None else planned + delay
        if event <= now:
            out[str(sched['stopPosition'])] = int(delay)
    return out


MAX_SEGMENT = 3600


def segment_times(delays: dict[str, int], schedule: dict) -> dict[str, int]:
    """{"fromStop>toStop": seconds}: observed arrival-to-arrival running time between
    consecutive scheduled stops that both have a recorded delay."""
    ordered = sorted(schedule['bySequence'].values(), key=lambda s: s['stopPosition'])
    out = {}
    for a, b in zip(ordered, ordered[1:]):
        da, db = delays.get(str(a['stopPosition'])), delays.get(str(b['stopPosition']))
        if da is None or db is None:
            continue
        seconds = (b['scheduledArrival'] + db) - (a['scheduledArrival'] + da)
        if 0 < seconds <= MAX_SEGMENT:
            out[f"{a['stop']['gtfsId']}>{b['stop']['gtfsId']}"] = int(seconds)
    return out


def _service_days(trip: dict, now: float) -> list[str]:
    if trip.get('startDate'):
        return [trip['startDate']]
    today = datetime.fromtimestamp(now, LJUBLJANA).date()
    # Trips without a start date may belong to yesterday's service day after midnight.
    return [today.strftime('%Y%m%d'), (today - timedelta(days=1)).strftime('%Y%m%d')]


def collect_once(schedules: ScheduleCache, now: Optional[float] = None, entities: Optional[list] = None) -> dict:
    now = now or time.time()
    state, _ = CollectorState.objects.get_or_create(source=SOURCE)
    state.last_attempt = timezone.now()
    try:
        if entities is None:
            entities = get_json(settings.PRESTOP_RT_TRIP_UPDATES_URL, limit=48 * 1024 * 1024)
    except UpstreamError as e:
        state.last_error = str(e)[:1000]
        state.save()
        raise
    index = mapping.trip_update_index(entities)
    schedules.updates = index  # blocks.record reads the delays of the same poll
    fresh = {t: tu for t, tu in index.items() if tu['updates'] and (not tu['timestamp'] or now - tu['timestamp'] <= MAX_UPDATE_AGE)}
    keys = [(t, d) for t, tu in fresh.items() for d in _service_days(tu['trip'], now)]
    found = schedules.get_many(keys)

    rows: dict[tuple[date, str], dict] = {}
    unmatched = 0
    for trip_id, tu in fresh.items():
        for day in _service_days(tu['trip'], now):
            schedule = found.get((trip_id, day))
            if schedule:
                break
        else:
            unmatched += 1
            continue
        delays = passed_stop_delays(tu['updates'], schedule, now)
        canceled = tu['trip'].get('scheduleRelationship') == 'CANCELED'
        if delays or canceled:
            rows[(datetime.strptime(day, '%Y%m%d').date(), trip_id)] = {'schedule': schedule, 'delays': delays, 'canceled': canceled}

    created = updated = 0
    stamp = timezone.now()
    with transaction.atomic():
        existing = {(r.service_date, r.trip_id): r for r in TripDelay.objects.select_for_update().filter(
            service_date__in={k[0] for k in rows}, trip_id__in={k[1] for k in rows})}
        new, changed = [], []
        for (day, trip_id), row in rows.items():
            current = existing.get((day, trip_id))
            if current:
                merged = {**current.stop_delays, **row['delays']}
                segments = segment_times(merged, row['schedule'])
                if merged != current.stop_delays or row['canceled'] != current.canceled or segments != current.segments:
                    current.stop_delays, current.segments, current.canceled, current.last_seen = merged, segments, row['canceled'], stamp
                    changed.append(current)
            else:
                s = row['schedule']
                new.append(TripDelay(service_date=day, trip_id=trip_id, route_id=s['routeId'], operator_id=s['operatorId'],
                                     direction=s['direction'], stop_delays=row['delays'], segments=segment_times(row['delays'], s),
                                     canceled=row['canceled'], first_seen=stamp, last_seen=stamp))
        TripDelay.objects.bulk_create(new, ignore_conflicts=True)
        TripDelay.objects.bulk_update(changed, ['stop_delays', 'segments', 'canceled', 'last_seen'])
        created, updated = len(new), len(changed)

    counts = {'trips': len(fresh), 'created': created, 'updated': updated, 'unmatched': unmatched}
    state.last_success, state.last_error, state.counts = stamp, '', counts
    state.save()
    schedules.forget_before((datetime.fromtimestamp(now, LJUBLJANA).date() - timedelta(days=2)).strftime('%Y%m%d'))
    return counts

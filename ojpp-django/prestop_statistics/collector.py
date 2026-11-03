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
from prestop_statistics.models import CollectorState, TripDelay, TripStops

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
        self._kept: set[str] = set()  # trips whose stops are in TripStops (this process wrote or tried them)

    def get_many(self, keys: list[tuple[str, str]]) -> dict[tuple[str, str], Optional[dict]]:
        missing = [k for k in dict.fromkeys(keys) if k not in self._data]
        for i in range(0, len(missing), self.CHUNK):
            self._fetch(missing[i:i + self.CHUNK])
        return {k: self._data.get(k) for k in keys}

    def _fetch(self, keys):
        fields = 'directionId blockId route { gtfsId mode agency { gtfsId } } stoptimesForDate(serviceDate: %s) { stopPosition scheduledArrival scheduledDeparture serviceDay stop { gtfsId name lat lon } }'
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
        self._keep_stops([(trip, data.get(f't{i}')) for i, (trip, _) in enumerate(keys)])

    def _keep_stops(self, found: list[tuple[str, Optional[dict]]]):
        """Each trip's stops, once (TripStops): the night's bus rollup reads them to know which stop a recorded
        position is. Never fails the poll: without them a bus stop's day is only missing from the statistics."""
        rows = []
        for trip_id, t in found:
            stoptimes = (t or {}).get('stoptimesForDate') or []
            if not stoptimes or trip_id in self._kept:
                continue
            self._kept.add(trip_id)
            rows.append(TripStops(trip_id=trip_id, route_id=t['route']['gtfsId'], mode=mapping.mode_of(t['route'].get('mode')) or '',
                                  stops=[[s['stopPosition'], s['stop']['gtfsId'], s['stop'].get('name') or '', s.get('scheduledArrival')]
                                         for s in sorted(stoptimes, key=lambda s: s['stopPosition'])],
                                  seen=datetime.now(LJUBLJANA).date()))
        if not rows:
            return
        try:
            TripStops.objects.bulk_create(rows, ignore_conflicts=True)
        except Exception as e:  # noqa: BLE001 - see the docstring
            logger.warning('Trip stops not kept: %r', e)

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


MAX_EARLY_PASS = 15 * 60  # s: a vehicle at a stop earlier than this is at another visit of it (a loop), not passing it
_first_ours: dict[tuple, int] = {}  # (service date, trip) -> first stop position whose stored delay came from positions


def position_pass(schedule: dict, at: Optional[tuple], stamp: float) -> dict[str, int]:
    """{stopPosition: delay} for the scheduled stop a vehicle report `at` (lat, lon) is within dwell.NEAR of, timed
    `stamp`. The trip-updates feed leaves some passed stops out (MARPROM drops a few, LPP and city buses often start at
    the second stop), so positions fill those in. At a stop the trip visits twice, the visit planned nearest `stamp`."""
    from prestop_statistics.dwell import NEAR, _metres
    if not at or at[0] is None or at[1] is None or not schedule.get('bySequence'):
        return {}
    first = min(schedule['bySequence'])
    best = None
    for pos, s in schedule['bySequence'].items():
        stop = s.get('stop') or {}
        if stop.get('lat') is None or stop.get('lon') is None or _metres(at, (stop['lat'], stop['lon'])) > NEAR:
            continue
        # Its first stop is left, so the last report there counts (its departure); any other is reached (arrival).
        delay = int(stamp - s['serviceDay'] - (s['scheduledDeparture'] if pos == first else s['scheduledArrival']))
        if (pos != first and delay < -MAX_EARLY_PASS) or delay > MAX_ABS_DELAY:
            continue
        if best is None or abs(delay) < abs(best[1]):
            best = (pos, delay)
    return {str(best[0]): best[1]} if best else {}


def store_passes(passes: dict) -> int:
    """Write position-derived stop delays ({(service date, trip id): (schedule, {stopPosition: delay})}) into
    TripDelay where the feed gave none: a feed value always wins. A first stop keeps updating while the vehicle waits
    there (it is timed by when it leaves); other stops keep the first report (when it got there)."""
    if not passes:
        return 0
    stamp = timezone.now()
    written = 0
    with transaction.atomic():
        existing = {(r.service_date, r.trip_id): r for r in TripDelay.objects.select_for_update().filter(
            service_date__in={k[0] for k in passes}, trip_id__in={k[1] for k in passes})}
        new, changed = [], []
        for key, (schedule, delays) in passes.items():
            first = str(min(schedule['bySequence']))
            current = existing.get(key)
            known = current.stop_delays if current else {}
            add = {k: v for k, v in delays.items() if k not in known or (k == first and _first_ours.get(key) == k and known[k] != v)}
            if not add:
                continue
            if first in add:
                _first_ours[key] = first
            merged = {**known, **add}
            if current:
                current.stop_delays, current.segments, current.last_seen = merged, segment_times(merged, schedule), stamp
                changed.append(current)
            else:
                new.append(TripDelay(service_date=key[0], trip_id=key[1], route_id=schedule['routeId'], operator_id=schedule['operatorId'],
                                     direction=schedule['direction'], stop_delays=merged, segments=segment_times(merged, schedule),
                                     first_seen=stamp, last_seen=stamp))
            written += len(add)
        TripDelay.objects.bulk_create(new, ignore_conflicts=True)
        TripDelay.objects.bulk_update(changed, ['stop_delays', 'segments', 'last_seen'])
    cutoff = timezone.localdate() - timedelta(days=2)
    for key in [k for k in _first_ours if k[0] < cutoff]:
        del _first_ours[key]
    return written


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
            if _first_ours.get((day, trip_id)) in row['delays']:  # the feed now gives its first stop: the feed's wins
                del _first_ours[(day, trip_id)]
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

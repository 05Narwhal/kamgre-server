"""How long vehicles stand at their stops, from the vehicle positions feed (spec 2026-10-18 A5).

The collector polls the feed every POLL seconds (its 60 s trip-update poll is too coarse for a 20 s dwell) and
hands every report to `DwellTracker.observe`. A vehicle standing (speed under STAND_SPEED, or the feed's
STOPPED_AT where it sends no speed) within NEAR m of a stop of its trip opens a dwell there; the dwell lasts from
halfway between its last moving report and its first standing one to halfway between its last standing report and
the next one. A stop it passed between two moving reports at most THROUGH s apart was driven through: 0 s.
Feeds that send neither speed nor status give no dwells. Dwells longer than MAX_DWELL (a layover, a disruption)
are dropped.

Finished dwells are written into the trip's VehicleTrip row (`dwell`: {stopId: seconds}) by `write`, every
collector poll; learned.py learns medians from them each night.
"""
import logging
import math
import time
from datetime import date, datetime
from typing import Optional

from django.db import transaction

from prestop_statistics.models import VehicleTrip

logger = logging.getLogger(__name__)
POLL = 15           # s between position polls
NEAR = 30           # m: a report this close to a stop is at it
STAND_SPEED = 0.5   # m/s
THROUGH = 45        # s: reports either side of a stop at most this far apart, both moving: it drove through
MAX_GAP = 60        # s: half a gap up to this long counts towards a dwell
MAX_DWELL = 180     # s: longer is not a dwell
FORGET = 10 * 60    # s: a vehicle not reported this long is forgotten (its open dwell is closed)
PENDING_FOR = 15 * 60  # s: dwells of a trip whose VehicleTrip row is not written yet are kept this long


def _metres(a: tuple, b: tuple) -> float:
    kx = 111_320 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * 110_574, (a[1] - b[1]) * kx)


def standing_of(v: dict) -> Optional[bool]:
    """Whether a report shows the vehicle standing; None when the feed can't tell."""
    speed = (v.get('position') or {}).get('speed')
    if isinstance(speed, (int, float)) and 0 <= speed < 70:
        return speed < STAND_SPEED
    status = v.get('currentStatus')
    return status == 'STOPPED_AT' if status else None


class DwellTracker:
    def __init__(self):
        self.vehicles: dict[str, dict] = {}
        self.done: dict[tuple[date, str], dict[str, int]] = {}
        self._first_pending: dict[tuple[date, str], float] = {}

    def observe(self, schedules, positions: list[dict], now: Optional[float] = None) -> int:
        """Reads one poll of the positions feed; returns how many dwells were finished."""
        from prestop_statistics.collector import _service_days
        now = now or time.time()
        reports = []
        for e in positions:
            v = e.get('vehicle') or {}
            trip = v.get('trip') or {}
            trip_id = trip.get('tripId') or ''
            vehicle = (v.get('vehicle') or {}).get('id') or e.get('id')
            pos = v.get('position') or {}
            stamp = int(v.get('timestamp') or 0)
            if ':' not in trip_id or not trip_id.split(':', 1)[1] or not vehicle or pos.get('latitude') is None or now - stamp > FORGET:
                continue
            standing = standing_of(v)
            if standing is None:
                continue
            reports.append((f"{trip_id.split(':', 1)[0]}:{vehicle}", trip_id, trip, stamp, (pos['latitude'], pos.get('longitude')), standing, v.get('stopId')))
        found = schedules.get_many([(r[1], d) for r in reports for d in _service_days(r[2], now)])
        finished = 0
        for key, trip_id, trip, stamp, at, standing, next_stop in reports:
            for day in _service_days(trip, now):
                schedule = found.get((trip_id, day))
                if schedule:
                    break
            else:
                continue
            finished += self._report(key, trip_id, datetime.strptime(day, '%Y%m%d').date(), schedule, stamp, at, standing, next_stop)
        for key, st in list(self.vehicles.items()):
            if now - st['last'][0] > FORGET:
                finished += self._close(st, None)
                del self.vehicles[key]
        return finished

    def _report(self, key, trip_id, day, schedule, stamp, at, standing, next_stop) -> int:
        st = self.vehicles.get(key)
        finished = 0
        if st and (st['trip'] != trip_id or st['day'] != day):
            finished += self._close(st, None)
            st = None
        if not st:
            ordered = [schedule['bySequence'][k] for k in sorted(schedule['bySequence'])]
            stops = [((s.get('stop') or {}).get('gtfsId'), (s['stop'].get('lat'), s['stop'].get('lon'))) for s in ordered]
            st = self.vehicles[key] = {'trip': trip_id, 'day': day, 'stops': stops, 'last': None, 'open': None}
        if st['last'] and stamp <= st['last'][0]:
            return finished  # the same report again
        near = self._near(st['stops'], at)
        index = {s[0]: i for i, s in enumerate(st['stops'])}.get(next_stop)
        last = st['last']
        opened = st['open']
        if opened and (near != opened['index'] or not standing):
            finished += self._close(st, stamp)
        if near is not None and standing and not st['open']:
            st['open'] = {'index': near, 'first': stamp, 'last': stamp, 'before': last[0] if last else None}
        elif st['open'] and near == st['open']['index'] and standing:
            st['open']['last'] = stamp
        # Driven through: stops passed between two moving reports close together, with no dwell seen there.
        if last and not standing and not last[2] and index is not None and last[1] is not None and stamp - last[0] <= THROUGH:
            for i in range(last[1], index):
                stop_id = st['stops'][i][0]
                if 0 < i < len(st['stops']) - 1 and stop_id and stop_id not in self.done.get((day, trip_id), {}):
                    self.done.setdefault((day, trip_id), {})[stop_id] = 0
                    finished += 1
        st['last'] = (stamp, index, standing)
        return finished

    @staticmethod
    def _near(stops: list, at: tuple) -> Optional[int]:
        best, best_d = None, NEAR
        for i, (_, where) in enumerate(stops):
            if 0 < i < len(stops) - 1 and where[0] is not None:
                d = _metres(at, where)
                if d <= best_d:
                    best, best_d = i, d
        return best

    def _close(self, st: dict, after: Optional[int]) -> int:
        opened, st['open'] = st['open'], None
        if not opened:
            return 0
        seconds = opened['last'] - opened['first']
        if opened['before'] is not None and opened['first'] - opened['before'] <= MAX_GAP:
            seconds += (opened['first'] - opened['before']) / 2
        if after is not None and after - opened['last'] <= MAX_GAP:
            seconds += (after - opened['last']) / 2
        if seconds > MAX_DWELL:
            return 0
        stop_id = st['stops'][opened['index']][0]
        if not stop_id:
            return 0
        self.done.setdefault((st['day'], st['trip']), {})[stop_id] = int(round(seconds))
        return 1

    def write(self, now: Optional[float] = None) -> int:
        """Merges finished dwells into their trips' VehicleTrip rows; returns how many rows were updated."""
        now = now or time.time()
        if not self.done:
            return 0
        keys = list(self.done)
        with transaction.atomic():
            rows = {(r.service_date, r.trip_id): r for r in VehicleTrip.objects.select_for_update().filter(
                service_date__in={k[0] for k in keys}, trip_id__in={k[1] for k in keys})}
            changed = []
            for key in keys:
                row = rows.get(key)
                if row:
                    row.dwell = {**(row.dwell or {}), **self.done.pop(key)}
                    changed.append(row)
                    self._first_pending.pop(key, None)
                elif now - self._first_pending.setdefault(key, now) > PENDING_FOR:
                    self.done.pop(key)  # the trip was never recorded (blocks.py): drop its dwells
                    self._first_pending.pop(key)
            VehicleTrip.objects.bulk_update(changed, ['dwell'])
        return len(changed)

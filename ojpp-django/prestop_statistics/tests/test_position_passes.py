"""K8 (spec 2026-11-03): every passed stop gets a delay. The feed leaves stops out of its trip updates, so a vehicle's
position at a stop fills them in (collector.position_pass / store_passes), and a passed stop still without one shows the
delay carried from the last measured stop (views._with_carried). Patterns from three real trips of 1 Nov 2026."""
from django.test import TestCase
from django.utils import timezone

from prestop_api.views import _with_carried
from prestop_statistics import collector
from prestop_statistics.models import TripDelay

DAY = 1_793_487_600  # 2026-11-01 00:00 Europe/Ljubljana
DATE = timezone.localdate()  # store_passes forgets what it holds for service days 2 days back: never a fixed date


def schedule(n: int, loop: bool = False) -> dict:
    """n stops 2 minutes and ~1 km apart from 9:00; `loop`: the last stop is the first one again."""
    stops = [{'stopPosition': i, 'scheduledArrival': 9 * 3600 + i * 120, 'scheduledDeparture': 9 * 3600 + i * 120, 'serviceDay': DAY,
              'stop': {'gtfsId': f'X:s{i}', 'lat': 46.05 + i * 0.01, 'lon': 14.5}} for i in range(1, n + 1)]
    if loop:
        stops[-1]['stop'] = dict(stops[0]['stop'])
    return {'routeId': 'X:r', 'operatorId': 'X:o', 'direction': '0', 'bySequence': {s['stopPosition']: s for s in stops},
            'byStop': {s['stop']['gtfsId']: s for s in stops}}


def at(s: dict, pos: int, metres: float = 10) -> tuple:
    stop = s['bySequence'][pos]['stop']
    return (stop['lat'] + metres / 110_574, stop['lon'])


class PositionPassTests(TestCase):
    def test_vehicle_at_a_stop_the_feed_left_out(self):
        # LPP trip on route LPP:278b245a…: the feed had no update for stop 3; the bus was reported 10 m from it 95 s late.
        s = schedule(6)
        planned = DAY + s['bySequence'][3]['scheduledArrival']
        self.assertEqual(collector.position_pass(s, at(s, 3), planned + 95), {'3': 95})

    def test_too_far_or_unknown_position_is_no_pass(self):
        s = schedule(6)
        planned = DAY + s['bySequence'][3]['scheduledArrival']
        self.assertEqual(collector.position_pass(s, at(s, 3, metres=60), planned), {})
        self.assertEqual(collector.position_pass(s, None, planned), {})

    def test_loop_line_picks_the_visit_planned_nearest(self):
        s = schedule(10, loop=True)
        start = DAY + s['bySequence'][1]['scheduledDeparture']
        self.assertEqual(collector.position_pass(s, at(s, 1), start + 30), {'1': 30})
        end = DAY + s['bySequence'][10]['scheduledArrival']
        self.assertEqual(collector.position_pass(s, at(s, 1), end + 40), {'10': 40})

    def test_store_fills_only_what_the_feed_left_out(self):
        s = schedule(6)
        TripDelay.objects.create(service_date=DATE, trip_id='LPP:t', route_id='X:r', operator_id='X:o', direction='0',
                                 stop_delays={'1': 0, '2': 60, '4': 120}, first_seen='2026-11-01T09:00Z', last_seen='2026-11-01T09:00Z')
        self.assertEqual(collector.store_passes({(DATE, 'LPP:t'): (s, {'3': 95})}), 1)
        self.assertEqual(collector.store_passes({(DATE, 'LPP:t'): (s, {'4': 300})}), 0)  # the feed's own value wins
        row = TripDelay.objects.get(trip_id='LPP:t')
        self.assertEqual(row.stop_delays, {'1': 0, '2': 60, '3': 95, '4': 120})
        self.assertIn('X:s2>X:s3', row.segments)

    def test_first_stop_is_timed_by_when_it_leaves(self):
        # MARPROM:103381 (line 71) had no update for its first stop: the last report there (its departure) counts.
        s = schedule(19)
        key = (DATE, 'MARPROM:103381')
        dep = DAY + s['bySequence'][1]['scheduledDeparture']
        collector.store_passes({key: (s, collector.position_pass(s, at(s, 1), dep - 120))})
        collector.store_passes({key: (s, collector.position_pass(s, at(s, 1), dep + 45))})
        self.assertEqual(TripDelay.objects.get(trip_id='MARPROM:103381').stop_delays, {'1': 45})
        collector.store_passes({key: (s, collector.position_pass(s, at(s, 2), DAY + s['bySequence'][2]['scheduledArrival'] + 60))})
        collector.store_passes({key: (s, collector.position_pass(s, at(s, 2), DAY + s['bySequence'][2]['scheduledArrival'] + 90))})
        self.assertEqual(TripDelay.objects.get(trip_id='MARPROM:103381').stop_delays, {'1': 45, '2': 60})  # arrival: first report


class FirstStopLeftTests(TestCase):
    """M7: a bus parked at its first stop, still logged on to its trip, has not left. Trip IJPP:448065 of 3 Nov 2026 read
    +9 min at its first stop and 4.5 min early at its fourth; waiting there must not count as a delay until it goes."""
    KEY = (DATE, 'IJPP:parked')

    def setUp(self):
        collector._at_first.clear()

    def report(self, s, where, stamp):
        return collector.first_stop_left(self.KEY, s, collector.position_pass(s, where, stamp), where)

    def test_a_bus_that_never_leaves_records_nothing(self):
        s = schedule(6)
        dep = DAY + s['bySequence'][1]['scheduledDeparture']
        for late in (0, 600, 1800):
            self.assertEqual(self.report(s, at(s, 1), dep + late), {})

    def test_leaving_records_its_last_report_at_the_first_stop(self):
        s = schedule(6)
        dep = DAY + s['bySequence'][1]['scheduledDeparture']
        self.report(s, at(s, 1), dep + 1800)
        self.assertEqual(self.report(s, at(s, 1), dep + 1830), {})
        self.assertEqual(self.report(s, at(s, 2), DAY + s['bySequence'][2]['scheduledArrival'] + 1900), {
            '1': 1830, '2': 1900})

    def test_gps_wander_at_the_stand_is_not_leaving(self):
        s = schedule(6)
        dep = DAY + s['bySequence'][1]['scheduledDeparture']
        self.report(s, at(s, 1), dep + 60)
        self.assertEqual(self.report(s, at(s, 1, metres=100), dep + 90), {})

    def test_only_counts_once_and_other_stops_pass_through(self):
        s = schedule(6)
        dep = DAY + s['bySequence'][1]['scheduledDeparture']
        self.report(s, at(s, 1), dep + 60)
        self.assertEqual(self.report(s, at(s, 2), DAY + s['bySequence'][2]['scheduledArrival'] + 70), {'1': 60, '2': 70})
        self.assertEqual(self.report(s, at(s, 3), DAY + s['bySequence'][3]['scheduledArrival'] + 80), {'3': 80})


def stops(observed: dict, n: int) -> list[dict]:
    return [{'observedDelaySeconds': observed.get(i)} for i in range(1, n + 1)]


class CarriedDelayTests(TestCase):
    def test_train_gap_carries_the_last_measured_stop(self):
        # Train IJPP:462216: stops 1–7 and 10 recorded, 8–9 missing.
        trip = stops({1: 0, 2: 60, 3: 60, 4: 120, 5: 180, 6: 180, 7: 240, 10: 420}, 10)
        _with_carried(trip)
        self.assertEqual([s.get('carriedDelaySeconds') for s in trip], [None] * 7 + [240, 240, None])

    def test_city_bus_leading_and_middle_gaps(self):
        # MARPROM:103381: 1, 9 and 14–18 missing, 19 = −35 s. Stop 1 takes the first measured one, the rest the one before.
        observed = {i: 60 for i in range(2, 9)} | {i: 30 for i in range(10, 14)} | {19: -35}
        trip = stops(observed, 19)
        _with_carried(trip)
        carried = {i + 1: s['carriedDelaySeconds'] for i, s in enumerate(trip) if 'carriedDelaySeconds' in s}
        self.assertEqual(carried, {1: 60, 9: 60, 14: 30, 15: 30, 16: 30, 17: 30, 18: 30})

    def test_nothing_after_the_last_measured_stop_and_nothing_without_data(self):
        trip = stops({1: 0, 2: 60}, 5)
        _with_carried(trip)
        self.assertFalse(any('carriedDelaySeconds' in s for s in trip))
        empty = stops({}, 4)
        _with_carried(empty)
        self.assertFalse(any('carriedDelaySeconds' in s for s in empty))

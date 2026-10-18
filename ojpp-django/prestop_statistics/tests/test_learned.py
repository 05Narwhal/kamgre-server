"""Learned running and dwell times (spec 2026-10-18 A5): dwell.py records, learned.py learns and looks up."""
from datetime import date, datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from prestop_api import trips
from prestop_statistics import dwell, learned
from prestop_statistics.collector import LJUBLJANA
from prestop_statistics.models import LearnedTime, TripDelay, VehicleTrip
from prestop_statistics.tests.test_blocks import FakeSchedules
from prestop_statistics.tests.test_statistics import DAY, NOW

# Stops 1..5 along a street heading east, ~300 m apart (0.004° of longitude).
STOPS = [{'stopPosition': i, 'scheduledArrival': 9 * 3600 + i * 60, 'scheduledDeparture': 9 * 3600 + i * 60, 'serviceDay': DAY,
          'stop': {'gtfsId': f'LPP:s{i}', 'lat': 46.05, 'lon': 14.50 + i * 0.004}} for i in range(1, 6)]
SCHEDULE = {'routeId': 'LPP:r1', 'operatorId': 'LPP:1', 'direction': '0',
            'bySequence': {s['stopPosition']: s for s in STOPS}, 'byStop': {s['stop']['gtfsId']: s for s in STOPS}}
SCHEDULES = FakeSchedules({('LPP:t1', '20261009'): SCHEDULE})


def report(stamp, lon, speed, next_stop):
    return {'id': 'LPP:v1', 'vehicle': {'trip': {'tripId': 'LPP:t1', 'startDate': '20261009'}, 'vehicle': {'id': 'v1'}, 'timestamp': str(stamp),
                                       'position': {'latitude': 46.05, 'longitude': lon, 'speed': speed}, 'stopId': next_stop}}


class DwellRecorderTests(TestCase):
    def setUp(self):
        self.tracker = dwell.DwellTracker()
        VehicleTrip.objects.create(service_date=date(2026, 10, 9), trip_id='LPP:t1', vehicle_id='LPP:v1', route_id='LPP:r1', start=9 * 3600,
                                   end=10 * 3600, first_seen=timezone.now(), last_seen=timezone.now())

    def feed(self, *reports):
        for r in reports:
            self.tracker.observe(SCHEDULES, [r], now=int(r['vehicle']['timestamp']) + 5)

    def test_standing_at_a_stop_is_a_dwell_from_halfway_before_to_halfway_after(self):
        t = NOW
        self.feed(report(t, 14.5110, 8, 'LPP:s3'),          # moving towards stop 3 (14.512)
                  report(t + 20, 14.5120, 0, 'LPP:s3'),     # standing at it
                  report(t + 30, 14.51202, 0, 'LPP:s3'),
                  report(t + 50, 14.5135, 7, 'LPP:s4'))     # gone
        self.tracker.write(now=t + 60)
        # 10 s standing seen, plus half of the 20 s before and of the 20 s after.
        self.assertEqual(VehicleTrip.objects.get().dwell, {'LPP:s3': 30})

    def test_a_stop_passed_between_two_moving_reports_is_driven_through(self):
        t = NOW
        self.feed(report(t, 14.5110, 9, 'LPP:s3'), report(t + 30, 14.5135, 9, 'LPP:s4'))
        self.tracker.write(now=t + 60)
        self.assertEqual(VehicleTrip.objects.get().dwell, {'LPP:s3': 0})

    def test_far_apart_reports_say_nothing_and_feeds_without_speed_give_no_dwells(self):
        t = NOW
        self.feed(report(t, 14.5110, 9, 'LPP:s3'), report(t + 90, 14.5135, 9, 'LPP:s4'))
        silent = report(t + 120, 14.5160, 0, 'LPP:s5')
        silent['vehicle']['position'].pop('speed')
        self.feed(silent)
        self.tracker.write(now=t + 200)
        self.assertEqual(VehicleTrip.objects.get().dwell, {})

    def test_a_long_stand_is_a_layover_not_a_dwell(self):
        t = NOW
        self.feed(report(t, 14.5120, 0, 'LPP:s3'), report(t + 200, 14.5120, 0, 'LPP:s3'), report(t + 215, 14.5135, 7, 'LPP:s4'))
        self.tracker.write(now=t + 300)
        self.assertEqual(VehicleTrip.objects.get().dwell, {})


def delay_row(day, trip, segments, hour=8, route='LPP:r1'):
    seen = datetime(day.year, day.month, day.day, hour, 5, tzinfo=LJUBLJANA)
    return TripDelay(service_date=day, trip_id=trip, route_id=route, operator_id='LPP:1', direction='0', stop_delays={'1': 0},
                     segments=segments, first_seen=seen, last_seen=seen)


class LearnTests(TestCase):
    TODAY = date(2026, 10, 16)  # a Friday: the workdays before it are the 9th-15th less the weekend

    def test_medians_per_kind_of_day_and_hour_band_with_a_sample_gate_and_back_off(self):
        rows = []
        for n in range(1, 15):
            day = self.TODAY - timedelta(days=n)
            if learned.day_kind(day) != 'workday':
                continue
            # The morning peak is slow (120 s), the middle of the day quick (60 s); one segment is too rare to learn.
            # Three trips in each band a day: enough for a band of its own (MIN_FINE_SAMPLES) over ten workdays.
            rows += [delay_row(day, f'am{n}-{k}', {'LPP:s1>LPP:s2': 120}, hour=7) for k in range(3)]
            rows += [delay_row(day, f'day{n}-{k}', {'LPP:s1>LPP:s2': 60}, hour=11) for k in range(3)]
            if n == 1:
                rows.append(delay_row(day, 'rare', {'LPP:s2>LPP:s3': 90}, hour=7))
        TripDelay.objects.bulk_create(rows)
        VehicleTrip.objects.bulk_create([VehicleTrip(service_date=self.TODAY - timedelta(days=n), trip_id=f'v{n}', vehicle_id='v', route_id='LPP:r1',
                                                     start=7 * 3600, end=8 * 3600, first_seen=timezone.now(), last_seen=timezone.now(),
                                                     dwell={'LPP:s2': 20 if n % 3 else 0, 'LPP:s3': 0}) for n in range(1, 11)])
        counts = learned.learn(self.TODAY)
        self.assertGreater(counts['rows'], 0)
        learned._memo.clear()
        segments, dwells = learned.lookup('LPP:r1', 'workday', 7)
        self.assertEqual(segments, {'LPP:s1>LPP:s2': 120})
        self.assertEqual(learned.lookup('LPP:r1', 'workday', 12)[0], {'LPP:s1>LPP:s2': 60})
        # No Saturday data: the route's median over everything.
        self.assertEqual(learned.lookup('LPP:r1', 'saturday', 7)[0], {'LPP:s1>LPP:s2': 90})
        # Stop 2: stood 20 s on two trips in three (on the eight workdays a mean of 15 s); stop 3: always driven through.
        self.assertEqual(learned.dwell_seconds(dwells['LPP:s2']), 15)
        self.assertEqual(learned.dwell_seconds(dwells['LPP:s3']), 0)
        self.assertIsNone(learned.dwell_seconds(dwells.get('LPP:s4')))

    def test_the_table_is_replaced_each_night(self):
        LearnedTime.objects.create(route_id='old', kind='*', band='*', segments={'a>b': [1, 1, 1, 9]}, learned_on=self.TODAY - timedelta(days=1))
        learned.learn(self.TODAY)
        self.assertFalse(LearnedTime.objects.filter(route_id='old').exists())

    def test_bands(self):
        self.assertEqual([learned.band(h) for h in (0, 5, 6, 8, 9, 13, 14, 17, 18, 23, 25)], ['night', 'night', 'am', 'am', 'day', 'day', 'pm', 'pm', 'eve', 'eve', 'night'])

    def test_the_nightly_run_starts_once_after_its_hour_under_nice(self):
        from unittest import mock
        learned._nightly.update(day=None, process=None)
        early = datetime(2026, 10, 16, 4, 0, tzinfo=LJUBLJANA).timestamp()
        late = datetime(2026, 10, 16, 5, 0, tzinfo=LJUBLJANA).timestamp()
        with mock.patch('subprocess.Popen') as popen:
            self.assertIsNone(learned.nightly(early))
            self.assertEqual(learned.nightly(late), {'learnTimes': 'started'})
            self.assertEqual(popen.call_args[0][0][:3], ['nice', '-n', '10'])
            popen.return_value.poll.return_value = 0
            self.assertEqual(learned.nightly(late + 60), {'learnTimes': 'done'})
            self.assertIsNone(learned.nightly(late + 120))
        self.assertEqual(popen.call_count, 1)


class TripDwellTests(TestCase):
    def test_trip_stops_carry_their_learned_dwell(self):
        static = {'id': 'LPP:t1', 'routeId': 'LPP:r1', 'routeName': '1', 'operatorId': 'LPP:1', 'mode': 'bus', 'color': None, 'destination': 'X',
                  'directionId': '0', 'patternId': 'p', 'length': 600, 'geometry': [[14.5, 46.05], [14.51, 46.05]],
                  'stops': [{'stopId': f'LPP:s{i}', 'name': f's{i}', 'latitude': 46.05, 'longitude': 14.5 + i * 0.004, 'distance': i * 300.0, 'position': i} for i in (1, 2, 3)]}
        times = [{'stopPosition': i, 'serviceDay': DAY, 'scheduledArrival': 9 * 3600 + i * 60, 'scheduledDeparture': 9 * 3600 + i * 60} for i in (1, 2, 3)]
        trip = trips.build_trip({'static': static, 'times': times, 'serviceDate': date(2026, 10, 9)}, {}, dwells={'LPP:s2': [22.0, 0.9, 40], 'LPP:s3': [3.0, 0.1, 40]})
        self.assertEqual([s['dwellSeconds'] for s in trip['stops']], [None, 22.0, 0.0])

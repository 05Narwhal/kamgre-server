from datetime import date
from unittest import mock

from django.test import TestCase

from prestop_statistics import collector
from prestop_statistics.aggregation import daily_statistics, summarize
from prestop_statistics.models import TripDelay

DAY = 1791496800  # 2026-10-09 00:00 Europe/Ljubljana
NOW = DAY + 10 * 3600


def schedule(route='IJPP:r1', direction='0'):
    stops = [{'stopPosition': i, 'scheduledArrival': 9 * 3600 + i * 600, 'scheduledDeparture': 9 * 3600 + i * 600,
              'serviceDay': DAY, 'stop': {'gtfsId': f'IJPP:s{i}'}} for i in range(1, 7)]
    return {'routeId': route, 'operatorId': 'IJPP:1123', 'direction': direction,
            'bySequence': {s['stopPosition']: s for s in stops}, 'byStop': {s['stop']['gtfsId']: s for s in stops}}


def update(trip, delays, start_date='20261009'):
    return {'tripUpdate': {'trip': {'tripId': trip, 'startDate': start_date}, 'timestamp': str(NOW - 30),
                           'stopTimeUpdate': [{'stopSequence': seq, 'arrival': {'delay': d}} for seq, d in delays.items()]}}


class CollectorTests(TestCase):
    def test_only_passed_stops_are_recorded(self):
        # Stops 1 and 2 were due at 09:10 and 09:20; stop 6 is due at 10:00 plus an hour of delay.
        updates = [{'stopSequence': 1, 'arrival': {'delay': 30}}, {'stopSequence': 2, 'arrival': {'delay': 90}},
                   {'stopSequence': 6, 'arrival': {'delay': 3600}}]
        self.assertEqual(collector.passed_stop_delays(updates, schedule(), NOW), {'1': 30, '2': 90})

    def test_absolute_times_without_delay_are_converted(self):
        updates = [{'stopSequence': 1, 'arrival': {'time': str(DAY + 9 * 3600 + 600 + 45)}}]
        self.assertEqual(collector.passed_stop_delays(updates, schedule(), NOW), {'1': 45})

    def test_repeated_polls_keep_one_row_per_trip_and_day(self):
        cache = collector.ScheduleCache()
        cache._data[('IJPP:t1', '20261009')] = schedule()
        with mock.patch('prestop_statistics.collector.otp'):
            for delay in (60, 60, 120):
                counts = collector.collect_once(cache, now=NOW, entities=[update('IJPP:t1', {1: delay, 2: delay})])
        row = TripDelay.objects.get()
        self.assertEqual((row.service_date, row.route_id, row.direction, row.stop_delays),
                         (date(2026, 10, 9), 'IJPP:r1', '0', {'1': 120, '2': 120}))
        self.assertEqual(counts['updated'], 1)

    def test_stale_and_unmatched_updates_are_skipped(self):
        cache = collector.ScheduleCache()
        cache._data[('IJPP:gone', '20261009')] = None
        old = update('IJPP:old', {1: 60})
        old['tripUpdate']['timestamp'] = str(NOW - 7200)
        with mock.patch('prestop_statistics.collector.otp'):
            counts = collector.collect_once(cache, now=NOW, entities=[old, update('IJPP:gone', {1: 60})])
        self.assertEqual((counts['trips'], counts['unmatched'], TripDelay.objects.count()), (1, 1, 0))


class AggregationTests(TestCase):
    def test_trips_weigh_equally(self):
        self.assertEqual(summarize([[60, 180], [0]]), {'meanSignedDelaySeconds': 60.0, 'meanLateSeconds': 60.0,
                                                       'p95LateSeconds': 120.0, 'tripCount': 2, 'eventCount': 3})

    def test_early_running_counts_as_zero_late(self):
        self.assertEqual(summarize([[-120, 0]])['meanLateSeconds'], 0)
        self.assertEqual(summarize([[-120, 0]])['meanSignedDelaySeconds'], -60)

    def test_days_report_available_no_data_no_service_and_unknown(self):
        for trip, delays in (('a', {'1': 60, '2': 180}), ('b', {'1': 0})):
            TripDelay.objects.create(service_date=date(2026, 10, 9), trip_id=trip, route_id='IJPP:r1', operator_id='IJPP:1123',
                                     direction='0', stop_delays=delays, first_seen='2026-10-09T10:00Z', last_seen='2026-10-09T10:00Z')
        scheduled = {(date(2026, 10, 9), '0'): 4, (date(2026, 10, 10), '0'): 3, (date(2026, 10, 11), '0'): 0}
        days = daily_statistics('IJPP:r1', date(2026, 10, 8), date(2026, 10, 11), '0', 'observed', scheduled)
        self.assertEqual([d['status'] for d in days], ['no_data', 'available', 'no_data', 'no_service'])
        self.assertEqual((days[0]['scheduledTripCount'], days[0]['coverage']), (None, None))  # before the timetable window
        self.assertEqual((days[1]['meanLateSeconds'], days[1]['tripCount'], days[1]['coverage']), (60.0, 2, 0.5))
        self.assertIsNone(days[2]['meanLateSeconds'])
        predicted = daily_statistics('IJPP:r1', date(2026, 10, 9), date(2026, 10, 9), '0', 'predicted', scheduled)
        self.assertEqual(predicted[0]['status'], 'no_data')


class SegmentTests(TestCase):
    def test_running_times_between_consecutive_recorded_stops(self):
        # Scheduled 10 min apart; delay grows 60 s from stop 1 to 2, nothing recorded at 4.
        segments = collector.segment_times({'1': 30, '2': 90, '3': 90, '5': 0}, schedule())
        self.assertEqual(segments, {'IJPP:s1>IJPP:s2': 660, 'IJPP:s2>IJPP:s3': 600})

    def test_collector_stores_segments_and_typical_times_use_the_median(self):
        from prestop_statistics.aggregation import typical_segments
        cache = collector.ScheduleCache()
        for i, extra in enumerate((0, 30, 300)):
            cache._data[(f'IJPP:t{i}', '20261009')] = schedule()
            with mock.patch('prestop_statistics.collector.otp'):
                collector.collect_once(cache, now=NOW, entities=[update(f'IJPP:t{i}', {1: 0, 2: extra})])
        self.assertEqual(TripDelay.objects.get(trip_id='IJPP:t1').segments, {'IJPP:s1>IJPP:s2': 630})
        self.assertEqual(typical_segments('IJPP:r1', date(2026, 10, 9)), {'IJPP:s1>IJPP:s2': 630.0})


class ReliabilityTests(TestCase):
    def test_on_time_share_and_hours(self):
        from datetime import datetime, timezone
        from prestop_statistics.aggregation import route_reliability
        seen = datetime(2026, 10, 9, 6, 15, tzinfo=timezone.utc)  # 08:15 in Ljubljana
        for i, delays in enumerate(([60, 120], [400, 500], [0])):
            TripDelay.objects.create(service_date=date(2026, 10, 9), trip_id=f'IJPP:t{i}', route_id='IJPP:r1', operator_id='IJPP:1123',
                                     direction='0', stop_delays={str(n): d for n, d in enumerate(delays)}, first_seen=seen, last_seen=seen)
        result = route_reliability('IJPP:r1', date(2026, 10, 9))
        self.assertEqual(result['tripCount'], 3)
        self.assertAlmostEqual(result['onTimeShare'], 2 / 3, places=3)
        self.assertEqual(result['byHour'], [{'hour': 8, 'meanSignedDelaySeconds': 180.0, 'tripCount': 3}])

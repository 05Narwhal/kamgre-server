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
        self.assertEqual(result['byHour'], [{'hour': 8, 'meanSignedDelaySeconds': 180.0, 'tripCount': 3, 'medianDelaySeconds': 90.0}])

    def test_by_departure_day_and_hour(self):
        """Contract 5: a late 07:10 and an on-time 15:00 departure over twelve days (Saturdays are another kind of day)."""
        from datetime import datetime, timedelta, timezone
        from prestop_statistics import aggregation
        today = date(2026, 10, 9)  # a Friday
        seen = datetime(2026, 10, 9, 5, 15, tzinfo=timezone.utc)
        n = 0
        for back in range(12):
            day = today - timedelta(days=back)
            if day.weekday() == 6:
                continue
            for trip, delays in (('IJPP:t710', [200 + 20 * back, 300]), ('IJPP:t1500', [0, 60])):
                n += 1
                TripDelay.objects.create(service_date=day, trip_id=trip, route_id='IJPP:r1', operator_id='IJPP:1123', direction='0',
                                         stop_delays={str(i): d for i, d in enumerate(delays)}, first_seen=seen, last_seen=seen)
        aggregation._starts.clear()
        otp = mock.Mock()
        otp.query.side_effect = lambda q: {f't{i}': {'departureStoptime': {'scheduledDeparture': {'IJPP:t710': 7 * 3600 + 600, 'IJPP:t1500': 15 * 3600}[t]}}
                                           for i, t in enumerate(['IJPP:t710', 'IJPP:t1500'] if q.index('t710') < q.index('t1500') else ['IJPP:t1500', 'IJPP:t710'])}
        with mock.patch('prestop_api.upstream.otp', return_value=otp):
            result = aggregation.route_reliability('IJPP:r1', today)
            usual = aggregation.usual_delays('IJPP:r1', today)
        early = result['byDeparture'][0]
        # Ten workdays in the window (the two Saturdays are another kind of day).
        self.assertEqual((early['start'], early['samples']), ('07:10', 10))
        self.assertEqual(early['medianDelaySeconds'], fmean_of([250 + 10 * b for b in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)]))
        self.assertEqual(result['byDeparture'][1]['onTimeShare'], 1.0)
        self.assertEqual(set(usual), {'07:10', '15:00'})
        self.assertEqual([h['hour'] for h in result['byHour']], [7, 15])
        self.assertEqual(len(result['byDay']), 30)
        self.assertEqual(result['byDay'][-1], {'date': '2026-10-09', 'samples': 2, 'medianDelaySeconds': 140.0, 'onTimeShare': 0.5})
        self.assertEqual(result['byDay'][-6]['samples'], 0)  # Sunday 2026-10-04: nothing observed
        self.assertIsNone(result['byDay'][-6]['medianDelaySeconds'])
        self.assertEqual(aggregation.day_kind(date(2026, 11, 1)), 'sunday')  # a holiday on a Sunday
        self.assertEqual(aggregation.day_kind(date(2026, 12, 25)), 'sunday')  # Christmas, a Friday
        self.assertEqual(aggregation.day_kind(date(2026, 10, 10)), 'saturday')


def fmean_of(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    return float(ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2)

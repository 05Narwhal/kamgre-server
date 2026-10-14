"""Which vehicle runs which trip: recording from the vehicle feed, learning blocks, predicting from the previous trip."""
from datetime import date, datetime, timedelta, timezone as tz

from django.test import TestCase
from django.utils import timezone

from prestop_statistics import blocks
from prestop_statistics.models import VehicleTrip
from prestop_statistics.tests.test_statistics import DAY, NOW, schedule

TODAY = date(2026, 10, 9)  # a Friday
H = 3600


class FakeSchedules:
    def __init__(self, found):
        self.found = found

    def get_many(self, keys):
        return {k: self.found.get(k) for k in keys}


def run(day, trip, vehicle, route, start, end, delay=None, seen=None):
    seen = seen or timezone.now()
    return VehicleTrip.objects.create(service_date=day, trip_id=trip, vehicle_id=vehicle, route_id=route, start=start, end=end,
                                      end_delay=delay, first_seen=seen, last_seen=seen)


class RecordTests(TestCase):
    def setUp(self):
        blocks._pruned['day'] = None

    def test_a_vehicle_on_a_trip_is_recorded_and_its_delay_kept_up_to_date(self):
        found = {('IJPP:t1', '20261009'): {**schedule(), 'blockId': 'B7'}}
        position = {'vehicle': {'trip': {'tripId': 'IJPP:t1', 'startDate': '20261009'}, 'vehicle': {'id': '1234'},
                                'timestamp': str(NOW - 20), 'stopId': 'IJPP:s3', 'currentStopSequence': 3}}
        updates = {'IJPP:t1': {'updates': [{'stopId': 'IJPP:s3', 'stopSequence': 3, 'arrival': {'delay': 120}}], 'timestamp': NOW, 'trip': {}}}
        counts = blocks.record(FakeSchedules(found), [position], updates, now=NOW)
        self.assertEqual((counts['vehicles'], counts['new']), (1, 1))
        row = VehicleTrip.objects.get()
        self.assertEqual((row.vehicle_id, row.route_id, row.block_id, row.start, row.end, row.end_delay),
                         ('IJPP:1234', 'IJPP:r1', 'B7', 9 * H + 600, 10 * H, 120))
        updates['IJPP:t1']['updates'][0]['arrival']['delay'] = 300
        blocks.record(FakeSchedules(found), [position], updates, now=NOW + 60)
        self.assertEqual(VehicleTrip.objects.get().end_delay, 300)

    def test_rows_older_than_eight_weeks_are_pruned_once_a_day(self):
        run(TODAY - timedelta(days=57), 'IJPP:old', 'IJPP:v', 'IJPP:r', 0, 60)
        run(TODAY - timedelta(days=55), 'IJPP:kept', 'IJPP:v', 'IJPP:r', 0, 60)
        self.assertEqual(blocks.prune(DAY + 12 * H), 1)
        self.assertEqual(blocks.prune(DAY + 13 * H), 0)
        self.assertEqual(list(VehicleTrip.objects.values_list('trip_id', flat=True)), ['IJPP:kept'])


class LearnTests(TestCase):
    """Line B's 07:50 is the bus that has just done line A's 07:00 (ends 07:40), on most workdays."""

    def setUp(self):
        blocks._learned.clear()
        blocks._days['at'] = 0.0

    def history(self, days, other_vehicle_on=()):
        n = 0
        day = TODAY
        while n < days:
            day -= timedelta(days=1)
            if day.weekday() >= 5:
                continue
            n += 1
            vehicle = 'IJPP:other' if n in other_vehicle_on else 'IJPP:v1'
            run(day, f'IJPP:a-{day}', 'IJPP:v1', 'IJPP:A', 7 * H, 7 * H + 40 * 60)
            run(day, f'IJPP:b-{day}', vehicle, 'IJPP:B', 7 * H + 50 * 60, 8 * H + 30 * 60)

    def test_nothing_is_learned_before_seven_days(self):
        self.history(6)
        self.assertEqual(blocks.learn('IJPP:B', TODAY), {})

    def test_a_departure_that_usually_follows_another_one_and_its_predicted_delay(self):
        self.history(10, other_vehicle_on=(3, 7))  # 8 of 10 days: 80 %
        m = blocks.learn('IJPP:B', TODAY)[7 * H + 50 * 60]
        self.assertEqual((m['samples'], m['share'], m['slack']), (10, 0.8, 600))
        self.assertEqual(m['previous'], {'routeId': 'IJPP:A', 'start': 7 * H, 'end': 7 * H + 40 * 60})
        self.assertIsNone(blocks.learn('IJPP:A', TODAY)[7 * H]['previous'])  # line A's bus comes from the depot
        # Today line A's 07:00 runs 15 min late: 10 of them are taken up by the layover.
        run(TODAY, 'IJPP:a-today', 'IJPP:v1', 'IJPP:A', 7 * H, 7 * H + 40 * 60, delay=900)
        self.assertEqual(blocks.predict('IJPP:B', 7 * H + 50 * 60, TODAY), 300)
        VehicleTrip.objects.filter(trip_id='IJPP:a-today').update(end_delay=420)
        blocks._learned.clear()
        self.assertEqual(blocks.predict('IJPP:B', 7 * H + 50 * 60, TODAY), 0)  # never below 0
        self.assertEqual(blocks.previous_run('IJPP:B', 7 * H + 50 * 60, TODAY)['vehicleId'], 'IJPP:v1')

    def test_under_sixty_percent_the_same_counts_as_a_fresh_start(self):
        self.history(10, other_vehicle_on=(1, 2, 3, 4, 5))
        self.assertIsNone(blocks.learn('IJPP:B', TODAY)[7 * H + 50 * 60]['previous'])

    def test_a_previous_trip_not_seen_lately_gives_no_live_delay(self):
        self.history(8)
        run(TODAY, 'IJPP:a-today', 'IJPP:v1', 'IJPP:A', 7 * H, 7 * H + 40 * 60, delay=900, seen=timezone.now() - timedelta(hours=1))
        self.assertIsNone(blocks.predict('IJPP:B', 7 * H + 50 * 60, TODAY))

"""Which vehicle runs which trip: recording from the vehicle feed (learning is in test_stays)."""
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

    def test_a_run_is_recorded_on_the_day_the_vehicle_can_be_on_it(self):
        def on(days):
            s = schedule()
            return {**s, 'bySequence': {k: {**v, 'serviceDay': DAY + days * 24 * H} for k, v in s['bySequence'].items()}}
        found = {('IJPP:t1', '20261009'): on(0), ('IJPP:t1', '20261010'): on(1), ('IJPP:t1', '20261008'): on(-1)}
        # Murska Sobota's buses name today's run (09:10-10:00, seen at 10:00) with tomorrow's date (22 Oct 2026).
        position = {'vehicle': {'trip': {'tripId': 'IJPP:t1', 'startDate': '20261010'}, 'vehicle': {'id': '1234'}, 'timestamp': str(NOW - 20)}}
        blocks.record(FakeSchedules(found), [position], {}, now=NOW)
        self.assertEqual(list(VehicleTrip.objects.values_list('service_date', flat=True)), [TODAY])
        # A bus names tomorrow's 09:10 run at 21:00: not on it yet (between trips).
        VehicleTrip.objects.all().delete()
        late = NOW + 11 * H
        position['vehicle']['timestamp'] = str(late - 20)
        counts = blocks.record(FakeSchedules(found), [position], {}, now=late)
        self.assertEqual((counts['vehicles'], counts['between'], VehicleTrip.objects.count()), (0, 1, 0))

    def test_rows_older_than_eight_weeks_are_pruned_once_a_day(self):
        run(TODAY - timedelta(days=57), 'IJPP:old', 'IJPP:v', 'IJPP:r', 0, 60)
        run(TODAY - timedelta(days=55), 'IJPP:kept', 'IJPP:v', 'IJPP:r', 0, 60)
        self.assertEqual(blocks.prune(DAY + 12 * H), 1)
        self.assertEqual(blocks.prune(DAY + 13 * H), 0)
        self.assertEqual(list(VehicleTrip.objects.values_list('trip_id', flat=True)), ['IJPP:kept'])

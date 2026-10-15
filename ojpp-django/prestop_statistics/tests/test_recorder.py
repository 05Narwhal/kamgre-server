"""The stay-on-the-same-vehicle recorder (blocks.record, version 2): stop patterns, start delays, what a vehicle
does between trips (VehicleGap) and how much of each day was recorded (RecorderDay)."""
from django.test import TestCase

from prestop_statistics import blocks
from prestop_statistics.models import RecorderDay, VehicleGap, VehicleTrip
from prestop_statistics.tests.test_blocks import FakeSchedules
from prestop_statistics.tests.test_statistics import DAY, NOW, schedule

H = 3600
TERMINUS = (46.05, 14.50)
DEPOT = (46.08, 14.55)


def with_stops(sched, last=TERMINUS):
    for i, s in sched['bySequence'].items():
        s['stop'] = {**s['stop'], 'lat': last[0] - 0.01 * (6 - i), 'lon': last[1]}
    return sched


def on_trip(trip, vehicle='77', at=TERMINUS, sequence=3, now=NOW):
    return {'id': trip, 'vehicle': {'trip': {'tripId': trip, 'startDate': '20261009'}, 'vehicle': {'id': vehicle}, 'timestamp': str(now - 5),
                                    'position': {'latitude': at[0], 'longitude': at[1]}, 'currentStopSequence': sequence}}


def between(vehicle='77', at=TERMINUS, now=NOW):
    return {'id': 'IJPP:veh', 'vehicle': {'trip': {'tripId': 'IJPP:'}, 'vehicle': {'id': vehicle}, 'timestamp': str(now - 5),
                                          'position': {'latitude': at[0], 'longitude': at[1]}}}


class RecorderTests(TestCase):
    def setUp(self):
        blocks._tracker = blocks.GapTracker()
        blocks._coverage['last'] = None
        blocks._pruned['day'] = None
        other = with_stops(schedule('IJPP:r2'))
        for s in other['bySequence'].values():
            s['scheduledDeparture'] += 2 * H
            s['scheduledArrival'] += 2 * H
        self.schedules = FakeSchedules({('IJPP:a', '20261009'): with_stops(schedule()), ('IJPP:b', '20261009'): other})

    def poll(self, entities, now, delays=None):
        updates = {t: {'updates': [{'stopSequence': 1, 'arrival': {'delay': d}}], 'timestamp': now, 'trip': {}} for t, d in (delays or {}).items()}
        return blocks.record(self.schedules, entities, updates, now=now)

    def test_the_trip_keeps_its_stop_pattern_and_start_delay(self):
        self.poll([on_trip('IJPP:a', sequence=1)], NOW, {'IJPP:a': 120})
        self.poll([on_trip('IJPP:a', sequence=4)], NOW + 60, {'IJPP:a': 300})
        row = VehicleTrip.objects.get()
        self.assertEqual((row.version, row.start_delay, row.end_delay), (2, 120, 300))
        self.assertEqual(row.pattern, blocks.pattern_key(self.schedules.found[('IJPP:a', '20261009')]))
        changed = with_stops(schedule())
        changed['bySequence'][3]['stop'] = {'gtfsId': 'IJPP:detour'}
        self.assertNotEqual(blocks.pattern_key(changed), row.pattern)  # a timetable change is another departure

    def test_a_wait_at_the_terminus_is_summed_up(self):
        self.poll([on_trip('IJPP:a')], NOW, {})
        for k in range(1, 6):  # five minutes at the terminus, between trips
            self.poll([between(at=TERMINUS, now=NOW + 60 * k)], NOW + 60 * k)
        counts = self.poll([on_trip("IJPP:b", now=NOW + 360)], NOW + 360, {})
        self.assertEqual(counts['gaps'], 1)
        gap = VehicleGap.objects.get()
        self.assertEqual((gap.after_trip_id, gap.before_trip_id, gap.seen_polls, gap.unseen_polls, gap.max_distance),
                         ('IJPP:a', 'IJPP:b', 5, 0, 0))
        self.assertEqual(gap.terminus_wait, 240)
        self.assertEqual(gap.idle, [])

    def test_a_trip_to_the_depot_leaves_an_idle_spot_and_a_long_way(self):
        self.poll([on_trip('IJPP:a')], NOW, {})
        t = NOW
        for k in range(1, 25):  # 24 minutes standing at the depot, then two polls missing from the feed
            t = NOW + 60 * k
            self.poll([between(at=DEPOT, now=t)], t)
        self.poll([], t + 60)
        self.poll([], t + 120)
        self.poll([on_trip("IJPP:b", now=t + 180)], t + 180, {})
        gap = VehicleGap.objects.get()
        self.assertGreater(gap.max_distance, 3000)
        self.assertEqual(gap.unseen_polls, 2)
        self.assertEqual(len(gap.idle), 1)
        self.assertEqual(gap.idle[0][:2], [DEPOT[0], DEPOT[1]])
        self.assertGreaterEqual(gap.idle[0][2], blocks.IDLE_SECONDS)

    def test_straight_onto_the_next_trip_is_a_gap_of_nothing(self):
        self.poll([on_trip('IJPP:a')], NOW, {})
        self.poll([on_trip('IJPP:b')], NOW + 60, {})
        gap = VehicleGap.objects.get()
        self.assertEqual((gap.seen_polls, gap.unseen_polls, gap.terminus_wait), (0, 0, 0))

    def test_a_gap_with_no_next_trip_expires(self):
        self.poll([on_trip('IJPP:a')], NOW, {})
        self.poll([], NOW + blocks.MAX_OPEN + 120)
        gap = VehicleGap.objects.get()
        self.assertEqual((gap.after_trip_id, gap.before_trip_id, gap.started), ('IJPP:a', '', None))

    def test_coverage_counts_the_seconds_between_polls(self):
        self.poll([on_trip('IJPP:a')], NOW, {})
        self.poll([on_trip('IJPP:a')], NOW + 60, {})
        self.poll([], NOW + 120)
        self.poll([], NOW + 2 * H)  # the collector was down: only POLL_CREDIT counts
        days = {r.feed: (r.seconds, r.polls) for r in RecorderDay.objects.all()}
        self.assertEqual(days['*'], (60 + 60 + blocks.POLL_CREDIT, 3))
        self.assertEqual(days['IJPP'], (60, 1))
        self.assertEqual(RecorderDay.objects.first().day.isoformat(), '2026-10-09')

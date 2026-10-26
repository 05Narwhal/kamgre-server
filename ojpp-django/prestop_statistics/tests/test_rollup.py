"""SŽ nightly rollups (spec 2026-10-26 F6): TrainDay and StationDay from TripDelay, one punctuality definition (on
time = under 3 min late), a backfill that stops when the night window ends."""
from datetime import date, datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from prestop_statistics import rollup
from prestop_statistics.models import StationDay, TrainDay, TripDelay

DAY = date(2026, 10, 25)
STATIONS = [('IJPP:lj', 'Ljubljana'), ('IJPP:kr', 'Kranj'), ('IJPP:le', 'Lesce-Bled'), ('IJPP:je', 'Jesenice')]
TRIPS = {
    'IJPP:t2428': {'route': 'IJPP:r2428', 'name': 'LPV 2428', 'mode': 'RAIL', 'stops': {i + 1: s for i, s in enumerate(STATIONS)}},
    'IJPP:t310': {'route': 'IJPP:r310', 'name': 'RG 310', 'mode': 'RAIL', 'stops': {i + 1: s for i, s in enumerate(STATIONS)}},
    'IJPP:b18969': {'route': 'IJPP:rb', 'name': 'BUS 18969', 'mode': 'BUS', 'stops': {1: STATIONS[0], 2: STATIONS[1]}},
    'IJPP:t310b': {'route': 'IJPP:r310b', 'name': 'RG 310', 'mode': 'RAIL', 'stops': {1: STATIONS[2], 2: STATIONS[3]}},
}


def delay(trip, stops, day=DAY, operator='IJPP:1161'):
    now = timezone.now()
    return TripDelay.objects.create(service_date=day, trip_id=trip, route_id=TRIPS.get(trip, {}).get('route', 'IJPP:x'), operator_id=operator,
                                    direction='0', stop_delays={str(k): v for k, v in stops.items()}, first_seen=now, last_seen=now)


def lookups(asked=None):
    def trip_stops(ids):
        if asked is not None:
            asked.extend(ids)
        return {t: TRIPS.get(t) for t in ids}
    return trip_stops


class RollupTests(TestCase):
    def setUp(self):
        delay('IJPP:t2428', {1: 0, 2: 120, 3: 300, 4: 240})   # 2 of 4 stations on time
        delay('IJPP:t310', {1: 600, 2: 660})                  # late, last two not reported
        delay('IJPP:t310b', {1: 600})                         # the same number on another route: fewer reports
        delay('IJPP:b18969', {1: 900, 2: 900})                # a replacement bus: not a train
        delay('LPP:t1', {1: 60}, operator='LPP:lpp')          # not SŽ

    def test_one_row_per_train_with_its_delays_and_tracks(self):
        trains, stations, counts = rollup.build(DAY, lookups(), lambda day: {'2428': {'IJPP:kr': '2'}})
        self.assertEqual([t['number'] for t in trains], ['2428', '310'])
        t = trains[0]
        self.assertEqual((t['category'], t['origin'], t['destination']), ('LPV', 'Ljubljana', 'Jesenice'))
        self.assertEqual((t['max_delay'], t['avg_delay'], t['final_delay'], t['on_time_share']), (300, 165, 240, 0.5))
        self.assertEqual(t['stops'][1], {'id': 'IJPP:kr', 'name': 'Kranj', 'delay': 120, 'track': '2'})
        rg = trains[1]
        self.assertEqual((rg['trip_id'], rg['final_delay'], rg['stops'][3]['delay']), ('IJPP:t310', 660, None))
        self.assertEqual(counts, {'trips': 4, 'trains': 2, 'unknown trips': 0})
        kranj = next(s for s in stations if s['stop_id'] == 'IJPP:kr')
        self.assertEqual((kranj['trains'], kranj['on_time_share'], kranj['avg_delay']), (2, 0.5, 390))

    def test_a_trip_otp_no_longer_has_is_left_out(self):
        trains, _, counts = rollup.build(DAY, lambda ids: {t: None for t in ids}, lambda day: {})
        self.assertEqual((trains, counts['unknown trips']), ([], 4))

    def test_a_rerun_replaces_the_day(self):
        for _ in range(2):
            trains, stations, _ = rollup.build(DAY, lookups(), lambda day: {})
            rollup.write(DAY, trains, stations)
        self.assertEqual(TrainDay.objects.filter(service_date=DAY).count(), 2)
        self.assertEqual(StationDay.objects.filter(service_date=DAY).count(), 4)

    def test_the_backfill_asks_otp_about_each_trip_once_and_stops_at_the_end_of_the_window(self):
        for back in (1, 2, 3):
            delay('IJPP:t2428', {1: 60}, day=date(2026, 10, 25 - back))
        self.assertEqual(rollup.days_to_backfill(DAY, 90), [date(2026, 10, 24), date(2026, 10, 23), date(2026, 10, 22)])
        asked = []
        clock = iter([datetime(2026, 10, 26, 2, 10, tzinfo=rollup_tz()), datetime(2026, 10, 26, 2, 30, tzinfo=rollup_tz()),
                      datetime(2026, 10, 26, 2, 40, tzinfo=rollup_tz()), datetime(2026, 10, 26, 2, 51, tzinfo=rollup_tz())])
        out = StringIO()
        with mock.patch('prestop_statistics.rollup.otp_trip_stops', side_effect=lookups(asked)), \
                mock.patch('prestop_statistics.rollup.scraper_tracks', return_value={}), \
                mock.patch('prestop_statistics.management.commands.rollup_stats.datetime', wraps=datetime) as fake:
            fake.now.side_effect = lambda tz=None: next(clock)
            call_command('rollup_stats', '--day', '2026-10-25', '--backfill', '90', '--until', '02:50', stdout=out)
        self.assertEqual(sorted(asked), sorted(TRIPS))  # day 25 asked all four; the older days only reuse them
        days = set(TrainDay.objects.values_list('service_date', flat=True))
        self.assertEqual(days, {DAY, date(2026, 10, 24), date(2026, 10, 23)})  # 22 Oct left for the next night


def rollup_tz():
    from prestop_statistics.collector import LJUBLJANA
    return LJUBLJANA

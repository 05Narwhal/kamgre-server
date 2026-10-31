"""SŽ nightly rollups (spec 2026-10-26 F6): TrainDay and StationDay from TripDelay, one punctuality definition (on
time = under 3 min late), a backfill that stops when the night window ends. Spec 2026-10-31 H1: the scheduled
departure, canceled and replaced runs, the delay gained per station and the `--since` re-roll."""
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


NO_PLAN = lambda day: None  # noqa: E731 - the replacement plan could not be read


def delay(trip, stops, day=DAY, operator='IJPP:1161', canceled=False):
    now = timezone.now()
    return TripDelay.objects.create(service_date=day, trip_id=trip, route_id=TRIPS.get(trip, {}).get('route', 'IJPP:x'), operator_id=operator,
                                    direction='0', stop_delays={str(k): v for k, v in stops.items()}, canceled=canceled,
                                    first_seen=now, last_seen=now)


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
        trains, stations, counts = rollup.build(DAY, lookups(), lambda day: {'2428': {'IJPP:kr': '2'}}, plan=NO_PLAN)
        self.assertEqual([t['number'] for t in trains], ['2428', '310'])
        t = trains[0]
        self.assertEqual((t['category'], t['origin'], t['destination']), ('LPV', 'Ljubljana', 'Jesenice'))
        self.assertEqual((t['max_delay'], t['avg_delay'], t['final_delay'], t['on_time_share']), (300, 165, 240, 0.5))
        self.assertEqual(t['stops'][1], {'id': 'IJPP:kr', 'name': 'Kranj', 'delay': 120, 'gained': 120, 'track': '2', 'time': None})
        self.assertEqual([s['gained'] for s in t['stops']], [None, 120, 180, -60])
        self.assertEqual((t['canceled'], t['replaced']), (False, None))  # no plan: replaced unknown, not 'none'
        rg = trains[1]
        self.assertEqual((rg['trip_id'], rg['final_delay'], rg['stops'][3]['delay']), ('IJPP:t310', 660, None))
        self.assertEqual(counts, {'trips': 4, 'trains': 2, 'unknown trips': 0, 'canceled': 0, 'replaced': None})
        kranj = next(s for s in stations if s['stop_id'] == 'IJPP:kr')
        self.assertEqual((kranj['trains'], kranj['on_time_share'], kranj['avg_delay']), (2, 0.5, 390))

    def test_a_trip_otp_no_longer_has_is_left_out(self):
        trains, _, counts = rollup.build(DAY, lambda ids: {t: None for t in ids}, lambda day: {}, plan=NO_PLAN)
        self.assertEqual((trains, counts['unknown trips']), ([], 4))

    def test_a_rerun_replaces_the_day(self):
        for _ in range(2):
            trains, stations, _ = rollup.build(DAY, lookups(), lambda day: {}, plan=NO_PLAN)
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
                mock.patch('prestop_statistics.rollup.day_plan', return_value=None), \
                mock.patch('prestop_statistics.management.commands.rollup_stats.datetime', wraps=datetime) as fake:
            fake.now.side_effect = lambda tz=None: next(clock)
            call_command('rollup_stats', '--day', '2026-10-25', '--backfill', '90', '--until', '02:50', stdout=out)
        self.assertEqual(sorted(asked), sorted(TRIPS))  # day 25 asked all four; the older days only reuse them
        days = set(TrainDay.objects.values_list('service_date', flat=True))
        self.assertEqual(days, {DAY, date(2026, 10, 24), date(2026, 10, 23)})  # 22 Oct left for the next night


class CanceledAndReplacedTests(TestCase):
    """Spec 2026-10-31 H1: canceled and replaced runs get rows without delays, which are never on time."""

    def plan(self, sections):
        """A day plan holding the two trains (stops 1-4 at 08:00, 08:10, ...), buses replacing `sections` of them:
        {trip id: [(from index or None, to index or None)]}."""
        midnight = int(datetime(2026, 10, 25, tzinfo=rollup_tz()).timestamp())
        run = lambda trip_id: {'id': trip_id, 'stops': [{'gtfsId': s} for s, _ in STATIONS], 'serviceDay': midnight,  # noqa: E731
                               'departures': [midnight + 8 * 3600 + 600 * i for i in range(4)],
                               'arrivals': [midnight + 8 * 3600 + 600 * i for i in range(4)]}
        trips = {t: [run(t)] for t in ('IJPP:t2428', 'IJPP:t310')}
        return lambda day: {'trips': trips, 'sections': {t: [
            {'fromIndex': a, 'toIndex': b, 'busTripId': 'IJPP:bus', 'start': trips[t][0]['departures'][a if a is not None else 0],
             'end': trips[t][0]['arrivals'][b if b is not None else 3]} for a, b in found] for t, found in sections.items()}}

    def test_a_canceled_train_has_a_row_without_delays_and_no_station_counts(self):
        delay('IJPP:t2428', {}, canceled=True)
        trains, stations, counts = rollup.build(DAY, lookups(), lambda day: {}, plan=NO_PLAN)
        t = trains[0]
        self.assertEqual((t['number'], t['canceled'], t['max_delay'], t['avg_delay'], t['on_time_share']), ('2428', True, None, None, None))
        self.assertEqual((stations, counts['canceled']), ([], 1))

    def test_a_canceled_run_never_beats_a_run_of_the_same_number_that_reported(self):
        delay('IJPP:t310', {1: 60})
        delay('IJPP:t310b', {}, canceled=True)
        trains, _, _ = rollup.build(DAY, lookups(), lambda day: {}, plan=NO_PLAN)
        self.assertEqual((trains[0]['trip_id'], trains[0]['canceled']), ('IJPP:t310', False))

    def test_replaced_part_whole_and_none_from_the_day_plan(self):
        delay('IJPP:t2428', {1: 0, 2: 60})           # a bus from Lesce-Bled on: part
        delay('IJPP:t310b', {1: 120})                # not in the plan's sections: none
        plan = self.plan({'IJPP:t2428': [(2, None)], 'IJPP:t310': [(0, 1), (1, 3)]})  # RG 310: two buses end to end
        trains, _, counts = rollup.build(DAY, lookups(), lambda day: {}, plan=plan)
        by = {t['trip_id']: t for t in trains}
        self.assertEqual(by['IJPP:t2428']['replaced'], 'part')
        self.assertEqual(by['IJPP:t2428']['max_delay'], 60)
        # RG 310's Ljubljana run reported nothing and buses ran all of it; its Lesce-Bled run reported, so that run is
        # the number's row of the day (more reports win), and the plan does not replace it.
        self.assertNotIn('IJPP:t310', by)
        self.assertEqual(by['IJPP:t310b']['replaced'], 'none')
        self.assertEqual(counts['replaced'], 1)

    def test_a_wholly_replaced_train_without_reports_gets_a_row(self):
        delay('IJPP:t2428', {1: 0})
        plan = self.plan({'IJPP:t310': [(None, 1), (1, None)]})
        trains, _, counts = rollup.build(DAY, lookups(), lambda day: {}, plan=plan)
        rg = next(t for t in trains if t['number'] == '310')
        self.assertEqual((rg['replaced'], rg['canceled'], rg['max_delay'], rg['on_time_share'], rg['trip_id']),
                         ('whole', False, None, None, 'IJPP:t310'))
        self.assertEqual(next(t for t in trains if t['number'] == '2428')['replaced'], 'none')
        self.assertEqual(counts['replaced'], 1)

    def test_a_gap_between_buses_is_part_not_whole(self):
        delay('IJPP:t2428', {1: 0})
        trains, _, _ = rollup.build(DAY, lookups(), lambda day: {}, plan=self.plan({'IJPP:t2428': [(0, 1), (2, 3)]}))
        self.assertEqual(trains[0]['replaced'], 'part')

    def test_the_scheduled_departure_comes_from_otp(self):
        delay('IJPP:t2428', {1: 0})
        trips = lambda ids: {t: {**TRIPS[t], 'departure': 8 * 3600} for t in ids}  # noqa: E731
        trains, _, _ = rollup.build(DAY, trips, lambda day: {}, plan=NO_PLAN)
        rollup.write(DAY, trains, [])
        row = TrainDay.objects.get(number='2428')
        self.assertEqual((row.departure, row.canceled, row.replaced), (8 * 3600, False, None))

    def test_stations_by_the_hour_of_their_scheduled_time(self):
        delay('IJPP:t2428', {1: 0, 2: 240, 3: 300})
        delay('IJPP:t310', {1: 60, 2: 600})
        times = {1: 7 * 3600 + 3000, 2: 8 * 3600 + 600, 3: 8 * 3600 + 1800, 4: 9 * 3600}
        trips = lambda ids: {t: {**TRIPS[t], 'times': times} for t in ids}  # noqa: E731 - both trains at the same times
        trains, stations, _ = rollup.build(DAY, trips, lambda day: {}, plan=NO_PLAN)
        self.assertEqual(trains[0]['stops'][1]['time'], 8 * 3600 + 600)
        by = {s['stop_id']: s['hours'] for s in stations}
        self.assertEqual(by['IJPP:kr'], {'8': [2, 0, 840]})       # 4 and 10 min late at 8:10
        self.assertEqual(by['IJPP:lj'], {'7': [2, 2, 60]})
        self.assertEqual(by['IJPP:le'], {'8': [1, 0, 300]})

    def test_since_re_rolls_days_that_already_have_rows(self):
        for back in (0, 1, 2):
            delay('IJPP:t2428', {1: 60 * back}, day=date(2026, 10, 25 - back))
        TrainDay.objects.create(service_date=date(2026, 10, 24), number='2428', route_id='r', trip_id='t')  # an old row
        with mock.patch('prestop_statistics.rollup.otp_trip_stops', side_effect=lookups()), \
                mock.patch('prestop_statistics.rollup.scraper_tracks', return_value={}), \
                mock.patch('prestop_statistics.rollup.day_plan', return_value=None):
            call_command('rollup_stats', '--day', '2026-10-25', '--since', '2026-10-24', stdout=StringIO())
        self.assertEqual(TrainDay.objects.get(service_date=date(2026, 10, 24)).max_delay, 60)  # re-rolled
        self.assertFalse(TrainDay.objects.filter(service_date=date(2026, 10, 23)).exists())  # before --since


def rollup_tz():
    from prestop_statistics.collector import LJUBLJANA
    return LJUBLJANA

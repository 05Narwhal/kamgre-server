"""Replacement buses on every date (spec 2026-10-27 G3): a notice that names its trains (zamudil.si) replaces those
only, on the days its spans give; the line page lists the replaced runs from the same day plan."""
from datetime import datetime

from django.test import SimpleTestCase

from prestop_api import closures, replacement
from prestop_api.tests.test_timetable_buses import LOCAL, TABLES, DayPlanTests, alert, build, feed, timetabled


def numbers(plan: dict) -> set[str]:
    """The trains the plan's buses run for."""
    return {(b.get('trainName') or '').split()[-1] for b in plan['buses'] if b.get('trainName')}


def named(number: str, trains=None, dates=None, on=None) -> dict:
    a = alert(number)
    if trains is not None:
        a.update(_trains=frozenset(trains), _trains_on=on or {})
    if dates is not None:
        a['_dates'] = frozenset(dates)
    return a


class NamedTrainsTests(SimpleTestCase):
    def test_a_notice_without_trains_replaces_every_train_on_its_section(self):
        guessed = build('20261014', tables=None, alerts=[named('99002')])
        self.assertTrue({'2400', '2402', '38'} <= numbers(guessed), numbers(guessed))

    def test_a_notice_naming_its_trains_replaces_only_those(self):
        guessed = build('20261014', tables=None, alerts=[named('99002', {'2400', '2402'})])
        self.assertEqual(numbers(guessed), {'2400', '2402'})

    def test_the_trains_of_that_date(self):
        on = {'20261014': frozenset({'2400'})}
        self.assertEqual(numbers(build('20261014', tables=None, alerts=[named('99002', {'2400', '2402'}, on=on)])), {'2400'})
        self.assertEqual(closures.trains_of(named('99002', {'2400', '2402'}, on=on), '20261015'), frozenset({'2400', '2402'}))
        self.assertIsNone(closures.trains_of(named('99002'), '20261014'))

    def test_a_timetable_runs_the_buses_of_the_named_trains_only(self):
        every = timetabled(build('20261014', alerts=[named('11147')]))
        only = timetabled(build('20261014', alerts=[named('11147', {'38'})]))
        self.assertGreater(len(every), len(only))
        self.assertTrue(only)
        self.assertEqual({n for b in only.values() if not b['additional'] for n in b['numbers']} & {'38'}, {'38'})
        self.assertTrue(all('38' in b['numbers'] or b['additional'] for b in only.values()), sorted(only))


class SpansTests(SimpleTestCase):
    def test_a_day_between_two_spans_has_no_buses(self):
        """"(13. 10. in 15. 10.)": the notice is not in effect on the 14th."""
        between = build('20261014', tables=None, alerts=[named('99002', {'2400'}, dates={'20261013', '20261015'})])
        self.assertEqual(between['buses'], [])
        inside = build('20261014', tables=None, alerts=[named('99002', {'2400'}, dates={'20261014'})])
        self.assertEqual(numbers(inside), {'2400'})

    def test_the_days_of_a_notice(self):
        a = named('99002', dates={'20261026', '20261103'})
        self.assertEqual(closures._days(a), {'20261026', '20261103'})
        start = datetime(2026, 11, 1, 10, tzinfo=LOCAL).timestamp()
        self.assertFalse(closures.leg_alerts.on_listed_day(a, start, start + 3600))
        start = datetime(2026, 11, 3, 10, tzinfo=LOCAL).timestamp()
        self.assertTrue(closures.leg_alerts.on_listed_day(a, start, start + 3600))


class ReplacedRunsTests(SimpleTestCase):
    def test_the_line_lists_its_replaced_runs(self):
        trips = feed('20261014')
        plan = DayPlanTests().derive({'key': None}, trips, TABLES)
        train = next(t for t in trips if t['route']['shortName'] == 'LPV 2400')
        other = next(t for t in trips if t['route']['shortName'] == 'LPV 2401')
        departures = [{'tripId': t['id'], 'departure': datetime.fromtimestamp(t['departures'][0], LOCAL).isoformat()} for t in (train, other, train)]
        runs = replacement.replaced_runs(plan, departures)
        mine = [r for r in runs if r['tripId'] == train['id']]
        self.assertEqual(len(mine), 1)
        [run] = mine
        bus = plan['by_id'][run['busTripIds'][0]]
        self.assertEqual((run['trainNumber'], run['busRouteId']), ('2400', bus['route']['gtfsId']))
        self.assertTrue(closures.is_synthetic_line(run['busRouteId']))
        self.assertEqual(run['fromStop'], train['stops'][bus['fromIndex']]['name'])
        self.assertEqual(run['toStop'], train['stops'][bus['toIndex']]['name'])
        self.assertEqual(replacement.replaced_runs(None, departures), [])

    def test_a_split_train_lists_the_bus_before_it(self):
        """ICS 36: the feed's train runs Celje – Maribor, BUS 36006 Ljubljana – Celje before it."""
        start = datetime(2026, 10, 28, 6, 0, tzinfo=LOCAL).timestamp()
        stops = [{'name': 'Celje', 'gtfsId': 'IJPP:1'}, {'name': 'Maribor', 'gtfsId': 'IJPP:2'}]
        train = {'id': 'IJPP:t36', 'route': {'gtfsId': 'IJPP:r36', 'shortName': 'ICS 36'}, 'stops': stops,
                 'departures': [start, start + 3600], 'arrivals': [start, start + 3600]}
        bus = {'id': 'IJPP:b36006', 'route': {'gtfsId': 'IJPP:rb', 'shortName': 'BUS 36006'}, 'stops': [{'name': 'Ljubljana'}, stops[0]],
               'departures': [start - 4000, start - 120], 'arrivals': [start - 4000, start - 120]}
        plan = {'sections': {train['id']: [{'fromIndex': None, 'toIndex': 0, 'start': start - 4000, 'end': start - 120, 'busTripId': bus['id']}]},
                'trips': {train['id']: [train], bus['id']: [bus]}, 'by_id': {}}
        trip = {'id': train['id'], 'stops': [{'name': 'Celje', 'scheduledDeparture': datetime.fromtimestamp(start, LOCAL).isoformat()},
                                             {'name': 'Maribor', 'scheduledDeparture': datetime.fromtimestamp(start + 3600, LOCAL).isoformat()}]}
        self.assertEqual(replacement.trip_sections(trip, plan), [{'fromIndex': None, 'toIndex': 0, 'busTripId': bus['id'], 'busName': 'BUS 36006'}])
        [run] = replacement.replaced_runs(plan, [{'tripId': train['id'], 'departure': trip['stops'][0]['scheduledDeparture']}])
        self.assertEqual((run['trainNumber'], run['fromStop'], run['toStop'], run['busRouteId']), ('36', None, 'Celje', 'IJPP:rb'))

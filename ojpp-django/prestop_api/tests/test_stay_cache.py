"""E1: "Stay on the bus" is decided on the first answer of a cold process: the learned departures are held per process
and the stops of the trips come with the plan, so nothing waits for a background load."""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import journeys, predictions
from prestop_api.tests.test_insane import plan, request
from prestop_api.tests.test_mapping import leg
from prestop_statistics import blocks
from prestop_statistics.aggregation import day_kind

DAY = date(2026, 10, 9)
START_1, START_2 = 9 * 3600 + 40 * 60, 10 * 3600 + 22 * 60
STOPS_1, STOPS_2 = ['IJPP:a', 'IJPP:b'], ['IJPP:b', 'IJPP:c']


def learned_row(**overrides):
    return {'route_id': 'IJPP:r2', 'kind': day_kind(DAY), 'start': START_2, 'pattern': blocks.hash_stops(STOPS_2), 'origin': 'continues',
            'level': 'sure', 'prev_route_id': 'IJPP:r', 'prev_start': START_1, 'prev_pattern': blocks.hash_stops(STOPS_1), 'prev_end': 10 * 3600 + 20 * 60,
            'absorb': None, 'depot_delay': None, **overrides}


def table(*rows):
    out = {}
    for r in rows:
        out.setdefault((r['route_id'], r['kind']), {})[r['start']] = r
    return out


def cold():
    """A process that has just started: nothing loaded, nothing known about any trip."""
    predictions._learned.update(on=None, checked=0.0, rows={})
    predictions._patterns.clear()
    predictions._fetching.clear()
    predictions.rejections.clear()


@override_settings(PRESTOP_PREDICTIONS=True)
class ColdStayTests(SimpleTestCase):
    def setUp(self):
        cold()
        self.addCleanup(cold)

    def build(self, learned, stops=(STOPS_1, STOPS_2), fetch=None):
        first = leg('BUS', '10:00:00', '10:20:00', trip='IJPP:t1')
        second = leg('BUS', '10:22:00', '10:50:00', trip='IJPP:t2')
        first['to']['stop']['gtfsId'], second['from']['stop']['gtfsId'] = 'IJPP:b', 'IJPP:b'
        second['route'] = {**second['route'], 'gtfsId': 'IJPP:r2', 'shortName': '2'}
        for raw, start, ids in ((first, START_1, stops[0]), (second, START_2, stops[1])):
            raw['trip'].update(blockId=None, departureStoptime={'scheduledDeparture': start}, stoptimes=[{'stop': {'gtfsId': s}} for s in ids])
        with mock.patch('prestop_statistics.stays.learned_version', return_value=(DAY, 1)), \
                mock.patch('prestop_statistics.stays.all_departures', return_value=learned) as loaded, \
                mock.patch('prestop_statistics.stays.trip_pattern', side_effect=fetch or AssertionError('asked OTP for a trip the plan described')), \
                mock.patch.object(predictions, 'usual', return_value={}), mock.patch.object(predictions, 'previous_trip', return_value=None), \
                mock.patch('prestop_api.sources.stop_group', side_effect=lambda s: [s]):
            [j] = journeys.build_journeys(plan([first, second]), request(slack=0), [])
        self.loaded = loaded
        return [l for l in j['legs'] if l['mode'] != 'walk'][1], j

    def test_the_first_answer_of_a_cold_process_has_the_stay(self):
        second, j = self.build(table(learned_row()))
        self.assertEqual(second['stayLevel'], 'sure')
        self.assertEqual(j['transferCount'], 0)
        self.loaded.assert_called_once()

    def test_a_pattern_that_changed_is_refused_and_counted(self):
        second, _ = self.build(table(learned_row()), stops=(STOPS_1, ['IJPP:b', 'IJPP:x', 'IJPP:c']))
        self.assertIsNone(second['stayLevel'])
        self.assertEqual(dict(predictions.rejections), {'pattern-changed': 1})

    def test_another_previous_trip_is_refused_and_counted(self):
        second, _ = self.build(table(learned_row(prev_start=8 * 3600)))
        self.assertIsNone(second['stayLevel'])
        self.assertEqual(dict(predictions.rejections), {'other-previous-trip': 1})

    def test_a_trip_the_plan_did_not_describe_is_asked_of_otp_once(self):
        second, _ = self.build(table(learned_row()), stops=(STOPS_1, []), fetch=lambda t: blocks.hash_stops(STOPS_2))
        self.assertEqual(second['stayLevel'], 'sure')

    def test_a_trip_otp_cannot_describe_in_time_is_refused(self):
        with mock.patch.object(predictions, 'PATTERN_WAIT', 0.0):
            second, _ = self.build(table(learned_row()), stops=(STOPS_1, []), fetch=lambda t: __import__('time').sleep(0.3))
        self.assertIsNone(second['stayLevel'])
        self.assertEqual(dict(predictions.rejections), {'pattern-missing': 1})


class LearnedTableTests(SimpleTestCase):
    def setUp(self):
        cold()
        self.addCleanup(cold)

    def test_the_table_is_loaded_for_the_first_caller_and_reloaded_when_a_new_day_was_learned(self):
        old, new = learned_row(), learned_row(level='likely')
        with mock.patch('prestop_statistics.stays.learned_version', side_effect=[(DAY, 1), (DAY, 1), (DAY, 2)]) as on, \
                mock.patch('prestop_statistics.stays.all_departures', side_effect=[table(old), table(new)]) as loaded:
            self.assertEqual(predictions.departure('IJPP:r2', START_2, DAY)['level'], 'sure')
            self.assertEqual(predictions.departure('IJPP:r2', START_2, DAY)['level'], 'sure')  # within the check interval: no query
            self.assertEqual((on.call_count, loaded.call_count), (1, 1))
            predictions._learned['checked'] -= predictions.LEARNED_CHECK
            self.assertEqual(predictions.departure('IJPP:r2', START_2, DAY)['level'], 'sure')  # same day: checked, not reloaded
            self.assertEqual((on.call_count, loaded.call_count), (2, 1))
            predictions._learned['checked'] -= predictions.LEARNED_CHECK
            self.assertEqual(predictions.departure('IJPP:r2', START_2, DAY)['level'], 'likely')  # rewritten: reloaded
            self.assertEqual(loaded.call_count, 2)

    def test_a_failed_read_keeps_the_old_table(self):
        with mock.patch('prestop_statistics.stays.learned_version', return_value=(DAY, 1)), mock.patch('prestop_statistics.stays.all_departures', return_value=table(learned_row())):
            predictions.departure('IJPP:r2', START_2, DAY)
        predictions._learned['checked'] -= predictions.LEARNED_CHECK
        with mock.patch('prestop_statistics.stays.learned_version', side_effect=RuntimeError('db down')):
            self.assertEqual(predictions.departure('IJPP:r2', START_2, DAY)['level'], 'sure')

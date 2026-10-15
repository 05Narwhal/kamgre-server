"""Every change of vehicle shows its comfort rating, tied to the leg it boards (A6)."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import journey_legs, journeys
from prestop_api.tests.test_insane import plan, request, ride
from prestop_api.tests.test_mapping import leg

AP = 'IJPP:1126954'  # Ljubljana AP: one feed stop for all 46 bays


def walk(start, end, seconds):
    return leg('WALK', start, end, transit=False, duration=seconds)


class TransferRatingTests(SimpleTestCase):
    def build(self, *legs, **kw):
        [j] = journeys.build_journeys(plan(list(legs)), request(insane=False, slack=180), [], **kw)
        return j

    def test_a_through_run_in_between_does_not_shift_the_ratings(self):
        first, through = ride('10:00:00', '10:20:00', 'IJPP:1'), ride('10:20:00', '10:40:00', 'IJPP:2', frm='IJPP:b', to='IJPP:c')
        through['interlineWithPreviousLeg'] = True  # OTP says stay seated; only what the vehicles did counts (stays.py)
        last = ride('10:50:00', '11:10:00', 'IJPP:3', frm='IJPP:c', to='IJPP:d')
        j = self.build(first, through, last)
        self.assertEqual(j['transferCount'], 2)
        at_b, at_c = j['transfers']
        self.assertEqual((at_b['legId'], at_b['status']), (j['legs'][1]['id'], 'tight'))  # 0 min on the timetable
        self.assertEqual((at_c['legId'], at_c['status']), (j['legs'][2]['id'], 'safe'))  # each rating on the leg it boards

    def test_same_stop_without_a_walk_and_with_a_zero_minute_walk(self):
        a, b = ride('10:00:00', '10:20:00', 'IJPP:1', to=AP), ride('10:30:00', '10:50:00', 'IJPP:2', frm=AP, to='IJPP:z')
        for middle in ([], [walk('10:20:00', '10:20:00', 0)]):
            j = self.build(a, *middle, b)
            self.assertEqual([(t['requiredSeconds'], t['status'], t['legId']) for t in j['transfers']], [(0, 'safe', j['legs'][-1]['id'])])

    def test_between_two_stops_of_one_merged_station(self):
        a, b = ride('10:00:00', '10:20:00', 'IJPP:1', to='IJPP:1121237'), ride('10:24:00', '10:50:00', 'MOKranj:2', frm='MOKranj:112', to='MOKranj:9')
        j = self.build(a, walk('10:20:00', '10:21:00', 60), b)
        [t] = j['transfers']
        self.assertEqual((t['requiredSeconds'], t['availableSeconds'], t['status']), (60, 240, 'safe'))

    def test_a_change_sz_holds_is_rated_but_not_counted(self):
        train, bus = ride('10:00:00', '10:20:00', 'IJPP:train'), ride('10:21:00', '11:00:00', 'IJPP:bus', frm='IJPP:b', to='IJPP:c')
        held = lambda legs, meta, *a: (legs, [meta[0], {**meta[1], 'held': True}])
        with mock.patch.object(journey_legs, 'rewrite', side_effect=held), mock.patch.object(journey_legs, 'unreplaced_notices'), \
                mock.patch.object(journey_legs, 'name_replaced_trains'):
            j = self.build(train, bus, plan_for=lambda when: None)
        self.assertEqual(j['transferCount'], 0)
        [t] = j['transfers']
        self.assertEqual((t['status'], t['held'], t['legId']), ('safe', True, j['legs'][1]['id']))

"""Insane mode optimises for arrival time only (request builder, allowance, labels, order, the -1 min pass)."""
from django.test import SimpleTestCase

from prestop_api import journeys
from prestop_api.tests.test_journey_alerts import PLACE
from prestop_api.tests.test_mapping import leg


def request(insane=True, slack=None, **overrides):
    body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-09T10:00:00+02:00',
            'timeMode': 'departAt', 'modes': ['walk', 'bus', 'rail'], 'riskMode': 'insane' if insane else 'normal', **overrides}
    if slack is not None:
        body['minTransferSeconds'] = slack
    return journeys.parse_request(body, insane_enabled=True)


def plan(*nodes):
    return {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': list(legs)}} for legs in nodes]}}


def ride(start, end, trip, frm='IJPP:a', to='IJPP:b'):
    raw = leg('RAIL', start, end, trip=trip)
    raw['from']['stop']['gtfsId'], raw['to']['stop']['gtfsId'] = frm, to
    return raw


class RequestTests(SimpleTestCase):
    def test_insane_drops_penalties_and_limits(self):
        v = journeys.otp_variables(request(slack=180))
        self.assertEqual(v['preferences']['transit']['transfer'],
                         {'slack': 'PT0S', 'cost': 0, 'maximumTransfers': 29, 'maximumAdditionalTransfers': 30})
        self.assertEqual(v['preferences']['street']['walk']['speed'], journeys.INSANE_WALK_SPEED)
        self.assertNotIn('reluctance', v['preferences']['street']['walk'])

    def test_negative_allowance_is_insane_only_and_never_sent_to_otp(self):
        req = request(slack=-60)
        self.assertEqual(req['minTransferSeconds'], -60)
        self.assertEqual(journeys.otp_variables(req)['preferences']['transit']['transfer']['slack'], 'PT0S')
        with self.assertRaises(journeys.RequestError):
            request(insane=False, slack=-60)
        with self.assertRaises(journeys.RequestError):
            request(slack=-61)

    def test_normal_mode_is_unchanged(self):
        v = journeys.otp_variables(request(insane=False, slack=180))
        self.assertEqual(v['preferences']['transit']['transfer'], {'slack': 'PT180S'})

    def test_max_transfers_limits_the_search_in_either_mode(self):
        self.assertEqual(journeys.otp_variables(request(insane=False, maxTransfers=1))['preferences']['transit']['transfer'],
                         {'slack': 'PT180S', 'maximumTransfers': 1})
        self.assertEqual(journeys.otp_variables(request(maxTransfers=0))['preferences']['transit']['transfer']['maximumTransfers'], 0)
        self.assertIsNone(request(insane=False)['maxTransfers'])
        for bad in (-1, 6, 1.5, True, '2'):
            with self.assertRaises(journeys.RequestError):
                request(insane=False, maxTransfers=bad)


class LabelTests(SimpleTestCase):
    def build(self, req, gap_end):
        first, second = ride('10:00:00', '10:20:00', 'IJPP:t1'), ride(gap_end, '10:50:00', 'IJPP:t2', frm='IJPP:b', to='IJPP:c')
        [j] = journeys.build_journeys(plan([first, second]), req, [])
        return j['transfers'][0]

    def test_a_transfer_under_two_minutes_is_tight_and_one_inside_the_allowance_is_a_bet(self):
        self.assertEqual(self.build(request(slack=0), '10:21:00')['status'], 'tight')
        self.assertEqual(self.build(request(slack=0), '10:25:00')['status'], 'safe')
        self.assertEqual(self.build(request(slack=-60), '10:19:20')['status'], 'tight')    # -0:40, allowed
        self.assertEqual(self.build(request(slack=0), '10:19:20')['status'], 'missed')     # -0:40, not allowed
        self.assertEqual(self.build(request(slack=-60), '10:18:30')['status'], 'missed')   # -1:30


class OrderTests(SimpleTestCase):
    def test_earliest_arrival_first_then_latest_departure(self):
        j = lambda dep, arr: {'effectiveDeparture': f'2026-10-09T{dep}+02:00', 'effectiveArrival': f'2026-10-09T{arr}+02:00'}
        out = journeys.by_arrival([j('10:00:00', '11:00:00'), j('10:05:00', '10:50:00'), j('10:10:00', '10:50:00')])
        self.assertEqual([x['effectiveDeparture'][11:16] for x in out], ['10:10', '10:05', '10:00'])


class BetTests(SimpleTestCase):
    def test_a_connection_leaving_within_the_allowance_is_added_when_it_arrives_sooner(self):
        slow = [ride('10:00:00', '10:20:00', 'IJPP:t1'), ride('10:30:00', '11:30:00', 'IJPP:t2', frm='IJPP:b', to='IJPP:c')]
        asked = []

        def query(q, variables):
            asked.append(variables)
            # From the transfer stop, a train that left at 10:19:30 (30 s before the rider arrives) and is there sooner.
            return plan([ride('10:19:30', '11:00:00', 'IJPP:t3', frm='IJPP:b', to='IJPP:c')])

        data = journeys.bet_on_delays(plan(slow), request(slack=-60), query)
        self.assertEqual(asked[0]['origin'], {'label': 'B', 'location': {'stopLocation': {'stopLocationId': 'IJPP:b'}}})
        self.assertEqual(asked[0]['dateTime'], {'earliestDeparture': '2026-10-09T10:19:00+02:00'})
        found = journeys.by_arrival(journeys.build_journeys(data, request(slack=-60), []))
        self.assertEqual(found[0]['effectiveArrival'], '2026-10-09T11:00:00+02:00')
        self.assertEqual((found[0]['transfers'][0]['availableSeconds'], found[0]['transfers'][0]['status']), (-30, 'tight'))

    def test_no_second_pass_without_a_negative_allowance(self):
        data = plan([ride('10:00:00', '10:20:00', 'IJPP:t1'), ride('10:30:00', '11:30:00', 'IJPP:t2')])
        self.assertIs(journeys.bet_on_delays(data, request(slack=0), lambda *a: self.fail('asked OTP')), data)

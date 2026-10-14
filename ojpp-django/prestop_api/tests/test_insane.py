"""Insane mode optimises for arrival time only (request builder, allowance, labels, order, the -1 min pass)."""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import journeys, predictions
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


@override_settings(PRESTOP_PREDICTIONS=True)
class PredictedDelayTests(SimpleTestCase):
    """Contract 2 and A1: insane mode scores transfers with predicted delays, not just the timetable."""

    def journey(self, usual=None, previous=None, second_est=None, now=None, slack=0):
        first = ride('10:00:00', '10:20:00', 'IJPP:t1')
        first['trip']['departureStoptime'] = {'scheduledDeparture': 9 * 3600 + 40 * 60}  # the bus left its first stop at 09:40
        second = ride('10:25:00', '10:50:00', 'IJPP:t2', frm='IJPP:b', to='IJPP:c')
        second['trip']['departureStoptime'] = {'scheduledDeparture': 10 * 3600 + 25 * 60}
        if second_est:
            second['start']['estimated'] = {'time': f'2026-10-09T{second_est}+02:00'}
        with mock.patch.object(predictions, 'usual', return_value=usual or {}), \
                mock.patch.object(predictions, 'previous_trip', side_effect=lambda r, start, d: previous if start == 10 * 3600 + 25 * 60 else None), \
                mock.patch('prestop_api.predictions.time.time', return_value=now or 1791532800):  # 2026-10-09 12:00, after both
            [j] = journeys.build_journeys(plan([first, second]), request(slack=slack), [])
        return j

    def test_a_transfer_that_works_on_paper_but_not_with_the_route_s_usual_four_minutes(self):
        self.assertEqual(self.journey()['transfers'][0]['status'], 'safe')  # 5 min on paper
        j = self.journey(usual={'09:40': 240.0})
        first, second = [l for l in j['legs'] if l['mode'] != 'walk']
        self.assertEqual((first['predictedDelaySeconds'], first['predictionBasis']), (240, 'history'))
        self.assertEqual((second['predictedDelaySeconds'], second['predictionBasis']), (None, None))
        self.assertEqual((j['transfers'][0]['status'], j['transfers'][0]['availableSeconds']), ('tight', 60))
        self.assertEqual(self.journey(usual={'09:40': 360.0})['transfers'][0]['status'], 'missed')

    def test_normal_mode_shows_the_prediction_but_keeps_the_timetable_status(self):
        first = ride('10:00:00', '10:20:00', 'IJPP:t1')
        first['trip']['departureStoptime'] = {'scheduledDeparture': 9 * 3600 + 40 * 60}
        second = ride('10:25:00', '10:50:00', 'IJPP:t2', frm='IJPP:b', to='IJPP:c')
        with mock.patch.object(predictions, 'usual', return_value={'09:40': 360.0}), mock.patch.object(predictions, 'previous_trip', return_value=None):
            [j] = journeys.build_journeys(plan([first, second]), request(insane=False, slack=60), [])
        self.assertEqual(j['legs'][0]['predictionBasis'], 'history')
        self.assertEqual(j['transfers'][0]['status'], 'safe')

    def test_live_beats_previous_trip_beats_history(self):
        j = self.journey(usual={'10:25': 600.0}, second_est='10:27:00')
        self.assertEqual((j['legs'][1]['predictedDelaySeconds'], j['legs'][1]['predictionBasis']), (120, 'live'))
        # The bus for the 10:25 is on its previous trip 10 min late with a 3 min layover; now is 10:00.
        j = self.journey(usual={'10:25': 600.0}, previous={'delaySeconds': 600, 'slack': 180}, now=1791532800 - 2 * 3600)
        self.assertEqual((j['legs'][1]['predictedDelaySeconds'], j['legs'][1]['predictionBasis']), (420, 'previous-trip'))
        self.assertEqual(j['transfers'][0]['availableSeconds'], 300 + 420)  # the leaving bus is running late now: counts
        j = self.journey(usual={'10:25': 600.0})
        self.assertEqual((j['legs'][1]['predictedDelaySeconds'], j['legs'][1]['predictionBasis']), (600, 'history'))
        self.assertEqual(j['transfers'][0]['availableSeconds'], 300)  # "usually late" is no bet for the leaving bus

    def test_no_prediction_without_data_or_when_turned_off(self):
        j = self.journey()
        self.assertEqual([(l['predictedDelaySeconds'], l['predictionBasis']) for l in j['legs'] if l['mode'] != 'walk'], [(None, None)] * 2)
        with override_settings(PRESTOP_PREDICTIONS=False):
            self.assertIsNone(self.journey(usual={'09:40': 240.0})['legs'][0]['predictionBasis'])


@override_settings(PRESTOP_PREDICTIONS=True)
class StayOnVehicleTests(SimpleTestCase):
    """Contract 3: the bus goes on as another line and the rider stays on it."""

    def build(self, block=(None, None), previous=None, learned=None, frm='IJPP:b', interline=False, operators=('IJPP:bus', 'IJPP:bus')):
        first = leg('BUS', '10:00:00', '10:20:00', trip='IJPP:t1')
        second = leg('BUS', '10:22:00', '10:50:00', trip='IJPP:t2', interline=interline)
        first['to']['stop']['gtfsId'], second['from']['stop']['gtfsId'] = 'IJPP:b', frm
        second['route'] = {**second['route'], 'gtfsId': 'IJPP:r2', 'shortName': '2', 'agency': {'gtfsId': operators[1]}}
        first['route']['agency'] = {'gtfsId': operators[0]}
        for raw, b, start in ((first, block[0], 9 * 3600 + 40 * 60), (second, block[1], 10 * 3600 + 22 * 60)):
            raw['trip'].update(blockId=b, departureStoptime={'scheduledDeparture': start})
        with mock.patch.object(predictions, 'previous_trip', return_value=previous), \
                mock.patch.object(predictions, 'usual', return_value={}), \
                mock.patch.object(predictions, '_background', return_value={10 * 3600 + 22 * 60: {'previous': learned}} if learned else {}), \
                mock.patch('prestop_api.sources.stop_group', side_effect=lambda s: [s]):
            [j] = journeys.build_journeys(plan([first, second]), request(slack=0), [])
        return [l for l in j['legs'] if l['mode'] != 'walk'][1], j

    def test_the_same_block_in_the_feed(self):
        second, j = self.build(block=('B7', 'B7'))
        self.assertEqual((second['staysOnVehicle'], second['newTicket']), (True, True))
        self.assertEqual(j['transfers'][0]['status'], 'safe')

    def test_the_vehicle_learned_from_the_feed(self):
        second, _ = self.build(previous={'tripId': 'IJPP:t1', 'vehicleId': 'IJPP:v1', 'delaySeconds': None, 'slack': 120})
        self.assertTrue(second['staysOnVehicle'])
        second, _ = self.build(learned={'routeId': 'IJPP:r', 'start': 9 * 3600 + 40 * 60, 'end': 10 * 3600 + 20 * 60})
        self.assertTrue(second['staysOnVehicle'])

    def test_otp_interline_and_the_ticket_rule(self):
        second, _ = self.build(interline=True, operators=('IJPP:1161', 'IJPP:1161'))
        self.assertTrue(second['staysOnVehicle'])
        self.assertTrue(second['newTicket'])  # an SŽ bus to bus: unknown, so a new ticket
        self.assertFalse(predictions.new_ticket({'routeId': 'R1', 'operatorId': 'IJPP:1161', 'mode': 'rail'},
                                                {'routeId': 'R2', 'operatorId': 'IJPP:1161', 'mode': 'rail'}))
        self.assertFalse(predictions.new_ticket({'routeId': 'R1', 'operatorId': 'LPP:lpp', 'mode': 'bus'}, {'routeId': 'R1', 'operatorId': 'LPP:lpp', 'mode': 'bus'}))

    def test_a_different_bus_or_another_stop_is_a_change(self):
        for kwargs in ({}, {'block': ('B7', 'B8')}, {'block': ('B7', 'B7'), 'frm': 'IJPP:elsewhere'},
                       {'previous': {'tripId': 'IJPP:other', 'vehicleId': 'IJPP:v2', 'delaySeconds': None, 'slack': 0}}):
            second, _ = self.build(**kwargs)
            self.assertNotIn('staysOnVehicle', second, kwargs)
            self.assertNotIn('newTicket', second, kwargs)

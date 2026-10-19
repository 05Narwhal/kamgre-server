"""Replacement buses in depart *and* arrive plans, and the short notices on their legs (spec 2026-10-19 A1).

On the recorded feed and SŽ replacement timetables (fixtures/sztimetables): notice 11198 (Ljubljana – Jesenice /
Beljak, 19. – 23. 10.) runs EC 38 as bus 38/1, which reaches Jesenice at 06:32 where the train would at 06:43;
on 14 Oct LPV 2400 runs by train to Lesce Bled and by bus on, and trains the timetable does not list run as trains.
The LPP detour is the line's own GTFS-RT alert as OTP had it on 2026-10-19.
"""
from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import closures, journey_legs, journeys, leg_alerts, scheduled, sztimetables
from prestop_api.tests.test_timetable_buses import (ALERTS, LOCAL, META, ROAD, TABLES, WALK, DayPlanTests, _Value, feed, hhmm,
                                                    leg_on, plan_for, rides, stop_index, walk)

LPP_DETOUR = {  # recorded 2026-10-19 (alerts from OTP, Slovenian)
    'id': 'alert:QWxlcnQ6TFBQOmMzZThhNGRiLTQyM2YtNDk1NC04MjlkLTdiNzFhMzQ4ZGFjOQ', 'title': 'Postaja Čerinova na obvozu',
    'message': 'Vozilo se ne bo ustavilo na postaji', 'operatorId': 'LPP:lpp',
    'stopIds': ['LPP:010c271e-49ca-45a5-91ac-8ba8d41ee7f3', 'LPP:a769d1e9-8727-4190-b56c-5cdd8a49333d'], 'routeIds': [],
    'kind': 'detour', 'source': 'feed', '_from': 1785880800, '_to': 1793401140,
}


def place(trip: dict, name: str) -> dict:
    s = next(s for s in trip['stops'] if s['name'] == name)
    return {'name': name, 'latitude': s['lat'], 'longitude': s['lon'], 'kind': 'station', 'stopId': s['gtfsId']}


def request(trip: dict, frm: str, to: str, day: str, at: str, mode: str, **extra) -> dict:
    return {'origin': place(trip, frm), 'destination': place(trip, to), 'via': [], 'timeMode': mode, 'pageCursor': None,
            'dateTime': datetime.fromisoformat(f'{day}T{at}').replace(tzinfo=LOCAL), **extra}


def journey(legs: list[dict]) -> dict:
    return {'legs': legs, 'effectiveDeparture': legs[0]['effectiveDeparture'], 'effectiveArrival': legs[-1]['effectiveArrival']}


class Ec38Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = plan_for('20261019')
        cls.ec38 = next(t for t in feed('20261019') if t['route']['shortName'] == 'EC 38')

    def rewrite(self, legs, metas):
        return journey_legs.rewrite(legs, metas, lambda when: self.plan, ROAD)

    def test_ec_38_rides_its_bus_in_a_departure_plan(self):
        legs, _ = self.rewrite([leg_on(self.ec38, 'Ljubljana', 'Jesenice')], [META])
        self.assertEqual(rides(legs), [('BUS 38/1', 'Ljubljana', '05:42', 'Jesenice', '06:32')])
        self.assertEqual((legs[0]['replacesTrain'], legs[0]['mode']), ('EC 38', 'bus'))

    def test_an_arrival_search_looks_as_much_later_as_the_bus_beats_the_train(self):
        # As a train EC 38 reaches Jesenice at 06:43, so OTP asked for "arrive by 06:40" never had it.
        self.assertEqual(hhmm(leg_on(self.ec38, 'Ljubljana', 'Jesenice')['scheduledArrival']), '06:43')
        req = request(self.ec38, 'Ljubljana', 'Jesenice', '2026-10-19', '06:40', 'arriveBy')
        self.assertEqual(journey_legs.search_gain(self.plan, req), 11 * 60)
        asked = []
        journeys.search({**req, 'searchShift': 660, 'modes': {'walk', 'rail'}, 'minTransferSeconds': 180, 'riskMode': 'normal',
                         'operators': [], 'maxTransfers': None},
                        lambda q, v: asked.append(v) or {'planConnection': {'edges': [], 'pageInfo': {}}})
        self.assertEqual(asked[0]['dateTime'], {'latestArrival': '2026-10-19T06:51:00+02:00'})
        self.assertEqual(asked[1]['dateTime'], {'latestArrival': '2026-10-19T06:40:00+02:00'})  # too few in time: as asked too
        # Far from any station a bus beats its train at, nothing moves.
        self.assertEqual(journey_legs.search_gain(self.plan, request(self.ec38, 'Jesenice', 'Ljubljana', '2026-10-19', '06:40', 'arriveBy')), 0)
        # Nor for a trip the bus cannot be part of: from Kranjska Gora it would come from further away than Jesenice.
        gora = {'name': 'Kranjska Gora', 'latitude': 46.4845, 'longitude': 13.7856}
        self.assertEqual(journey_legs.search_gain(self.plan, {**req, 'origin': gora}), 0)

    def test_the_arrival_plan_keeps_the_bus_and_drops_what_the_wider_search_found_too_late(self):
        legs, _ = self.rewrite([leg_on(self.ec38, 'Ljubljana', 'Jesenice')], [META])
        late = leg_on(self.ec38, 'Ljubljana', 'Jesenice')  # as if not replaced: a train arriving 06:43
        req = request(self.ec38, 'Ljubljana', 'Jesenice', '2026-10-19', '06:40', 'arriveBy', searchShift=660)
        kept = journeys.within_time([journey(legs), journey([late])], req)
        self.assertEqual([rides(j['legs']) for j in kept], [[('BUS 38/1', 'Ljubljana', '05:42', 'Jesenice', '06:32')]])

    def test_the_bus_notice_names_the_train(self):
        legs, _ = self.rewrite([leg_on(self.ec38, 'Ljubljana', 'Jesenice')], [META])
        [en] = leg_alerts.add_notices([journey(legs)], ALERTS, 'en')
        self.assertEqual(en['legs'][0]['notices'], [{'kind': 'replacement', 'text': 'Bus instead of train EC 38'}])
        legs, _ = self.rewrite([leg_on(self.ec38, 'Ljubljana', 'Jesenice')], [META])
        [sl] = leg_alerts.add_notices([journey(legs)], ALERTS, 'sl')
        self.assertEqual(sl['legs'][0]['notices'], [{'kind': 'replacement', 'text': 'Avtobus namesto vlaka EC 38'}])


class OctoberFourteenthTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = plan_for('20261014')
        cls.trips = {t['route']['shortName']: t for t in feed('20261014')}

    def rewrite(self, legs, metas):
        return journey_legs.rewrite(legs, metas, lambda when: self.plan, ROAD)

    def test_a_partial_replacement_rides_the_train_and_names_the_bus_stretch(self):
        legs, _ = self.rewrite([leg_on(self.trips['LPV 2400'], 'Ljubljana', 'Jesenice')], [META])
        [j] = leg_alerts.add_notices([journey(legs)], ALERTS, 'en')
        self.assertEqual(rides(j['legs']), [('LPV 2400', 'Ljubljana', '04:40', 'Lesce-Bled', '05:37'),
                                            ('BUS 2400', 'Lesce-Bled', '05:40', 'Jesenice', '05:57')])
        self.assertNotIn('notices', j['legs'][0])
        self.assertEqual(j['legs'][1]['notices'], [{'kind': 'replacement', 'text': 'Bus instead of train LPV 2400 between Lesce-Bled and Jesenice'}])

    def test_a_train_the_timetable_runs_anyway_has_no_replacement_notice(self):
        ride = leg_on(self.trips['LPV 2442'], 'Ljubljana Šiška', 'Kranj')
        ride['alertIds'] = [next(a['id'] for a in ALERTS if closures.notice_id(a) == '11147')]
        journey_legs.unreplaced_notices([ride], lambda when: self.plan, {a['id']: a for a in ALERTS})
        [j] = leg_alerts.add_notices([journey([ride])], ALERTS, 'en')
        self.assertEqual((rides(j['legs'])[0][0], j['legs'][0].get('notices')), ('LPV 2442', None))

    def test_a_bus_leaving_before_the_asked_time_is_dropped_from_a_departure_plan(self):
        ride = leg_on(self.trips['RG 318'], 'Kranj', 'Jesenice')  # the train would leave Kranj at 08:14, its bus 318/3 at 07:47
        legs, _ = self.rewrite([walk(ride), ride], [WALK, META])
        self.assertEqual(rides(legs), [('BUS 318/3', 'Kranj', '07:47', 'Jesenice', '08:32')])
        for at, kept in (('08:00', 0), ('07:40', 1)):
            with self.subTest(at=at):
                req = request(self.trips['RG 318'], 'Kranj', 'Jesenice', '2026-10-14', at, 'departAt')
                self.assertEqual(len(journeys.within_time([journey(legs)], req)), kept)
        # Pages of earlier connections lie before the asked time on purpose.
        req = request(self.trips['RG 318'], 'Kranj', 'Jesenice', '2026-10-14', '08:00', 'departAt', pageCursor='abc')
        self.assertEqual(len(journeys.within_time([journey(legs)], req)), 1)

    def test_a_journey_without_a_replacement_is_left_alone(self):
        ride = leg_on(self.trips['LPV 2442'], 'Ljubljana Šiška', 'Kranj')
        req = request(self.trips['LPV 2442'], 'Ljubljana Šiška', 'Kranj', '2026-10-14', '23:00', 'departAt')
        self.assertEqual(len(journeys.within_time([journey([ride])], req)), 1)


class LppDetourTests(SimpleTestCase):
    def test_a_detour_on_the_leg_becomes_its_notice(self):
        leg = {'id': 'leg:x-0', 'mode': 'bus', 'routeName': '6', 'origin': {'name': 'Bavarski dvor'}, 'destination': {'name': 'Črnuče'},
               'alertIds': [LPP_DETOUR['id']], 'effectiveDeparture': '2026-10-19T08:00:00+02:00', 'effectiveArrival': '2026-10-19T08:20:00+02:00'}
        [j] = leg_alerts.add_notices([journey([leg])], [LPP_DETOUR], 'sl')
        self.assertEqual(j['legs'][0]['notices'], [{'kind': 'detour', 'text': 'Postaja Čerinova na obvozu'}])

    def test_delays_and_plain_information_are_not_notices(self):
        leg = {'id': 'leg:x-0', 'mode': 'rail', 'routeName': 'LPV 2402', 'origin': {'name': 'A'}, 'destination': {'name': 'B'},
               'alertIds': ['alert:d'], 'effectiveDeparture': '2026-10-19T08:00:00+02:00', 'effectiveArrival': '2026-10-19T08:20:00+02:00'}
        [j] = leg_alerts.add_notices([journey([leg])], [{'id': 'alert:d', 'kind': 'delay', 'title': 'Vlak zamuja 6 min'}], 'sl')
        self.assertNotIn('notices', j['legs'][0])


class ColdStartTests(SimpleTestCase):
    """Right after a restart the first requests must not get a plan without the replacement timetables."""

    def test_the_first_read_of_the_timetables_rebuilds_a_deferred_plan_but_a_newer_version_waits(self):
        trips = feed('20261019')
        derive = DayPlanTests().derive
        slot = derive({'key': None}, trips, None)
        self.assertFalse([b for b in slot['synthetic'] if b.get('source') == 'timetable'])
        derive(slot, trips, TABLES, defer_timetables=True)
        self.assertTrue([b for b in slot['synthetic'] if b['route']['shortName'] == 'BUS 38/1'])
        newer = sztimetables.Timetables(TABLES.notices, TABLES.files)
        derive(slot, trips, newer, defer_timetables=True)
        self.assertIs(slot['key'][-1], TABLES)  # the warmer reads it (warm.plans)

    def test_a_request_that_may_wait_waits_for_the_notices(self):
        trips = feed('20261019')
        loaded = ([], [], {}, stop_index(trips))
        answers = iter([None, None, None])
        timetable = mock.Mock(wait=mock.Mock(return_value=_Value(trips)), get_nowait=mock.Mock(return_value=None))
        with mock.patch.object(closures, 'inputs', side_effect=lambda: next(answers, loaded)), mock.patch.object(closures, 'warm'), \
                mock.patch.object(closures.mapping, 'build_alerts', return_value=ALERTS), \
                mock.patch.object(sztimetables, 'current', return_value=TABLES), \
                mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]), \
                mock.patch.object(scheduled, 'timetable', timetable), \
                mock.patch.object(scheduled, '_derived', {'key': None, 'sections': {}, 'synthetic': [], 'by_id': {}, 'suppressed': {}, 'decided': {}}), \
                mock.patch.object(scheduled, 'service_day', return_value=datetime(2026, 10, 19).date()):
            plan = scheduled.plan_at(datetime(2026, 10, 19, 6, 0, tzinfo=LOCAL).timestamp(), wait=6, cold=True)
        self.assertTrue([b for b in plan['synthetic'] if b['route']['shortName'] == 'BUS 38/1'])

"""A trip back to where it starts, through stops on the way, is planned out and back (journeys.plan)."""
from django.test import SimpleTestCase

from prestop_api import journeys
from prestop_api.tests.test_insane import ride

HOME = {'name': 'Home', 'latitude': 46.05, 'longitude': 14.5, 'kind': 'address'}
FOUND = ride('10:00:00', '10:30:00', 'IJPP:found')  # an empty answer would be asked again with wider limits
SCHOOL = {'name': 'School', 'latitude': 46.24, 'longitude': 14.35, 'kind': 'address'}


def request(**overrides):
    body = {'origin': HOME, 'destination': {**HOME, 'name': 'Home again'}, 'via': [SCHOOL], 'dateTime': '2026-10-09T10:00:00+02:00',
            'timeMode': 'departAt', 'modes': ['walk', 'bus', 'rail'], 'minTransferSeconds': 120, **overrides}
    return journeys.parse_request(body, insane_enabled=True)


def answer(*legs):
    return {'planConnection': {'pageInfo': {'hasNextPage': True, 'endCursor': 'next'}, 'edges': [{'node': {'walkTime': 60, 'legs': [l]}} for l in legs]}}


class RoundTripTests(SimpleTestCase):
    def test_out_and_back_are_paired(self):
        asked = []

        def query(_q, variables):
            asked.append(variables)
            if variables['destination']['label'] == 'School':
                return answer(ride('10:00:00', '10:30:00', 'IJPP:out1'), ride('10:20:00', '10:50:00', 'IJPP:out2'))
            return answer(ride('10:31:00', '11:00:00', 'IJPP:tooSoon'), ride('10:35:00', '11:05:00', 'IJPP:back1'), ride('10:55:00', '11:25:00', 'IJPP:back2'))

        data = journeys.plan(request(), query)
        trips = [[l['trip']['gtfsId'] for l in e['node']['legs']] for e in data['planConnection']['edges']]
        self.assertEqual(trips, [['IJPP:out1', 'IJPP:back1'], ['IJPP:out2', 'IJPP:back2']])  # 2 min buffer at School
        self.assertEqual(data['planConnection']['edges'][0]['node']['walkTime'], 120)
        self.assertEqual(data['planConnection']['pageInfo']['endCursor'], 'next')
        self.assertEqual(len(asked), 2)
        self.assertEqual(asked[1]['origin']['label'], 'School')
        self.assertNotIn('after', asked[1])

    def test_a_trip_elsewhere_is_one_request(self):
        asked = []
        journeys.plan(request(destination={**SCHOOL, 'name': 'Kranj', 'latitude': 46.3}), lambda q, v: asked.append(v) or answer(FOUND))
        self.assertEqual(len(asked), 1)

    def test_without_stops_on_the_way_nothing_changes(self):
        asked = []
        journeys.plan(request(via=[]), lambda q, v: asked.append(v) or answer(FOUND))
        self.assertEqual(len(asked), 1)

    def test_a_stop_repeating_the_place_before_it_is_left_out(self):
        asked = []
        kranj = {**SCHOOL, 'name': 'Kranj', 'latitude': 46.3}
        journeys.plan(request(via=[HOME, SCHOOL, SCHOOL], destination=kranj), lambda q, v: asked.append(v) or answer())
        self.assertEqual([v['visit']['label'] for v in asked[0]['via']], ['School'])
        asked.clear()
        journeys.plan(request(via=[SCHOOL, kranj], destination=kranj), lambda q, v: asked.append(v) or answer())
        self.assertEqual([v['visit']['label'] for v in asked[0]['via']], ['School'])

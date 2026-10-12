"""Buses on trips the timetable does not know yet get their line from the stops they serve (sources.infer_trip)."""
from django.test import SimpleTestCase

from prestop_api import sources

ROUTES = {'X:1': {'gtfsId': 'X:1', 'shortName': '6'}, 'X:2': {'gtfsId': 'X:2', 'shortName': '6'}, 'X:3': {'gtfsId': 'X:3', 'shortName': '9'}, 'X:4': {'gtfsId': 'X:4', 'shortName': '9B'}}
PATTERNS = [
    {'routeId': 'X:1', 'stops': ['a', 'b', 'c', 'd', 'e'], 'last': 'Eend'},
    {'routeId': 'X:2', 'stops': ['a', 'b', 'c', 'd'], 'last': 'Dend'},
    {'routeId': 'X:3', 'stops': ['q', 'b', 'r', 's'], 'last': 'Send'},
    {'routeId': 'X:4', 'stops': ['b', 'c', 'd', 'z'], 'last': 'Zend'},
]
INDEX = {'patterns': PATTERNS, 'by_stop': {}}
for i, p in enumerate(PATTERNS):
    for st in p['stops']:
        INDEX['by_stop'].setdefault(st, set()).add(i)


def update(*stops):
    return {'updates': [{'stopId': st} for st in stops]}


class InferTripTests(SimpleTestCase):
    def test_the_line_whose_pattern_serves_the_stops(self):
        self.assertEqual(sources.infer_trip(update('b', 'c', 'd', 'e'), INDEX, ROUTES), {'routeId': 'X:1', 'destination': 'Eend'})

    def test_stops_renamed_in_a_newer_version_still_match_on_the_rest(self):
        self.assertEqual(sources.infer_trip(update('new1', 'a', 'b', 'c', 'd'), INDEX, ROUTES)['routeId'], 'X:2')

    def test_too_few_known_stops_or_two_lines_give_nothing(self):
        self.assertEqual(sources.infer_trip(update('b', 'c'), INDEX, ROUTES), {})
        self.assertEqual(sources.infer_trip(update('b', 'c', 'd'), INDEX, ROUTES), {})  # lines 6 and 9B alike
        self.assertEqual(sources.infer_trip(None, INDEX, ROUTES), {})

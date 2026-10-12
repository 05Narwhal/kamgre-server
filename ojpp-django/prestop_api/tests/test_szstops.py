"""SŽ's own list of replacement-bus stops (szstops.py) and its place among the stop sources (closures.py)."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import closures, szstops

TABLE = [
    {'route': 'Ljubljana – Kranj – Jesenice', 'station': 'Ljubljana', 'lat': 46.058118, 'lon': 14.513669, 'label': 'Nova Avtobusna postaja Ljubljana (peroni 37, 38 in 39).', 'source': 'place_pin'},
    {'route': 'Ljubljana – Kranj – Jesenice', 'station': 'Kranj', 'lat': 46.2390028, 'lon': 14.3484417, 'label': 'Zunanja stran železniške postaje', 'source': 'place_pin'},
    {'route': 'Ljubljana – Kranj – Jesenice', 'station': 'Lesce Bled', 'lat': 46.3607483, 'lon': 14.157908, 'label': 'Avtobusno postajališče Lesce ŽP', 'source': 'place_pin'},
    {'route': 'Ljubljana – Zidani Most – Dobova', 'station': 'Ljubljana', 'lat': 46.0570, 'lon': 14.5110, 'label': 'Other line', 'source': 'place_pin'},
    {'route': 'Ljubljana – Zidani Most – Dobova', 'station': 'Litija', 'lat': 46.0578473, 'lon': 14.8256351, 'label': 'Zunanja stran železniške postaje', 'source': 'directions_destination'},
    {'route': 'Ljubljana – Zidani Most – Dobova', 'station': 'Sava', 'lat': 46.0897641, 'lon': 14.8976687, 'label': 'Zunanja stran železniške postaje', 'source': 'map_camera_only'},
]
LJUBLJANA = {'gtfsId': 'IJPP:1122804', 'name': 'Ljubljana', 'lat': 46.0582, 'lon': 14.5102}


class LookupTests(SimpleTestCase):
    def test_names_match_across_spelling_but_not_other_stations(self):
        self.assertTrue(szstops.same_station('Lesce Bled', 'Lesce-Bled'))
        self.assertTrue(szstops.same_station('Ljubljana', 'Ljubljana'))
        self.assertFalse(szstops.same_station('Ljubljana', 'Ljubljana Zalog'))

    def test_the_line_sharing_the_buses_stations_wins(self):
        to_jesenice = szstops.lookup(LJUBLJANA, ['Ljubljana', 'Kranj', 'Lesce-Bled'], TABLE)
        self.assertEqual((to_jesenice['lat'], to_jesenice['lon']), (46.058118, 14.513669))
        self.assertIn('peroni 37', to_jesenice['label'])
        to_dobova = szstops.lookup(LJUBLJANA, ['Ljubljana', 'Litija'], TABLE)
        self.assertEqual(to_dobova['label'], 'Other line')

    def test_a_camera_centre_is_only_approximate_and_a_far_namesake_is_ignored(self):
        sava = szstops.lookup({'name': 'Sava', 'lat': 46.0890, 'lon': 14.8970}, [], TABLE)
        self.assertTrue(sava['unverified'])
        self.assertIsNone(szstops.lookup({'name': 'Kranj', 'lat': 45.5, 'lon': 13.7}, [], TABLE))

    def test_the_scrape_becomes_one_row_per_line_and_station(self):
        data = {'stops': [
            {'route': 'A – B', 'station': 'A', 'description': 'Nova Avtobusna postaja Ljubljana (peroni 37, 38 in 39). in', 'latitude': 46.1, 'longitude': 14.5, 'coordinate_source': 'place_pin'},
            {'route': 'A – B', 'station': 'A', 'description': 'again', 'latitude': 46.2, 'longitude': 14.6, 'coordinate_source': 'place_pin'},
            {'route': 'A – B', 'station': 'B', 'description': 'Zunanja stran:', 'latitude': None, 'longitude': None},
        ]}
        rows = szstops.from_scrape(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['label'], 'Nova Avtobusna postaja Ljubljana (peroni 37, 38 in 39).')


class ClosureStopTests(SimpleTestCase):
    """Hand-checked overrides still win; SŽ's list beats a guess."""

    def setUp(self):
        patcher = mock.patch.object(szstops, 'rows', return_value=TABLE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_list_beats_the_namesake_guess(self):
        kranj = {'gtfsId': 'IJPP:kranj', 'name': 'Kranj', 'lat': 46.2375, 'lon': 14.3555}
        nearby = [{'name': 'Kranj', 'latitude': 46.2378, 'longitude': 14.3550, 'modes': ['bus']}]
        with mock.patch.object(closures.stopfix, 'replacement_stops', return_value=[]):
            at = closures.replacement_point(kranj, [], nearby, fallback=True, context=['Ljubljana', 'Kranj'])
        self.assertEqual((at['lat'], at['lon'], at['unverified']), (46.2390028, 14.3484417, False))
        self.assertEqual(at['label'], 'Zunanja stran železniške postaje')

    def test_an_override_wins_over_the_list(self):
        with mock.patch.object(closures.stopfix, 'replacement_stops', return_value=[{'lat': 46.0579, 'lon': 14.5121, 'label': 'x'}]):
            at = closures.replacement_point(LJUBLJANA, [], [], fallback=False, context=['Kranj'])
        self.assertEqual((at['lat'], at['lon']), (46.0579, 14.5121))

    def test_real_replacement_buses_move_to_the_listed_stop_too(self):
        with mock.patch.object(closures.stopfix, 'replacement_stops', return_value=[]):
            moved = closures.relocate([dict(LJUBLJANA), {'gtfsId': 'IJPP:kranj', 'name': 'Kranj', 'lat': 46.2375, 'lon': 14.3555}])
        self.assertEqual((moved[0]['lat'], moved[0]['lon']), (46.058118, 14.513669))
        self.assertIn('peroni 37', moved[0]['replacementLabel'])

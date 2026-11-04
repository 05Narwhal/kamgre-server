"""M11: a bay's routed leg never takes a bus round the town when its own line goes straight there; every bay is on its station's ground."""
from unittest import TestCase
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from prestop_api import geometry, platforms, roads

FEED = [[14.0, 46.0], [14.0, 46.004]]
STOPS = [{'lat': 46.0, 'lon': 14.0, 'name': 'Globus'}, {'lat': 46.0042, 'lon': 14.0, 'name': 'Kranj AP', 'parked': True}]
ROUND_THE_TOWN = [[14.0, 46.0], [14.02, 46.0], [14.02, 46.0042], [14.0, 46.0042]]
ALONG_THE_STREET = [[14.0, 46.0], [14.0004, 46.002], [14.0, 46.0042]]


def repaired(leg):
    with patch.object(roads.legs, 'get_many', lambda keys: {k: leg for k in keys}):
        return roads.repair_in_bays(FEED, STOPS)[0]


@override_settings(PRESTOP_VALHALLA_URL='')
class BayLegWays(SimpleTestCase):
    def test_the_long_way_round_keeps_the_feeds_line_and_still_reaches_the_bay(self):
        line = repaired(ROUND_THE_TOWN)
        self.assertLess(geometry.cumulative(line)[-1], 500)
        self.assertEqual(line[-1], [14.0, 46.0042])

    def test_a_routed_leg_of_about_the_lines_length_is_kept(self):
        self.assertIn([14.0004, 46.002], repaired(ALONG_THE_STREET))


class BaysOnTheirGround(TestCase):
    def test_every_bay_is_inside_its_stations_ground(self):
        stations = platforms.read_bays()
        self.assertEqual(set(stations), set(platforms.STATIONS))
        for name, known in stations.items():
            spec = platforms.STATIONS[name]
            for ref, bay in known['bays'].items():
                self.assertLessEqual(geometry.distance([bay['lon'], bay['lat']], [spec['lon'], spec['lat']]), spec['ground'], f'{name} bay {ref}')

"""Bays at big bus stations (platforms.py): where a departure stands and how its bay is learned."""
from datetime import datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from prestop_api import platforms, roads
from prestop_api.models import PlatformSeen

AP = 'IJPP:1126954'
BAYS = {
    '13': {'lat': 46.0580472, 'lon': 14.5145895, 'heading': 29.9, 'path': [[14.5145045, 46.0579443], [14.5146746, 46.05815]]},
    '27': {'lat': 46.05806, 'lon': 14.5157, 'heading': 29.6, 'path': []},
    '37': {'lat': 46.0581476, 'lon': 14.5143907, 'heading': 269.3, 'path': []},
}
LOCAL = ZoneInfo('Europe/Ljubljana')
AT_13 = datetime(2026, 10, 11, 13, 0, tzinfo=LOCAL).timestamp()
BOARD = [
    {'formatted_time': '13:00', 'platform': '13', 'company': 'Nomago', 'online_heading': 'Tolmin'},
    {'formatted_time': '13:00', 'platform': '12', 'company': 'Arriva', 'online_heading': 'Koper'},
    {'formatted_time': '13:10', 'platform': '27-29', 'company': 'FlixBus', 'online_heading': 'Budapest Népliget bus station'},
    {'formatted_time': '13:15', 'platform': '', 'company': 'x', 'online_heading': 'no bay'},
]


class MatchingTests(SimpleTestCase):
    def test_destinations_match_loosely_but_not_other_towns(self):
        self.assertTrue(platforms.same_place('Bohinj Ukanc', 'Ukanc'))
        self.assertTrue(platforms.same_place('Novo mesto', 'Novo mesto AP'))
        self.assertTrue(platforms.same_place('Videm v Dobrepolju', 'Videm (Dobrepolje)'))
        self.assertFalse(platforms.same_place('Koper', 'Tolmin'))

    def test_a_board_platform_becomes_one_known_bay(self):
        self.assertEqual(platforms.first_bay('27-29', BAYS), '27')
        self.assertEqual(platforms.first_bay('37, 38 in 39', BAYS), '37')
        self.assertIsNone(platforms.first_bay('99', BAYS))

    def test_board_rows_without_a_bay_are_skipped(self):
        rows = platforms.board_rows(BOARD)
        self.assertEqual([r['platform'] for r in rows], ['13', '12', '27-29'])

    def test_the_departure_at_that_time_to_that_place_gives_the_bay(self):
        seen = [SimpleNamespace(destination='Tolmin', platform='13', updated=timezone.now()),
                SimpleNamespace(destination='Koper', platform='12', updated=timezone.now())]
        with mock.patch.object(platforms, 'overrides', return_value=[]):
            self.assertEqual(platforms.departure_platform(AP, AT_13, 'Tolmin AP', seen), '13')
            self.assertIsNone(platforms.departure_platform(AP, AT_13, 'Maribor', seen))

    def test_a_hand_set_bay_wins(self):
        with mock.patch.object(platforms, 'overrides', return_value=[{'station': AP, 'time': '13:00', 'destination': 'Tolmin', 'bay': '27'}]):
            self.assertEqual(platforms.departure_platform(AP, AT_13, 'Tolmin', []), '27')


class PlaceTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(platforms, 'bays', side_effect=lambda station: BAYS if station == AP else {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_departure_starts_in_its_bay(self):
        stops = [{'gtfsId': AP, 'name': 'Ljubljana AP', 'lat': 46.057944, 'lon': 14.514695}, {'gtfsId': 'x', 'name': 'Tolmin', 'lat': 46.18, 'lon': 13.73}]
        with mock.patch.object(platforms, 'departure_platform', return_value='13'):
            placed, bay = platforms.place(stops, AT_13, 'Tolmin')
        self.assertEqual((placed[0]['lat'], placed[0]['lon'], placed[0]['bay']), (46.0580472, 14.5145895, '13'))
        self.assertEqual(bay['ref'], '13')
        self.assertEqual(stops[0]['lat'], 46.057944)  # a copy

    def test_an_unknown_departure_or_another_station_stays_put(self):
        stops = [{'gtfsId': AP, 'name': 'Ljubljana AP', 'lat': 46.0, 'lon': 14.0}]
        with mock.patch.object(platforms, 'departure_platform', return_value=None):
            self.assertEqual(platforms.place(stops, AT_13, 'Nowhere'), (stops, None))
        other = [{'gtfsId': 'IJPP:other', 'name': 'Kranj', 'lat': 46.2, 'lon': 14.3}]
        self.assertEqual(platforms.place(other, AT_13, 'x'), (other, None))

    def test_sz_replacement_buses_use_the_bays_their_notice_names_at_the_bus_station_next_door(self):
        station = [{'gtfsId': 'IJPP:1122804', 'name': 'Ljubljana', 'lat': 46.058, 'lon': 14.5137, 'replacementLabel': 'Nova Avtobusna postaja Ljubljana (peroni 37, 38 in 39).'}]
        placed, bay = platforms.place(station, AT_13, 'Jesenice')
        self.assertEqual(bay['ref'], '37')
        self.assertEqual((placed[0]['lat'], placed[0]['lon']), (46.0581476, 14.5143907))


@override_settings(PRESTOP_AP_LJUBLJANA_URL='https://ap.test/api/upcoming')
class LearnTests(TestCase):
    def setUp(self):
        platforms._last_learn.clear()

    def test_the_board_is_remembered_by_time_and_destination_and_polled_at_most_every_few_minutes(self):
        with mock.patch.object(platforms, 'get_json', return_value=BOARD) as board:
            self.assertEqual(platforms.learn(now=1000.0), 3)
            self.assertEqual(platforms.learn(now=1000.0 + 60), 0)
            self.assertEqual(board.call_count, 1)
        with mock.patch.object(platforms, 'overrides', return_value=[]):
            self.assertEqual(platforms.departure_platform(AP, AT_13, 'Tolmin'), '13')
            self.assertEqual(platforms.departure_platform(AP, AT_13, 'Koper'), '12')
        self.assertEqual(PlatformSeen.objects.count(), 3)


@override_settings(PRESTOP_VALHALLA_URL='')
class RerouteTests(SimpleTestCase):
    def test_a_bus_leaving_a_bay_has_its_first_leg_routed_even_when_the_shape_looks_fine(self):
        road = [[14.50 + i * 0.0005, 46.05] for i in range(41)]
        stops = [{'lat': 46.05, 'lon': 14.5002}, {'lat': 46.05, 'lon': 14.51}, {'lat': 46.05, 'lon': 14.52}]
        legs = {roads.leg_key(stops[0], stops[1]): [[14.5002, 46.05], [14.505, 46.0503], [14.51, 46.05]]}
        with mock.patch.object(roads.legs, 'get_many', side_effect=lambda keys: {k: legs[k] for k in keys if k in legs}):
            shape, _ = roads.repair(road, stops, reroute=(0,))
        self.assertIn([14.505, 46.0503], shape)

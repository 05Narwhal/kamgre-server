"""Bays at big bus stations (platforms.py): where a departure stands and how its bay is learned."""
from datetime import datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from prestop_api import platforms, roads
from prestop_api.management.commands import platform_bays
from prestop_api.models import PlatformSeen

AP = 'IJPP:1168813'  # Ljubljana AP in the feed (was IJPP:1126954 until Nov 2026)
OLD_AP = 'IJPP:1126954'
KEY = 'ljubljana-ap'
BAYS = {
    '13': {'lat': 46.0580472, 'lon': 14.5145895, 'heading': 29.9, 'path': [[14.5145045, 46.0579443], [14.5146746, 46.05815]]},
    '27': {'lat': 46.05806, 'lon': 14.5157, 'heading': 29.6, 'path': []},
    '28': {'lat': 46.05807, 'lon': 14.51578, 'heading': 29.6, 'path': []},
    '29': {'lat': 46.05808, 'lon': 14.51586, 'heading': 29.7, 'path': []},
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

    def test_a_range_on_the_board_names_every_bay_in_it(self):
        self.assertEqual(platforms.bay_refs('27-29', BAYS), ['27', '28', '29'])
        self.assertEqual(platforms.bay_refs('13, 27', BAYS), ['13', '27'])
        self.assertEqual(platforms.bay_refs('99', BAYS), [])

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


class UsualBayTests(SimpleTestCase):
    """Departures the board has not shown yet: the bay their destination usually leaves from."""
    def seen(self, *rows):
        return [SimpleNamespace(key=f'{AP}|{hhmm}|{dest.lower()}', destination=dest, platform=bay, updated=timezone.now()) for hhmm, dest, bay in rows]

    def test_the_bay_a_destination_mostly_uses(self):
        seen = self.seen(('07:00', 'Bled', '8'), ('09:00', 'Bled', '8'), ('13:00', 'Bled', '26'), ('13:00', 'Koper', '12'))
        at_1330 = AT_13 + 1800  # no Bled departure seen within DEPARTURE_WINDOW of 13:30
        self.assertEqual(platforms.usual_platform(AP, at_1330, 'Bled AP', seen), '8')
        self.assertIsNone(platforms.usual_platform(AP, at_1330, 'Maribor', seen))

    def test_the_bay_its_own_departure_used_comes_first(self):
        """A5: the 13:05 to Bled (13:00 last timetable, seen at bay 26) usually leaves from 26, not the 8 most Bled
        buses use; a departure with none of its own within the window gets the destination's."""
        seen = self.seen(('07:00', 'Bled', '8'), ('09:00', 'Bled', '8'), ('11:00', 'Bled', '8'), ('13:00', 'Bled', '26'))
        self.assertEqual(platforms.usual_platform(AP, AT_13 + 300, 'Bled', seen), '26')
        self.assertEqual(platforms.usual_platform(AP, AT_13 + 3600, 'Bled', seen), '8')

    def test_a_destinations_own_departures_count_before_namesakes(self):
        seen = self.seen(('07:00', 'Bled', '8'), ('08:00', 'Bled', '8'), ('09:00', 'Bled', '26'), ('10:00', 'Bled shuttle', '30'), ('11:00', 'Bled shuttle', '30'))
        self.assertEqual(platforms.usual_platform(AP, AT_13, 'Bled', seen), '8')
        self.assertEqual(platforms.usual_platform(AP, AT_13, 'Bled shuttle', seen), '30')

    def test_no_usual_bay_when_it_varies(self):
        seen = self.seen(('07:00', 'Nova Gorica', '11'), ('09:00', 'Nova Gorica', '12'), ('11:00', 'Nova Gorica', '13'))
        self.assertIsNone(platforms.usual_platform(AP, AT_13, 'Nova Gorica', seen))

    def test_of_equally_used_bays_the_one_seen_nearest_that_time(self):
        seen = self.seen(('07:00', 'Kranj', '5'), ('12:40', 'Kranj', '8'))
        self.assertEqual(platforms.usual_platform(AP, AT_13, 'Kranj', seen), '8')

    def test_the_departures_own_bay_wins_and_a_usual_one_is_marked(self):
        seen = self.seen(('13:00', 'Bled', '26'), ('07:00', 'Bled', '8'), ('09:00', 'Bled', '8'))
        with mock.patch.object(platforms, 'overrides', return_value=[]):
            self.assertEqual(platforms.platform_for(AP, AT_13, 'Bled', seen), ('26', False))
            self.assertEqual(platforms.platform_for(AP, AT_13 + 3600, 'Bled', seen), ('8', True))
            self.assertEqual(platforms.platform_for(AP, AT_13, 'Maribor', seen), (None, False))

    def test_a_station_has_ground_a_plain_stop_has_none(self):
        self.assertEqual(platforms.origin_area(AP)['radius'], 130)
        self.assertIsNone(platforms.origin_area('IJPP:other'))

class PlaceTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(platforms, 'bays', side_effect=lambda station: BAYS if station == KEY else {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_departure_starts_in_its_bay(self):
        stops = [{'gtfsId': AP, 'name': 'Ljubljana AP', 'lat': 46.057944, 'lon': 14.514695}, {'gtfsId': 'x', 'name': 'Tolmin', 'lat': 46.18, 'lon': 13.73}]
        with mock.patch.object(platforms, 'departure_platform', return_value='13'):
            placed, bay = platforms.place(stops, AT_13, 'Tolmin')
        self.assertEqual((placed[0]['lat'], placed[0]['lon'], placed[0]['bay']), (46.0580472, 14.5145895, '13'))
        self.assertEqual(bay['ref'], '13')
        self.assertFalse(placed[0]['bayUsual'])
        self.assertEqual(stops[0]['lat'], 46.057944)  # a copy

    def test_a_departure_not_announced_yet_stands_in_its_destinations_usual_bay(self):
        stops = [{'gtfsId': AP, 'name': 'Ljubljana AP', 'lat': 46.057944, 'lon': 14.514695}, {'gtfsId': 'x', 'name': 'Koper', 'lat': 45.5, 'lon': 13.7}]
        with mock.patch.object(platforms, 'platform_for', return_value=('27-29', True)):
            placed, bay = platforms.place(stops, AT_13, 'Koper')
        self.assertEqual((placed[0]['bay'], placed[0]['bayUsual'], bay['station']), ('27', True, KEY))
        # Spec 2026-10-18 A3: the rest of the range is where it stands when 27 is taken.
        self.assertEqual([b['ref'] for b in bay['alternates']], ['28', '29'])
        self.assertEqual(bay['alternates'][0]['heading'], 29.6)

    def test_a_bus_ending_at_the_station_parks_in_the_least_used_bays(self):
        # Seen: 13 twice, 27-29 once (each of 27, 28, 29), 37 once, 28 once more.
        seen = [SimpleNamespace(platform=p) for p in ('13', '13', '27-29', '37', '28')]
        parks = platforms.destination_bays(AP, seen)
        order = ('27', '29', '37', '13', '28')  # fewest departures first, then by number
        self.assertEqual([(b['lat'], b['lon']) for b in parks], [(BAYS[r]['lat'], BAYS[r]['lon']) for r in order])
        self.assertEqual(parks[0]['heading'], 29.6)
        self.assertNotIn('ref', parks[0])  # an arrival's bay is never named
        self.assertEqual(platforms.destination_bays('IJPP:other', seen), [])

    def test_a_departure_nothing_names_a_bay_for_waits_in_a_free_one_with_no_number(self):
        stops = [{'gtfsId': AP, 'name': 'Ljubljana AP', 'lat': 46.0, 'lon': 14.0}]
        with mock.patch.object(platforms, 'platform_for', return_value=(None, False)), \
                mock.patch.object(platforms, 'station_seen', return_value=[SimpleNamespace(platform='13')]):
            placed, bay = platforms.place(stops, AT_13, 'Nowhere')
        self.assertEqual((placed[0]['lat'], placed[0]['lon']), (BAYS[bay['ref']]['lat'], BAYS[bay['ref']]['lon']))
        self.assertNotIn('bay', placed[0])  # no number: the board shows nothing and the leg names no bay
        self.assertFalse(bay['named'])
        self.assertEqual({bay['ref'], *(b['ref'] for b in bay['alternates'])}, set(BAYS))  # stable per destination (free_bays)

    def test_a_stop_that_is_no_station_with_bays_stays_put(self):
        other = [{'gtfsId': 'IJPP:other', 'name': 'Kranj', 'lat': 46.2, 'lon': 14.3}]
        self.assertEqual(platforms.place(other, AT_13, 'x'), (other, None))

    def test_only_a_station_with_a_board_announces_bays(self):
        self.assertTrue(platforms.announces(AP))
        self.assertFalse(platforms.announces('kranj-ap'))
        self.assertFalse(platforms.announces('IJPP:other'))

    def test_sz_replacement_buses_use_the_bays_their_notice_names_at_the_bus_station_next_door(self):
        station = [{'gtfsId': 'IJPP:1122804', 'name': 'Ljubljana', 'lat': 46.058, 'lon': 14.5137, 'replacementLabel': 'Nova Avtobusna postaja Ljubljana (peroni 37, 38 in 39).'}]
        placed, bay = platforms.place(station, AT_13, 'Jesenice')
        self.assertEqual(bay['ref'], '37')
        self.assertEqual((placed[0]['lat'], placed[0]['lon']), (46.0581476, 14.5143907))


class PlainNameTests(SimpleTestCase):
    def test_a_plain_station_is_its_place_name_and_the_others_must_say_bus_station(self):
        plain, named = platforms.STATIONS['idrija-ap'], platforms.STATIONS['kranj-ap']
        self.assertTrue(platforms._station_name('Idrija', plain))
        self.assertFalse(platforms._station_name('Idrija Uta', plain))
        self.assertTrue(platforms._station_name('Kranj AP', named))
        self.assertFalse(platforms._station_name('Kranj', named))


def _way(ref, points, **tags):
    return {'type': 'way', 'tags': {'public_transport': 'platform', **({'ref': ref} if ref else {}), **tags},
            'geometry': [{'lon': x, 'lat': y} for x, y in points]}


class BaysFromTests(SimpleTestCase):
    ROAD = {'type': 'way', 'tags': {'highway': 'service'}, 'geometry': [{'lon': 15.6, 'lat': 46.0}, {'lon': 15.601, 'lat': 46.0}]}

    def test_a_platform_way_is_the_bay_and_the_bus_faces_the_nearer_road(self):
        bays = platform_bays.bays_from([self.ROAD, _way('7', [(15.6005, 46.0006), (15.6005, 46.0004)]), _way('8', [(15.6006, 46.0004), (15.6006, 46.0006)])])
        self.assertEqual(sorted(bays), ['7', '8'])
        self.assertEqual((bays['7']['lat'], bays['7']['lon'], bays['7']['heading']), (46.0005, 15.6005, 180.0))
        self.assertEqual(bays['8']['heading'], 180.0)  # drawn the other way round: still facing the road
        self.assertEqual(bays['7']['path'], [[15.6005, 46.0006], [15.6005, 46.0004]])

    def test_bays_in_a_row_face_the_same_way_whichever_end_is_nearer_a_road(self):
        north = {'type': 'way', 'tags': {'highway': 'service'}, 'geometry': [{'lon': 15.6009, 'lat': 46.00065}, {'lon': 15.601, 'lat': 46.00065}]}
        bays = platform_bays.bays_from([self.ROAD, north, _way('1', [(15.6003, 46.0003), (15.6003, 46.0001)]), _way('2', [(15.6004, 46.0003), (15.6004, 46.0001)]),
                                        _way('3', [(15.6009, 46.0004), (15.6009, 46.0006)])])  # 3's nearer road is the north one
        self.assertEqual([bays[r]['heading'] for r in '123'], [180.0, 180.0, 180.0])
        self.assertEqual(bays['3']['path'], [[15.6009, 46.0006], [15.6009, 46.0004]])

    def test_a_bay_drawn_as_an_outline_is_stood_in_along_its_long_side(self):
        box = [(15.6005, 46.0004), (15.60056, 46.0004), (15.60056, 46.00055), (15.6005, 46.00055), (15.6005, 46.0004)]
        bay = platform_bays.bays_from([self.ROAD, _way('1', box, area='yes')])['1']
        self.assertAlmostEqual(bay['lat'], 46.000475, places=6)
        self.assertAlmostEqual(bay['lon'], 15.60053, places=6)
        self.assertEqual(bay['heading'], 180.0)

    def test_railway_platforms_shared_refs_and_stop_nodes_are_no_bays(self):
        line = [(15.6005, 46.0006), (15.6005, 46.0004)]
        self.assertEqual(platform_bays.bays_from([self.ROAD, _way('1', line, railway='platform'), _way('2;3', line), _way('', line),
                                                  {'type': 'node', 'lat': 46.0, 'lon': 15.6005, 'tags': {'public_transport': 'platform', 'ref': '001'}}]), {})

    def test_a_platform_way_is_no_road_for_a_numbered_node(self):
        node = {'type': 'node', 'lat': 46.0005, 'lon': 15.6005, 'tags': {'public_transport': 'platform', 'local_ref': '5'}}
        self.assertEqual(platform_bays.bays_from([node, _way('', [(15.6005, 46.0006), (15.6005, 46.0004)])]), {})
        self.assertEqual(platform_bays.bays_from([node, self.ROAD]), {})  # 55 m from the road: nowhere to stand


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


def _stop(stop_id, name, lat, lon, modes=('bus',)):
    return {'id': stop_id, 'name': name, 'latitude': lat, 'longitude': lon, 'modes': list(modes)}


RAIL = _stop('IJPP:1122804', 'Ljubljana', 46.058509, 14.512924, ('bus', 'rail'))


class ResolveTests(SimpleTestCase):
    """Spec 2026-11-03 L1: the feed renumbered Ljubljana AP; a station with bays is found by place and name."""

    def resolved(self, stops):
        found = platforms.resolve(stops)
        return mock.patch.object(platforms, '_resolved', return_value=found)

    def test_a_renumbered_station_is_found_by_place_and_name(self):
        stops = [_stop('IJPP:9999', 'Ljubljana AP', 46.057944, 14.514695), RAIL, _stop('LPP:1', 'Bavarski dvor', 46.0585, 14.5135)]
        self.assertEqual(platforms.resolve(stops)[KEY], {'ids': ['IJPP:9999'], 'nextDoor': ['IJPP:1122804']})
        with self.resolved(stops):
            self.assertEqual(platforms.station_key('IJPP:9999'), KEY)
            self.assertEqual(platforms.station_key(OLD_AP), KEY)  # rows and links under the old id still count
            self.assertIsNone(platforms.station_key('LPP:1'))
            self.assertNotIn(KEY, platforms.unresolved())
            self.assertEqual(platforms.origin_area('IJPP:9999')['radius'], 130)

    def test_a_moved_stop_is_found_inside_the_radius_and_a_railway_station_is_never_the_bus_station(self):
        moved = _stop('IJPP:8888', 'Avtobusna postaja Ljubljana', 46.0592, 14.5150)  # ~130 m north
        self.assertEqual(platforms.resolve([RAIL, moved])[KEY]['ids'], ['IJPP:8888'])
        far = _stop('IJPP:7777', 'Ljubljana AP', 46.0650, 14.5150)  # ~780 m away: another stop
        self.assertEqual(platforms.resolve([RAIL, far])[KEY]['ids'], [])

    def test_a_city_feeds_pole_named_after_the_station_is_not_the_station(self):
        # N7: Kranj's city buses stop at their own "Kranj AP" poles on the street; taken as the station, they were put in
        # intercity bays (and Marprom's "AP Mlinska" beside Maribor AP likewise). City feeds keep their own points.
        stops = [_stop('IJPP:1121237', 'Kranj AP', 46.245851, 14.354465), _stop('MOKranj:112', 'Kranj AP', 46.24590, 14.35460),
                 _stop('MARPROM:7', 'AP Mlinska', 46.5598, 15.6560), _stop('IJPP:1127365', 'Maribor AP', 46.55956, 15.65575)]
        found = platforms.resolve(stops)
        self.assertEqual(found['kranj-ap']['ids'], ['IJPP:1121237'])
        self.assertEqual(found['maribor-ap']['ids'], ['IJPP:1127365'])
        with self.resolved(stops):
            self.assertIsNone(platforms.station_key('MOKranj:112'))
            self.assertEqual(platforms.station_key('IJPP:1121237'), 'kranj-ap')

    def test_a_station_matching_no_stop_is_reported(self):
        with self.resolved([RAIL, _stop('IJPP:1', 'Kranj AP', 46.2463, 14.3547), _stop('IJPP:2', 'Maribor AP', 46.55956, 15.65575), _stop('IJPP:3', 'Idrija', 46.00098, 14.02571)]):
            self.assertEqual(platforms.unresolved(), [KEY])
        with mock.patch.object(platforms, '_resolved', return_value=None):  # no stop index yet: nothing to report
            self.assertEqual(platforms.unresolved(), [])

    def test_replacement_buses_find_the_renumbered_railway_station_next_door(self):
        stops = [_stop('IJPP:1168813', 'Ljubljana AP', 46.057944, 14.514695), {**RAIL, 'id': 'IJPP:5555'}]
        with self.resolved(stops), mock.patch.object(platforms, 'bays', side_effect=lambda s: BAYS if s == KEY else {}):
            self.assertEqual(platforms.next_door('IJPP:5555'), KEY)
            bay = platforms.bay_for({'gtfsId': 'IJPP:5555'}, AT_13, 'Jesenice', 'Avtobusna postaja Ljubljana (peroni 37, 38 in 39)')
        self.assertEqual(bay['ref'], '37')

    def test_the_bay_file_is_keyed_by_station(self):
        self.assertGreaterEqual(len(platforms.read_bays()[KEY]['bays']), 40)
        self.assertEqual(len(platforms.bays(AP)), len(platforms.bays(KEY)))


class OldRowsTests(TestCase):
    def test_rows_under_the_old_feed_id_are_still_read_and_the_newer_row_of_a_departure_wins(self):
        PlatformSeen.objects.create(key=f'{OLD_AP}|13:00|tolmin', platform='13', destination='Tolmin', operator='Nomago')
        PlatformSeen.objects.create(key=f'{OLD_AP}|13:00|koper', platform='12', destination='Koper', operator='Arriva')
        PlatformSeen.objects.create(key=f'{KEY}|13:00|koper', platform='14', destination='Koper', operator='Arriva')
        PlatformSeen.objects.create(key='IJPP:other|13:00|koper', platform='1', destination='Koper', operator='x')
        with mock.patch.object(platforms, 'overrides', return_value=[]):
            self.assertEqual(platforms.departure_platform(AP, AT_13, 'Tolmin'), '13')
            self.assertEqual(platforms.departure_platform(AP, AT_13, 'Koper'), '14')
        self.assertEqual(len(platforms.station_seen(AP)), 2)
        self.assertEqual(platforms.station_seen('IJPP:other'), [])

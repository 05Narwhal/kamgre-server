"""M10: bays set by hand for stations whose board names none (platforms.py, data/platform_overrides.csv)."""
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from prestop_api import platforms, sources, trips

LOCAL = ZoneInfo('Europe/Ljubljana')
AT_0615 = datetime(2026, 11, 10, 6, 15, tzinfo=LOCAL).timestamp()
AT_0700 = datetime(2026, 11, 10, 7, 0, tzinfo=LOCAL).timestamp()
KRANJ = 'kranj-ap'
KRANJ_STOP = 'IJPP:1121237'
KRANJ_BAYS = {r: {'lat': 46.2463 + int(r) / 1e5, 'lon': 14.3547, 'heading': 90.0, 'path': []} for r in ('3', '4', '5', '7', '9')}
HEADER = '# a comment\nstation,time,destination,bay,note\n'


def hand_rows(text, bays=None):
    """Patch the hand-set bays file with `text` (rows after the header), Kranj's bays with `bays`."""
    folder = tempfile.TemporaryDirectory()
    path = Path(folder.name) / 'platform_overrides.csv'
    path.write_text(HEADER + text, encoding='utf-8')
    patches = [mock.patch.object(platforms, 'OVERRIDES', path),
               mock.patch.object(platforms, 'bays', side_effect=lambda s: (KRANJ_BAYS if platforms.station_key(s) == KRANJ else {}) if bays is None else bays),
               mock.patch.object(platforms, 'station_seen', return_value=[]),
               mock.patch.object(platforms, '_warned', set())]
    return folder, patches


class HandBayCase(SimpleTestCase):
    rows = ''

    def setUp(self):
        folder, patches = hand_rows(self.rows)
        self.addCleanup(folder.cleanup)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class NoRowsTests(HandBayCase):
    """Kranj, Maribor and Idrija have no board: with no hand row, no number anywhere."""

    def test_no_number_on_a_board_a_trip_or_a_leg(self):
        for key in ('kranj-ap', 'maribor-ap', 'idrija-ap'):
            self.assertEqual(platforms.platform_for(key, AT_0615, 'Ljubljana', []), (None, False), key)
            stops = [{'gtfsId': key, 'name': 'x', 'lat': 0, 'lon': 0}]
            known = {'1': {'lat': 1.0, 'lon': 2.0, 'heading': 0, 'path': []}, '2': {'lat': 1.1, 'lon': 2.1, 'heading': 0, 'path': []}}
            with mock.patch.object(platforms, 'bays', return_value=known):
                placed, bay = platforms.place(stops, AT_0615, 'Ljubljana')
            self.assertFalse(bay['named'], key)
            self.assertNotIn('bay', placed[0], key)
            self.assertNotIn('bayUsual', placed[0], key)
            self.assertFalse(platforms.announces(key), key)


class TimedRowTests(HandBayCase):
    rows = 'kranj-ap,06:15,Ljubljana,5,photographed\nkranj-ap,,Ljubljana,7,\n'

    def test_a_row_with_a_time_is_that_departures_bay_and_certain(self):
        self.assertEqual(platforms.platform_for(KRANJ, AT_0615, 'Ljubljana AP', []), ('5', False))

    def test_a_row_with_no_time_is_every_other_departure_to_that_place_and_usual(self):
        self.assertEqual(platforms.platform_for(KRANJ, AT_0700, 'Ljubljana', []), ('7', True))
        self.assertEqual(platforms.platform_for(KRANJ, AT_0700, 'Maribor', []), (None, False))

    def test_the_station_may_be_named_by_its_feed_stop(self):
        self.assertEqual(platforms.platform_for(KRANJ_STOP, AT_0615, 'Ljubljana', []), ('5', False))
        self.assertEqual(platforms.platform_for(KRANJ_STOP, AT_0700, 'Ljubljana', []), ('7', True))

    def test_other_stations_are_untouched(self):
        self.assertEqual(platforms.platform_for('maribor-ap', AT_0615, 'Ljubljana', []), (None, False))
        self.assertEqual(platforms.platform_for('IJPP:other', AT_0615, 'Ljubljana', []), (None, False))

    def test_the_board_beats_a_row_with_no_time_and_a_row_with_a_time_beats_the_board(self):
        board = SimpleNamespace(key=f'{KRANJ}|07:00|ljubljana', destination='Ljubljana', platform='9', updated=1)
        self.assertEqual(platforms.platform_for(KRANJ, AT_0700, 'Ljubljana', [board]), ('9', False))
        board.key = f'{KRANJ}|06:15|ljubljana'
        self.assertEqual(platforms.platform_for(KRANJ, AT_0615, 'Ljubljana', [board]), ('5', False))

    def test_a_row_with_no_time_beats_the_boards_history(self):
        history = [SimpleNamespace(key=f'{KRANJ}|09:00|ljubljana', destination='Ljubljana', platform='3', updated=1)] * 3
        self.assertEqual(platforms.platform_for(KRANJ, AT_0700, 'Ljubljana', history), ('7', True))


class ReachTests(HandBayCase):
    rows = 'kranj-ap,06:15,Ljubljana,5,\nkranj-ap,,Škofja Loka,7,\n'

    def first_stop(self, destination, at):
        stops = [{'gtfsId': KRANJ_STOP, 'name': 'Kranj AP', 'lat': 46.0, 'lon': 14.0}, {'gtfsId': 'x', 'name': destination, 'lat': 46.2, 'lon': 14.0}]
        placed, bay = platforms.place(stops, at, destination)
        return placed[0], bay

    def test_a_trips_first_stop_stands_in_the_bay(self):
        stop, bay = self.first_stop('Ljubljana', AT_0615)
        self.assertEqual((stop['bay'], stop['bayUsual'], bay['named']), ('5', False, True))
        self.assertEqual((stop['lat'], stop['lon']), (KRANJ_BAYS['5']['lat'], KRANJ_BAYS['5']['lon']))

    def test_a_usual_row_moves_the_stop_and_says_usual(self):
        stop, _ = self.first_stop('Škofja Loka', AT_0700)
        self.assertEqual((stop['bay'], stop['bayUsual']), ('7', True))

    def test_the_built_trip_names_the_platform_and_never_waits_for_a_board(self):
        t = {'gtfsId': 'IJPP:t1', 'tripHeadsign': 'Škofja Loka', 'directionId': 0,
             'route': {'gtfsId': 'IJPP:r1', 'shortName': '1', 'mode': 'BUS', 'agency': {'gtfsId': 'IJPP:a'}},
             'stoptimes': [{'stopPosition': 0, 'stop': {'gtfsId': KRANJ_STOP, 'name': 'Kranj AP', 'lat': 46.2463, 'lon': 14.3547}, 'scheduledDeparture': 7 * 3600},
                           {'stopPosition': 1, 'stop': {'gtfsId': 'x', 'name': 'Škofja Loka', 'lat': 46.16, 'lon': 14.3}, 'scheduledDeparture': 7 * 3600 + 900}],
             'shapeCoordinates': [[14.3547, 46.2463], [14.3, 46.16]]}
        with mock.patch.object(trips, '_corrected', side_effect=lambda stops, replacement=False: stops), \
                mock.patch.object(trips, 'road_shape', side_effect=lambda raw, *a, **k: (raw, True)), \
                mock.patch.object(trips, '_first_departure', return_value=AT_0700), \
                mock.patch.object(trips.stopfix, 'renamed', side_effect=lambda sid, name: name):
            static = trips._build_static(t)
        first = static['stops'][0]
        self.assertEqual((first['platform'], first['platformUsual']), ('7', True))
        self.assertFalse(static['bayPending'])  # Kranj's board announces nothing: nothing to wait for

    def test_the_station_board_row(self):
        entries = [{'mode': 'bus', 'scheduledAt': datetime.fromtimestamp(AT_0615, LOCAL).astimezone(ZoneInfo('UTC')).isoformat(), 'destination': 'Ljubljana'},
                   {'mode': 'bus', 'scheduledAt': datetime.fromtimestamp(AT_0700, LOCAL).astimezone(ZoneInfo('UTC')).isoformat(), 'destination': 'Škofja Loka'},
                   {'mode': 'bus', 'scheduledAt': datetime.fromtimestamp(AT_0700, LOCAL).astimezone(ZoneInfo('UTC')).isoformat(), 'destination': 'Maribor'}]
        from prestop_api import replacement, sz
        with mock.patch.object(replacement, 'board_rows', side_effect=lambda e, *a, **k: e), \
                mock.patch.object(sources, 'stop_names', return_value={}), \
                mock.patch.object(sz, 'live', SimpleNamespace(get=lambda: {})):
            rows = sources._with_live_platforms(entries, KRANJ_STOP)
        self.assertEqual([(r.get('platform'), r.get('platformUsual')) for r in rows], [('5', None), ('7', True), (None, None)])


class BadRowTests(HandBayCase):
    rows = 'kranj-ap,06:15,Ljubljana,99,\nnowhere-ap,06:15,Ljubljana,5,\n'

    def test_a_bay_with_no_position_is_logged_once_and_never_moves_a_bus(self):
        stops = [{'gtfsId': KRANJ_STOP, 'name': 'Kranj AP', 'lat': 46.0, 'lon': 14.0}]
        with self.assertLogs('prestop_api.platforms', 'WARNING') as logs:
            placed, bay = platforms.place(stops, AT_0615, 'Ljubljana')
            platforms.place(stops, AT_0615, 'Ljubljana')
        self.assertFalse(bay['named'])
        self.assertNotIn('bay', placed[0])
        self.assertEqual(sum("'99'" in m for m in logs.output), 1)

    def test_a_row_for_a_station_that_does_not_exist_is_ignored_and_logged(self):
        with self.assertLogs('prestop_api.platforms', 'WARNING') as logs:
            rows = platforms.overrides()
        self.assertEqual([r['station'] for r in rows], ['kranj-ap'])
        self.assertTrue(any('nowhere-ap' in m for m in logs.output))

"""M11: bus trips and the line page's patterns start and end in a bay, at every station with bays."""
from unittest import TestCase
from unittest.mock import patch

from prestop_api import platforms, trips

KNOWN = {str(n): {'lat': 46.0 + n / 10000, 'lon': 14.0, 'heading': 10.0, 'path': []} for n in range(1, 13)}
STATION = 'IJPP:1121237'  # Kranj AP, no board: no bay is ever named
OTHER = 'IJPP:9'


def stop(stop_id, name, lat=46.3, lon=14.2):
    return {'gtfsId': stop_id, 'name': name, 'lat': lat, 'lon': lon}


class BayEnds(TestCase):
    def setUp(self):
        for name, value in (('bays', lambda s: KNOWN if platforms.station_key(s) else {}), ('station_seen', lambda s: []), ('overrides', lambda: [])):
            p = patch.object(platforms, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_a_trip_ending_at_a_station_ends_in_a_bay_and_names_none(self):
        stops, bay = platforms.place([stop(OTHER, 'Ljubljana'), stop(STATION, 'Kranj AP')], 1.0, 'Kranj AP')
        self.assertIsNone(bay)
        last = stops[-1]
        self.assertTrue(last['parked'])
        self.assertIn((last['lat'], last['lon']), {(b['lat'], b['lon']) for b in KNOWN.values()})
        self.assertNotIn('bay', last)
        self.assertEqual(last['gtfsId'], STATION)  # still that stop, only drawn in the bay

    def test_it_ends_in_the_first_bay_it_may_park_in(self):
        stops, _ = platforms.place([stop(OTHER, 'Ljubljana'), stop(STATION, 'Kranj AP')], 1.0, 'Kranj AP')
        first = platforms.destination_bays(STATION, towards='Ljubljana')[0]
        self.assertEqual((stops[-1]['lat'], stops[-1]['lon']), (first['lat'], first['lon']))

    def test_the_free_bay_stays_the_same_whatever_the_day_and_differs_by_line(self):
        at = {t: platforms.place([stop(STATION, 'Kranj AP'), stop(OTHER, 'Ljubljana')], t, 'Ljubljana')[1]['ref'] for t in (1_000.0, 90_000.0, None)}
        self.assertEqual(len(set(at.values())), 1)
        towns = ['Ljubljana', 'Jesenice', 'Bled', 'Radovljica', 'Škofja Loka', 'Tržič']
        self.assertGreater(len({platforms.free_bays('kranj-ap', KNOWN, t)[0] for t in towns}), 1)

    def test_free_bays_are_the_least_used_rotated_with_none_lost(self):
        order = platforms.free_bays('kranj-ap', KNOWN, 'Bled')
        self.assertEqual(len(order), platforms.PARK_BAYS)
        self.assertEqual(set(order), set(platforms.least_used('kranj-ap', KNOWN)[:platforms.PARK_BAYS]))

    def test_a_stop_that_is_no_station_is_left_alone(self):
        given = [stop(OTHER, 'Ljubljana'), stop('IJPP:10', 'Bled')]
        stops, bay = platforms.place(given, 1.0, 'Bled')
        self.assertIsNone(bay)
        self.assertEqual(stops, given)

    def test_a_single_stop_is_not_parked(self):
        stops, _ = platforms.place([stop(STATION, 'Kranj AP')], 1.0, 'Kranj AP')
        self.assertNotIn('parked', stops[0])

    def test_the_road_is_routed_into_the_bay_and_the_line_reaches_it(self):
        stops, bay = platforms.place([stop(STATION, 'Kranj AP'), stop(OTHER, 'Middle', 46.1), stop(STATION, 'Kranj AP')], 1.0, 'Kranj AP')
        road = [[14.1, 46.01], [14.1, 46.2]]  # the router stops on the street beside both bays
        with patch.object(trips.roads, 'repair', return_value=(road, True)) as repair:
            line, _ = trips.road_shape([], stops, 'bus', None, from_bay=bool(bay))
        self.assertEqual(repair.call_args.kwargs['reroute'], (0, 1))
        self.assertEqual(line[0], [stops[0]['lon'], stops[0]['lat']])
        self.assertEqual(line[-1], [stops[-1]['lon'], stops[-1]['lat']])

    def test_a_pattern_on_the_line_page_starts_and_ends_as_its_trips_do(self):
        route = {'gtfsId': 'IJPP:1', 'mode': 'BUS', 'agency': {}, 'patterns': [{
            'code': 'p', 'headsign': 'Kranj AP', 'directionId': 0,
            'stops': [stop(STATION, 'Kranj AP'), stop(OTHER, 'Ljubljana')],
            'tripsForDate': [{'gtfsId': 't', 'departureStoptime': {'serviceDay': 1_000, 'scheduledDeparture': 60}}]}]}
        with patch.object(trips, '_corrected', side_effect=lambda s, r=False: s), patch.object(trips.roads, 'repair', side_effect=lambda raw, s, *a, **k: ([[x['lon'], x['lat']] for x in s], True)):
            line, _ = trips.build_line(route, trips.service_day())
        pattern = line['patterns'][0]
        placed, bay = platforms.place([stop(STATION, 'Kranj AP'), stop(OTHER, 'Ljubljana')], 1_060.0, 'Ljubljana')
        self.assertEqual(pattern['geometry'][0], [placed[0]['lon'], placed[0]['lat']])
        self.assertEqual(pattern['stops'][0]['latitude'], round(bay['lat'], 6))
        self.assertNotIn('platform', pattern['stops'][0])  # a line page names no bay

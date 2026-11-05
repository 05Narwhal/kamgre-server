"""M11: a planner's bus leg starts and ends where its trip's own line does, in a bay, and the walk reaches it."""
from unittest import TestCase
from unittest.mock import patch

from prestop_api import journeys, platforms

KNOWN = {str(n): {'lat': 46.0 + n / 10000, 'lon': 14.0, 'heading': 10.0, 'path': []} for n in range(1, 13)}
STATION = 'IJPP:1121237'  # Kranj AP
OTHER = 'IJPP:9'


def place(stop_id, name, lat=46.3, lon=14.2):
    return {'name': name, 'lat': lat, 'lon': lon, 'stop': {'gtfsId': stop_id}}


def raw_leg(start, end, first, last):
    """OTP's leg from `start` to `end` of a trip from `first` to `last`."""
    return {'start': {'scheduledTime': '2026-11-04T10:00:00+01:00'}, 'from': start, 'to': end,
            'trip': {'stoptimes': [{'stop': {'gtfsId': s['stop']['gtfsId'], 'name': s['name']}} for s in (first, last)]}}


def flat(stop):
    return {**stop, 'gtfsId': stop['stop']['gtfsId']}


class LegBays(TestCase):
    def setUp(self):
        for name, value in (('bays', lambda s: KNOWN if platforms.station_key(s) else {}), ('station_seen', lambda s: []), ('overrides', lambda: [])):
            p = patch.object(platforms, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_a_leg_of_a_whole_trip_ends_where_the_trip_does(self):
        start, end = place(STATION, 'Kranj AP'), place(OTHER, 'Jesenice')
        trip, trip_bay = platforms.place([flat(start), flat(end)], 1.0, 'Jesenice')
        stops, bay = journeys._leg_in_bays(raw_leg(start, end, start, end), [start, end])
        self.assertEqual((stops[0]['lat'], stops[0]['lon']), (trip[0]['lat'], trip[0]['lon']))
        self.assertEqual(bay['ref'], trip_bay['ref'])
        self.assertNotIn('parked', stops[-1])
        back, _ = platforms.place([flat(end), flat(start)], 1.0, 'Kranj AP')
        stops, bay = journeys._leg_in_bays(raw_leg(end, start, end, start), [end, start])
        self.assertIsNone(bay)
        self.assertTrue(stops[-1]['parked'])
        self.assertEqual((stops[-1]['lat'], stops[-1]['lon']), (back[-1]['lat'], back[-1]['lon']))

    def test_boarding_on_the_way_parks_as_the_whole_trip_does(self):
        first, on_way, last = place(OTHER, 'Jesenice'), place('IJPP:10', 'Lesce'), place(STATION, 'Kranj AP')
        whole, _ = platforms.place([flat(first), flat(last)], 1.0, 'Kranj AP')
        stops, _ = journeys._leg_in_bays(raw_leg(on_way, last, first, last), [on_way, last])
        self.assertEqual((stops[-1]['lat'], stops[-1]['lon']), (whole[-1]['lat'], whole[-1]['lon']))

    def test_a_station_the_trip_only_calls_at_stays_on_the_feeds_point(self):
        first, station, last = place(OTHER, 'Jesenice'), place(STATION, 'Kranj AP'), place('IJPP:10', 'Ljubljana')
        stops, bay = journeys._leg_in_bays(raw_leg(station, last, first, last), [station, last])
        self.assertIsNone(bay)
        self.assertEqual((stops[0]['lat'], stops[0]['lon']), (station['lat'], station['lon']))
        stops, _ = journeys._leg_in_bays(raw_leg(first, station, first, last), [first, station])
        self.assertNotIn('parked', stops[-1])
        self.assertEqual((stops[-1]['lat'], stops[-1]['lon']), (station['lat'], station['lon']))

    def test_the_walk_goes_on_to_the_bay_on_both_sides(self):
        feed = {'stopId': STATION, 'latitude': 46.5, 'longitude': 14.5}
        bay = {**feed, 'latitude': 46.0001, 'longitude': 14.0}
        walk_in = {'mode': 'walk', 'origin': {'latitude': 1, 'longitude': 2}, 'destination': feed, 'geometry': [[2, 1], [14.5, 46.5]]}
        bus = {'mode': 'bus', 'origin': bay, 'destination': bay, 'geometry': [[14.0, 46.0001], [14.0, 46.0001]]}
        walk_out = {'mode': 'walk', 'origin': feed, 'destination': {'latitude': 1, 'longitude': 2}, 'geometry': [[14.5, 46.5], [2, 1]]}
        journeys.walks_reach_bays([walk_in, bus, walk_out])
        self.assertEqual(walk_in['geometry'][-1], [14.0, 46.0001])
        self.assertEqual(walk_in['destination'], bay)
        self.assertEqual(walk_out['geometry'][0], [14.0, 46.0001])
        self.assertEqual(walk_out['origin'], bay)

    def test_a_walk_to_another_stop_is_left_alone(self):
        walk = {'mode': 'walk', 'origin': {}, 'destination': {'stopId': OTHER, 'latitude': 1, 'longitude': 2}, 'geometry': [[0, 0], [2, 1]]}
        bus = {'mode': 'bus', 'origin': {'stopId': STATION, 'latitude': 3, 'longitude': 4}, 'destination': {}, 'geometry': []}
        journeys.walks_reach_bays([walk, bus])
        self.assertEqual(walk['geometry'], [[0, 0], [2, 1]])

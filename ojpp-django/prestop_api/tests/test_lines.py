"""Line screen: each variant (pattern) lists today's departures."""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import trips

DAY = 1791583200  # 2026-10-10 00:00 Europe/Ljubljana (service day start)


def otp_trip(trip_id, seconds):
    return {'gtfsId': trip_id, 'departureStoptime': {'scheduledDeparture': seconds, 'serviceDay': DAY}}


LINE_PAYLOAD = {
    'gtfsId': 'IJPP:65041', 'shortName': 'IC 509', 'longName': 'Ljubljana - Koper', 'mode': 'RAIL', 'color': None,
    'agency': {'gtfsId': 'IJPP:1161', 'name': 'SŽ'},
    'patterns': [{
        'code': 'IJPP:65041:0:01', 'directionId': 0, 'headsign': 'Koper',
        'stops': [{'gtfsId': 'IJPP:a', 'name': 'Ljubljana', 'lat': 46.0583, 'lon': 14.5108}, {'gtfsId': 'IJPP:b', 'name': 'Borovnica', 'lat': 45.9196, 'lon': 14.3646}],
        'patternGeometry': {'points': ''},
        'tripsForDate': [otp_trip('LPP:t2', 8 * 3600 + 42 * 60), otp_trip('LPP:t1', 5 * 3600 + 12 * 60)],
    }],
}


class LineTests(SimpleTestCase):
    def test_line_patterns_list_todays_departures(self):
        line, complete = trips.build_line(LINE_PAYLOAD, date(2026, 10, 10))
        self.assertTrue(complete)
        self.assertEqual(line['patterns'][0]['departures'][0], {'tripId': 'LPP:t1', 'departure': '2026-10-10T05:12:00+02:00'})
        self.assertEqual([d['tripId'] for d in line['patterns'][0]['departures']], ['LPP:t1', 'LPP:t2'])
        self.assertEqual(line['patterns'][0]['tripCount'], 2)

    def test_trips_without_a_departure_time_are_left_out(self):
        payload = {**LINE_PAYLOAD, 'patterns': [{**LINE_PAYLOAD['patterns'][0], 'tripsForDate': [{'gtfsId': 'LPP:x', 'departureStoptime': None}]}]}
        line, _ = trips.build_line(payload, date(2026, 10, 10))
        self.assertEqual((line['patterns'][0]['departures'], line['patterns'][0]['tripCount']), ([], 1))

    def test_an_sz_bus_line_is_replacement_transport(self):
        bus = {**LINE_PAYLOAD, 'shortName': 'BUS 18969', 'mode': 'BUS'}
        with mock.patch.object(trips, 'road_shape', return_value=([], True)):
            line, _ = trips.build_line(bus, date(2026, 10, 10))
        self.assertTrue(line['replacement'])
        self.assertNotIn('replacement', trips.build_line(LINE_PAYLOAD, date(2026, 10, 10))[0])

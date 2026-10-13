from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from prestop_api import trips
from prestop_api.mapping import build_vehicles

# A straight street (~1.55 km east-west) and an L-shaped detour that comes back along it.
STREET = [[14.50, 46.05], [14.51, 46.05], [14.52, 46.05]]


class GeometryTests(SimpleTestCase):
    def test_simplify_keeps_corners_and_drops_collinear_points(self):
        dense = [[14.50 + i * 0.0005, 46.05] for i in range(41)] + [[14.52, 46.06]]
        simple = trips.simplify(dense)
        self.assertEqual(simple[0], dense[0])
        self.assertEqual(simple[-1], dense[-1])
        self.assertIn([14.52, 46.05], simple)
        self.assertLessEqual(len(simple), 4)

    def test_simplify_respects_the_point_limit(self):
        zigzag = [[14.5 + i * 0.001, 46.05 + (0.0005 if i % 2 else 0)] for i in range(1000)]
        self.assertLessEqual(len(trips.simplify(zigzag, limit=50)), 50)

    def test_simplify_keeps_a_loop_that_ends_where_it_starts(self):
        # Marprom G3 runs a 17 km circle from Tabor back to Tabor; it was cut down to its two end points.
        square = [[14.50, 46.05], [14.51, 46.05], [14.51, 46.06], [14.50, 46.06], [14.50, 46.05]]
        self.assertEqual(trips.simplify(square), square)

    def test_stop_distances_are_ordered_along_the_shape(self):
        stops = [{'lat': 46.0501, 'lon': 14.50}, {'lat': 46.0502, 'lon': 14.51}, {'lat': 46.0499, 'lon': 14.52}]
        distances = trips.stop_distances(STREET, stops)
        self.assertEqual(distances[0], 0.0)
        self.assertAlmostEqual(distances[1], 774, delta=10)
        self.assertAlmostEqual(distances[2], trips.cumulative(STREET)[-1], delta=1)

    def test_a_shape_that_passes_a_stop_twice_matches_the_first_pass(self):
        # Out along the street, a loop north, and back west along the same street.
        loop = [[14.50, 46.05], [14.52, 46.05], [14.52, 46.051], [14.50, 46.0501]]
        stops = [{'lat': 46.05, 'lon': 14.50}, {'lat': 46.05, 'lon': 14.51}, {'lat': 46.0501, 'lon': 14.50}]
        distances = trips.stop_distances(loop, stops)
        self.assertAlmostEqual(distances[1], 774, delta=10)
        self.assertGreater(distances[2], 3000)


def otp_trip(trip_id='LPP:t1', day=1791496800, realtime=True):
    stops = [{'gtfsId': f'LPP:s{i}', 'name': f'Stop {i}', 'lat': 46.05, 'lon': 14.50 + i * 0.01} for i in range(3)]
    return {
        'gtfsId': trip_id, 'directionId': None, 'tripHeadsign': 'Stop 2',
        'route': {'gtfsId': 'LPP:r1', 'shortName': '6', 'mode': 'BUS', 'color': '00A0E0', 'agency': {'gtfsId': 'LPP:lpp'}},
        'pattern': {'code': 'LPP:r1::01'}, 'tripGeometry': {'points': ''},
        'stoptimes': [{'stopPosition': i + 1, 'stop': s} for i, s in enumerate(stops)],
        'stoptimesForDate': [{'stopPosition': i + 1, 'scheduledArrival': 36000 + i * 120, 'realtimeArrival': 36000 + i * 120 + 60,
                              'scheduledDeparture': 36000 + i * 120, 'realtimeDeparture': 36000 + i * 120 + 60,
                              'realtime': realtime, 'realtimeState': 'UPDATED', 'serviceDay': day} for i in range(3)],
    }


class TripTests(SimpleTestCase):
    def setUp(self):
        trips._static._data.clear()
        trips._times._data.clear()

    def test_trip_carries_shape_stops_live_times_and_learned_segments(self):
        with mock.patch.object(trips, '_query_trips', return_value={'LPP:t1': otp_trip()}):
            found = trips.load_trips(['LPP:t1'], date(2026, 10, 9))
        trip = trips.build_trip(found['LPP:t1'], {'LPP:s0>LPP:s1': 95.0})
        self.assertEqual((trip['routeName'], trip['operatorId'], trip['color'], trip['realtime']), ('6', 'LPP:lpp', '#00A0E0', True))
        self.assertEqual([s['typicalSeconds'] for s in trip['stops']], [95.0, None, None])
        self.assertEqual(trip['stops'][1]['effectiveArrival'], '2026-10-09T08:03:00Z')
        # No shape in the feed: the stops are joined (three collinear stops simplify to a segment).
        self.assertEqual((trip['geometry'][0], trip['geometry'][-1]), ([14.5, 46.05], [14.52, 46.05]))
        self.assertEqual(trips.build_trip(found['LPP:t1'], {}, geometry=False)['geometry'], [])

    def test_static_parts_are_fetched_once(self):
        with mock.patch.object(trips, '_query_trips', return_value={'LPP:t1': otp_trip()}) as query:
            trips.load_trips(['LPP:t1'], date(2026, 10, 9))
            trips._times._data.clear()
            trips.load_trips(['LPP:t1'], date(2026, 10, 9))
        self.assertEqual(query.call_args_list[0].args[2], {'LPP:t1'})
        self.assertEqual(query.call_args_list[1].args[2], set())

    def overnight(self, at: str):
        """A daily trip 23:30 - 24:10 (00:10 the next morning), loaded at `at` on 14 October; live on both days."""
        from datetime import datetime

        from prestop_api import supplement

        def run(day):
            t = otp_trip(day=supplement.day_start(day))
            for i, s in enumerate(t['stoptimesForDate']):
                s.update(scheduledArrival=84600 + i * 1200, scheduledDeparture=84600 + i * 1200,
                         realtimeArrival=84660 + i * 1200, realtimeDeparture=84660 + i * 1200)
            return t
        now = datetime.fromisoformat(f'2026-10-14T{at}+02:00').timestamp()
        query = mock.Mock(side_effect=lambda ids, day, static: {'LPP:t1': run(day)})
        with mock.patch.object(trips, '_query_trips', query), mock.patch.object(trips.time, 'time', return_value=now):
            found = trips.load_trips(['LPP:t1'])
        return found['LPP:t1'], query

    def test_just_after_midnight_last_nights_run_wins_while_still_on_the_road(self):
        entry, _ = self.overnight('00:05')
        self.assertEqual(entry['serviceDate'], date(2026, 10, 13))
        trip = trips.build_trip(entry, {})
        # 00:11 this morning (one minute late), not 00:10 tomorrow: its delay is a minute, not a day early.
        self.assertEqual(trip['stops'][-1]['effectiveArrival'], '2026-10-13T22:11:00Z')
        self.assertEqual(trip['stops'][-1]['scheduledArrival'], '2026-10-13T22:10:00Z')

    def test_once_last_nights_run_has_arrived_tonights_is_shown(self):
        entry, _ = self.overnight('01:00')
        self.assertEqual(entry['serviceDate'], date(2026, 10, 14))

    def test_in_the_day_the_previous_day_is_not_asked(self):
        entry, query = self.overnight('12:00')
        self.assertEqual((entry['serviceDate'], query.call_count), (date(2026, 10, 14), 1))

    def test_vehicle_carries_motion_hints(self):
        entity = {'vehicle': {'trip': {'tripId': 'LPP:t1'}, 'position': {'latitude': 46.05, 'longitude': 14.5, 'bearing': 90, 'speed': 7.2},
                              'timestamp': '1791540000', 'stopId': 'LPP:s1', 'currentStatus': 'STOPPED_AT', 'vehicle': {'id': 'LPP:v1', 'label': 'LJ 1'}}}
        [vehicle] = build_vehicles([entity], {}, {'LPP:t1': {'routeId': 'LPP:r1'}}, {'LPP:r1': {'gtfsId': 'LPP:r1', 'shortName': '6', 'mode': 'BUS'}}, {}, now=1791540010)
        self.assertEqual((vehicle['tripId'], vehicle['speed'], vehicle['nextStopId'], vehicle['stopped']), ('LPP:t1', 7.2, 'LPP:s1', True))

    def test_bare_feed_prefixes_are_not_passed_on_as_ids(self):
        # Marprom reports trip ids like "MARPROM:"; one malformed id must not invalidate the whole response.
        entity = {'vehicle': {'trip': {'tripId': 'MARPROM:', 'routeId': 'MARPROM:6'}, 'position': {'latitude': 46.55, 'longitude': 15.64},
                              'timestamp': '1791540000', 'stopId': 'MARPROM:', 'vehicle': {'id': 'MARPROM:v1'}}}
        [vehicle] = build_vehicles([entity], {}, {}, {'MARPROM:6': {'gtfsId': 'MARPROM:6', 'shortName': '6', 'mode': 'BUS'}}, {}, now=1791540010)
        self.assertEqual((vehicle['tripId'], vehicle['nextStopId']), (None, None))


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class EndpointTests(TestCase):
    def test_unknown_trip_is_404(self):
        with mock.patch.object(trips, 'load_trips', return_value={}):
            response = self.client.get('/api/v1/trips/LPP:missing')
        self.assertEqual((response.status_code, response.json()['error']['code']), (404, 'TRIP_NOT_FOUND'))

    def test_trip_list_needs_ids_and_caps_them(self):
        self.assertEqual(self.client.get('/api/v1/trips').status_code, 422)
        ids = ','.join(f'X:{i}' for i in range(61))
        self.assertEqual(self.client.get('/api/v1/trips', {'ids': ids}).status_code, 422)

    def test_reliability_without_measurements_is_empty_not_zero(self):
        body = self.client.get('/api/v1/statistics/reliability', {'routeIds': 'LPP:r1'}).json()
        self.assertEqual(body['data'][0]['tripCount'], 0)
        self.assertIsNone(body['data'][0]['meanSignedDelaySeconds'])
        self.assertIsNone(body['data'][0]['onTimeShare'])

    def test_trip_stops_carry_observed_delays_and_null_where_never_observed(self):
        from django.utils import timezone
        from prestop_statistics.models import TripDelay
        trips._static._data.clear()
        trips._times._data.clear()
        TripDelay.objects.create(service_date=date(2026, 10, 9), trip_id='LPP:t1', route_id='LPP:r1', operator_id='LPP:lpp', direction='0',
                                 stop_delays={'1': 0, '2': 190}, first_seen=timezone.now(), last_seen=timezone.now())
        with mock.patch.object(trips, '_query_trips', return_value={'LPP:t1': otp_trip()}):
            body = self.client.get('/api/v1/trips/LPP:t1', {'date': '2026-10-09'}).json()
            listed = self.client.get('/api/v1/trips', {'ids': 'LPP:t1', 'date': '2026-10-09'}).json()
        self.assertEqual([s['observedDelaySeconds'] for s in body['data']['stops']], [0, 190, None])
        self.assertEqual([s['observedDelaySeconds'] for s in listed['data'][0]['stops']], [0, 190, None])

    def test_line_departures_carry_the_last_observed_delay(self):
        from django.utils import timezone
        from prestop_statistics.models import TripDelay
        TripDelay.objects.create(service_date=date(2026, 10, 9), trip_id='LPP:t1', route_id='LPP:r1', operator_id='LPP:lpp', direction='0',
                                 stop_delays={'1': 30, '12': 420, '3': 60}, first_seen=timezone.now(), last_seen=timezone.now())
        line = {'id': 'LPP:r1', 'serviceDate': '2026-10-09', 'patterns': [{'id': 'p', 'departures': [
            {'tripId': 'LPP:t1', 'departure': '2026-10-09T10:00:00+02:00'}, {'tripId': 'LPP:t2', 'departure': '2026-10-09T10:30:00+02:00'}]}]}
        with mock.patch.object(trips, 'load_line', return_value=line):
            body = self.client.get('/api/v1/lines/LPP:r1').json()
        departures = body['data']['patterns'][0]['departures']
        self.assertEqual(departures[0]['observedDelaySeconds'], 420)
        self.assertNotIn('observedDelaySeconds', departures[1])
        self.assertNotIn('observedDelaySeconds', line['patterns'][0]['departures'][0])

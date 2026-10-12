from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from prestop_api import geometry, roads, scheduled
from prestop_api.models import RoadLeg

# Stops along a street running east, ~770 m apart.
STOPS = [{'lat': 46.05, 'lon': 14.50}, {'lat': 46.05, 'lon': 14.51}, {'lat': 46.05, 'lon': 14.52}]
# The road the bus drives: a dense line along the street.
ROAD = [[14.50 + i * 0.0005, 46.05] for i in range(41)]


def leg(a, b, bulge=0.002):
    """A routed leg from stop a to stop b that bends north (not a straight line)."""
    mid = [(a['lon'] + b['lon']) / 2, a['lat'] + bulge]
    return [[a['lon'], a['lat']], mid, [b['lon'], b['lat']]]


@override_settings(PRESTOP_VALHALLA_URL='')
class BadSegmentTests(SimpleTestCase):
    def test_a_real_shape_is_left_alone(self):
        self.assertEqual(roads.bad_segments(ROAD, STOPS), [False, False])

    def test_a_feed_without_a_shape_is_bad_everywhere(self):
        straight = [[s['lon'], s['lat']] for s in STOPS]
        self.assertEqual(roads.bad_segments(straight, STOPS), [True, True])
        self.assertEqual(roads.bad_segments([], STOPS), [True, True])

    def test_a_straight_run_without_shape_points_is_bad(self):
        # Dense up to the middle stop, then one long straight line to the last.
        partial = [c for c in ROAD if c[0] <= 14.51] + [[14.52, 46.05]]
        self.assertEqual(roads.bad_segments(partial, STOPS), [False, True])

    def test_a_shape_that_starts_away_from_the_first_stop_is_bad_there(self):
        # Like Ljubljana AP: the shape still starts ~470 m west at the old bus station.
        moved = [{'lat': 46.0535, 'lon': 14.50}, *STOPS[1:]]
        self.assertEqual(roads.bad_segments(ROAD, moved), [True, False])


@override_settings(PRESTOP_VALHALLA_URL='')
class SpliceTests(SimpleTestCase):
    def test_routed_legs_replace_bad_segments_and_keep_the_rest(self):
        straight = [[s['lon'], s['lat']] for s in STOPS]
        routed = {roads.leg_key(STOPS[0], STOPS[1]): leg(STOPS[0], STOPS[1])}
        out = roads.splice(straight, STOPS, [True, True], routed)
        self.assertTrue(any(abs(c[1] - 46.052) < 1e-9 for c in out))  # the routed bend
        self.assertEqual(out[-1], [14.52, 46.05])  # no leg yet: straight to the last stop

    def test_a_routed_leg_with_an_absurd_detour_is_not_used(self):
        # Like Dolgi most P+R: the router snapped a stop to the far side of the road and looped 7 km to turn.
        straight = [[s['lon'], s['lat']] for s in STOPS]
        loop = leg(STOPS[0], STOPS[1], bulge=0.03)  # ~6.7 km for 770 m
        routed = {roads.leg_key(STOPS[0], STOPS[1]): loop}
        out = roads.splice(straight, STOPS, [True, False], routed)
        self.assertFalse(any(abs(c[1] - 46.08) < 1e-9 for c in out))
        self.assertLess(geometry.cumulative(out)[-1], 2000)

    def test_the_shape_is_trimmed_to_the_first_stop(self):
        moved = [{'lat': 46.0535, 'lon': 14.50}, *STOPS[1:]]
        routed = {roads.leg_key(moved[0], moved[1]): leg(moved[0], moved[1])}
        out = roads.splice(ROAD, moved, [True, False], routed)
        self.assertEqual(out[0], [14.50, 46.0535])
        self.assertAlmostEqual(geometry.cumulative(out)[-1], geometry.cumulative(ROAD)[-1] + 200, delta=400)

    def test_repair_uses_stored_legs_and_reports_completeness(self):
        straight = [[s['lon'], s['lat']] for s in STOPS]
        both = {roads.leg_key(a, b): leg(a, b) for a, b in zip(STOPS, STOPS[1:])}
        with mock.patch.object(roads.legs, 'get_many', side_effect=lambda keys: {k: both[k] for k in keys if k in both}):
            out, complete = roads.repair(straight, STOPS)
        self.assertTrue(complete)
        self.assertGreater(len(out), 3)
        with override_settings(PRESTOP_VALHALLA_URL='https://example.invalid/route'), \
                mock.patch.object(roads.legs, 'get_many', return_value={}), mock.patch.object(roads.worker, 'request', return_value=[]):
            _, complete = roads.repair(straight, STOPS)
        self.assertFalse(complete)

    def test_a_shape_without_problems_is_returned_unchanged(self):
        self.assertEqual(roads.repair(ROAD, STOPS), (ROAD, True))


class MatchTests(SimpleTestCase):
    """Feed shapes map-matched onto the roads (roads.match_shape / matched)."""
    # A sparse feed shape cutting the corner of an L-shaped street, and the street itself.
    FEED = [[14.50, 46.05], [14.505, 46.053], [14.51, 46.056], [14.515, 46.058], [14.52, 46.06]]
    STREET = [[14.50 + i * 0.0005, 46.05] for i in range(21)] + [[14.51 + i * 0.0005, 46.05 + i * 0.0005] for i in range(1, 21)]

    def test_a_close_match_of_similar_length_is_accepted(self):
        feed = [[14.50 + i * 0.001, 46.05 + 0.0002] for i in range(21)]  # ~20 m north of the street
        self.assertTrue(roads.match_ok(feed, ROAD[:41]))

    def test_a_match_that_covers_only_part_of_the_shape_or_runs_far_away_is_refused(self):
        feed = [[14.50 + i * 0.001, 46.05] for i in range(21)]
        self.assertFalse(roads.match_ok(feed, feed[:5]))
        elsewhere = [[x, y + 0.003] for x, y in feed]  # a parallel road ~330 m away
        self.assertFalse(roads.match_ok(feed, elsewhere))
        self.assertFalse(roads.match_ok(feed, None))

    def test_the_whole_shape_is_matched_in_one_request_when_that_works(self):
        feed = [[14.50 + i * 0.001, 46.05] for i in range(21)]
        calls = []
        line = roads.match_shape(feed, lambda pts: calls.append(pts) or [[x, y + 0.00005] for x, y in pts])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(line), len(feed))

    def test_a_partial_match_falls_back_to_pieces_keeping_the_feed_where_a_piece_fails(self):
        feed = [[14.50 + i * 0.001, 46.05] for i in range(200)]  # ~15 km, three pieces

        def request(pts):
            if len(pts) == len(feed):
                return pts[:20]  # Valhalla matched only the start
            if pts[0][0] > 14.65:
                return None  # the last piece doesn't match at all
            return [[x, y + 0.00005] for x, y in pts]
        line = roads.match_shape(feed, request)
        self.assertAlmostEqual(geometry.cumulative(line)[-1], geometry.cumulative(feed)[-1], delta=50)
        self.assertIn([14.68, 46.05], [[round(x, 5), round(y, 5)] for x, y in line])  # the failed piece kept as fed
        self.assertIn([14.62, 46.05005], [[round(x, 5), round(y, 5)] for x, y in line])  # a matched one

    def test_nothing_matched_is_stored_as_empty(self):
        self.assertEqual(roads.match_shape(self.FEED, lambda pts: None), [])

    @override_settings(PRESTOP_VALHALLA_URL='http://valhalla.test/route', PRESTOP_SHAPE_MATCH=True)
    def test_repair_draws_a_stored_match_and_ignores_the_feed_lines_road_checks(self):
        with mock.patch.object(roads.legs, 'get_many', side_effect=lambda keys: {k: self.STREET for k in keys if k.startswith(roads.MATCH_PREFIX)}),                 mock.patch.object(roads, 'checks', return_value={roads.leg_key(STOPS[0], STOPS[1]): 99}):
            stops = [{'lat': 46.05, 'lon': 14.50}, {'lat': 46.06, 'lon': 14.52}]
            shape, complete = roads.repair(self.FEED, stops, deadline=0)
        self.assertEqual(shape, self.STREET)
        self.assertTrue(complete)

    @override_settings(PRESTOP_VALHALLA_URL='http://valhalla.test/route', PRESTOP_SHAPE_MATCH=True)
    def test_a_shape_still_being_matched_is_not_complete(self):
        stops = [{'lat': 46.05, 'lon': 14.50}, {'lat': 46.06, 'lon': 14.52}]
        pending = mock.Mock(wait=mock.Mock(return_value=False))
        with mock.patch.object(roads.legs, 'get_many', return_value={}), mock.patch.object(roads.matcher, 'request', return_value=pending),                 mock.patch.object(roads, 'checks', return_value={}):
            shape, complete = roads.repair(self.FEED, stops, deadline=0)
        self.assertEqual(shape, self.FEED)  # the feed's line meanwhile
        self.assertFalse(complete)  # so it is rebuilt soon, not kept for the line cache's 15 min
        with mock.patch.object(roads.legs, 'get_many', return_value={}), mock.patch.object(roads.matcher, 'request', return_value=None),                 mock.patch.object(roads, 'checks', return_value={}):
            self.assertTrue(roads.repair(self.FEED, stops, deadline=0)[1])  # matching failed lately: the feed's line is final

    def test_keys_change_with_the_shape(self):
        self.assertNotEqual(roads.match_key(self.FEED), roads.match_key(self.FEED[:2]))
        self.assertLessEqual(len(roads.match_key(self.FEED)), 64)


class LegStoreTests(TestCase):
    def test_legs_are_stored_once_and_read_back(self):
        store = roads._Legs()
        store.put_many({'a': [[1, 2], [3, 4]], 'b': []})
        store.put_many({'a': [[9, 9]]})  # an existing route is kept
        self.assertEqual(RoadLeg.objects.count(), 2)
        self.assertEqual(roads._Legs().get_many(['a', 'b', 'c']), {'a': [[1, 2], [3, 4]], 'b': []})


class WorkerTests(SimpleTestCase):
    def test_windows_overlap_at_their_boundary_stop(self):
        stops = [{'lat': 46.05, 'lon': 14.50 + i * 0.01} for i in range(12)]
        missing = {roads.leg_key(a, b) for a, b in zip(stops, stops[1:])}
        worker = roads._Worker()
        with mock.patch.object(roads.threading, 'Thread'):
            events = worker.request(stops, missing)
        self.assertEqual(len(events), 2)
        windows = [worker._queue.get_nowait()[0] for _ in events]
        self.assertEqual(len(windows[0]), roads.MAX_LOCATIONS)
        self.assertEqual(windows[0][-1], windows[1][0])
        # Asking again while they are pending reuses the same requests.
        self.assertEqual(set(worker.request(stops, missing)), set(events))


class ScheduledTrainTests(SimpleTestCase):
    T0 = 1_760_000_000
    TRIP = {'arrivals': [T0, T0 + 600, T0 + 1200], 'departures': [T0, T0 + 660, T0 + 1200]}
    SHAPE = {'distances': [0.0, 5000.0, 9000.0]}

    def test_a_train_waits_at_its_first_station_before_departure(self):
        at = scheduled.locate(self.TRIP, self.SHAPE, self.T0 - 60)
        self.assertEqual((at['stop'], at['stopped'], at['distance']), (0, True, 0.0))
        self.assertIsNone(scheduled.locate(self.TRIP, self.SHAPE, self.T0 - scheduled.BOARDING - 1))

    def test_between_stations_it_is_interpolated_along_the_shape(self):
        at = scheduled.locate(self.TRIP, self.SHAPE, self.T0 + 300)
        self.assertEqual((at['stop'], at['stopped']), (1, False))
        self.assertAlmostEqual(at['distance'], 2500)
        self.assertAlmostEqual(at['speed'], 5000 / 600)

    def test_it_stands_at_a_station_between_arrival_and_departure(self):
        at = scheduled.locate(self.TRIP, self.SHAPE, self.T0 + 630)
        self.assertEqual((at['stop'], at['stopped'], at['distance']), (1, True, 5000.0))

    def test_it_is_gone_after_arriving(self):
        self.assertTrue(scheduled.locate(self.TRIP, self.SHAPE, self.T0 + 1200 + 30)['stopped'])
        self.assertIsNone(scheduled.locate(self.TRIP, self.SHAPE, self.T0 + 1200 + scheduled.ARRIVED + 1))

    def test_vehicles_are_marked_scheduled_and_skip_trains_with_a_live_position(self):
        trip = {**self.TRIP, 'id': 'IJPP:t1', 'pattern': 'p', 'headsign': None, 'delays': [None, None, None],
                'route': {'gtfsId': 'IJPP:r1', 'shortName': 'LPV 2904', 'agency': {'gtfsId': 'IJPP:1161'}},
                'stops': [{'gtfsId': f'IJPP:s{i}', 'name': f'S{i}', 'lat': 46.05, 'lon': 14.5 + i * 0.05} for i in range(3)]}
        coords = [[14.5, 46.05], [14.6, 46.05]]
        shape = {'coords': coords, 'cum': geometry.cumulative(coords), 'distances': [0.0, 3850.0, 7700.0]}
        with mock.patch.object(scheduled.timetable, 'get', return_value=mock.Mock(value=[trip])), \
                mock.patch.object(scheduled.shapes, 'get', return_value=mock.Mock(value={'p': shape})):
            [train] = scheduled.vehicles(self.T0 + 300)
            self.assertEqual(scheduled.vehicles(self.T0 + 300, skip_trips=frozenset({'IJPP:t1'})), [])
        self.assertEqual((train['id'], train['quality'], train['mode'], train['tripId']), ('IJPP:scheduled-t1', 'scheduled', 'rail', 'IJPP:t1'))
        self.assertEqual(train['nextStopId'], 'IJPP:s1')
        self.assertAlmostEqual(train['longitude'], 14.525, places=3)
        self.assertAlmostEqual(train['bearing'], 90, delta=1)
        self.assertIsNone(train['delaySeconds'])

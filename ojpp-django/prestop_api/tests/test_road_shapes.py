"""Road-following bus shapes: deviating segments found, routed once offline, densified for the app."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from prestop_api import geometry, roads, views
from prestop_api.tests.test_roads import ROAD, STOPS

# A sparse checkpoint shape: the stops and one point ~390 m on, so each stop-to-stop stretch has a long gap.
SPARSE = [[14.50, 46.05], [14.505, 46.05], [14.51, 46.05], [14.515, 46.05], [14.52, 46.05]]


class DeviationTests(SimpleTestCase):
    def test_a_stretch_found_off_the_road_is_bad(self):
        first = roads.leg_key(STOPS[0], STOPS[1])
        self.assertEqual(roads.bad_segments(ROAD, STOPS, {first: 40.0}), [True, False])
        self.assertEqual(roads.bad_segments(ROAD, STOPS, {first: 12.0}), [False, False])  # within OFF_ROAD

    def test_straight_runs_over_150_m_without_points_are_bad(self):
        stops = [{'lat': 46.05, 'lon': 14.50}, {'lat': 46.05, 'lon': 14.5022}, {'lat': 46.05, 'lon': 14.5044}]  # ~170 m apart
        line = [[14.50, 46.05], [14.5006, 46.05], [14.5011, 46.05], [14.5016, 46.05], [14.5022, 46.05], [14.5044, 46.05]]  # points only in the first stretch
        self.assertEqual(roads.bad_segments(line, stops, {}), [False, True])

    def test_sparse_points_are_half_way_across_long_gaps(self):
        line = [[14.50, 46.05], [14.501, 46.05], [14.51, 46.05]]  # gaps of ~77 m and ~690 m
        cum = geometry.cumulative(line)
        [mid] = roads.sparse_points(line, cum, 0, cum[-1])
        self.assertAlmostEqual(mid[0], 14.5055, places=4)
        self.assertEqual(roads.sparse_points(ROAD, geometry.cumulative(ROAD), 0, cum[-1]), [])  # dense: nothing to check


class DensifyTests(SimpleTestCase):
    def test_no_segment_is_longer_than_the_step_and_the_line_is_unchanged(self):
        line = [[14.50, 46.05], [14.52, 46.05], [14.52, 46.06]]
        dense = geometry.densify(line, 30)
        self.assertEqual((dense[0], dense[-1]), (line[0], line[-1]))
        self.assertIn(line[1], dense)
        self.assertLessEqual(max(geometry.distance(a, b) for a, b in zip(dense, dense[1:])), 30.5)  # 6-decimal rounding
        self.assertAlmostEqual(geometry.cumulative(dense)[-1], geometry.cumulative(line)[-1], delta=0.5)

    def test_responses_stay_under_the_point_budget(self):
        line = [[14.50, 46.05], [15.50, 46.05]]  # ~77 km
        length = geometry.cumulative(line)[-1]
        [one] = views._dense([{'geometry': line, 'length': length}])
        self.assertLessEqual(max(geometry.distance(a, b) for a, b in zip(one['geometry'], one['geometry'][1:])), 30.5)
        many = views._dense([{'geometry': line, 'length': length}] * 60)
        self.assertLessEqual(sum(len(t['geometry']) for t in many), views.POINT_BUDGET + 60 * 2)


@override_settings(PRESTOP_VALHALLA_URL='https://valhalla.example/route')
class CommandTests(SimpleTestCase):
    def run_command(self, checks, stored):
        out = StringIO()
        patterns = [{'route': 'LPP:6', 'code': 'p1', 'stops': STOPS, 'coords': SPARSE, 'replacement': False}]
        with mock.patch('prestop_api.management.commands.road_shapes.Command._patterns', return_value=patterns), \
                mock.patch.object(roads, 'checks', return_value=checks), mock.patch.object(roads, 'CHECKS') as path, \
                mock.patch.object(roads.legs, 'get_many', side_effect=lambda keys: {k: [[0, 0], [1, 1]] for k in keys if k in stored}), \
                mock.patch.object(roads.legs, 'put_many') as put, mock.patch.object(roads, 'route_window', return_value=[ROAD[:21], ROAD[20:]]) as route, \
                mock.patch('requests.Session.post') as post, mock.patch('time.sleep'):
            post.return_value.json.return_value = [{'input_lat': 46.05, 'input_lon': 14.5025,
                                                    'edges': [{'correlated_lat': 46.0505, 'correlated_lon': 14.5025}]}] * 10
            call_command('road_shapes', routes='LPP:6', stdout=out)
        return out.getvalue(), post, route, put, path.write_text

    def test_a_first_run_checks_and_routes_what_is_off_the_road(self):
        text, post, route, put, saved = self.run_command({}, set())
        self.assertEqual(post.call_count, 1)  # both stretches' points in one locate request
        self.assertEqual(route.call_count, 1)  # ~55 m off the road: both legs routed in one window
        self.assertTrue(saved.called)
        self.assertIn('2 legs stored', text)

    def test_a_rerun_makes_no_valhalla_request(self):
        keys = {roads.leg_key(a, b) for a, b in zip(STOPS, STOPS[1:])}
        text, post, route, put, _ = self.run_command({k: 55.6 for k in keys}, keys)
        self.assertEqual((post.call_count, route.call_count, put.call_count), (0, 0, 0))
        self.assertIn('done: 0 Valhalla requests', text)

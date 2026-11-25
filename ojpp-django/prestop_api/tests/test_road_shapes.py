"""Road-following bus shapes: deviating segments found, routed once offline, densified for the app."""
from datetime import date
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from prestop_api import closures, geometry, mapping, raillines, roads, scheduled, views
from prestop_api.management.commands import road_shapes
from prestop_api.management.commands.road_shapes import Command
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

    def test_a_train_gets_fewer_points_on_the_same_line(self):
        corner = [[14.50, 46.05], [14.60, 46.05], [14.60, 46.10]]  # ~13 km
        length = geometry.cumulative(corner)[-1]
        [bus, train] = views._dense([{'geometry': corner, 'length': length, 'mode': 'bus'}, {'geometry': corner, 'length': length, 'mode': 'rail'}])
        self.assertLess(len(train['geometry']), len(bus['geometry']) / 3)
        self.assertLessEqual(max(geometry.distance(a, b) for a, b in zip(train['geometry'], train['geometry'][1:])), 100.5)
        self.assertIn(corner[1], train['geometry'])  # every point of the shape stays
        self.assertAlmostEqual(geometry.cumulative(train['geometry'])[-1], length, delta=0.5)

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


def _bus(name, stops, stamp, replacement=True):
    return {'id': name, 'route': {'replacement': replacement}, 'stops': stops, 'serviceDate': stamp}


@override_settings(PRESTOP_VALHALLA_URL='https://valhalla.example/route')
class MorningTests(SimpleTestCase):
    def run_morning(self, plan, **options):
        stored, asked, out = {}, [], StringIO()

        def route(window):
            asked.append([s['name'] for s in window])
            return [ROAD for _ in window[1:]]
        with mock.patch.object(scheduled, 'service_day', return_value=date(2026, 11, 25)), \
                mock.patch.object(scheduled, 'day_plan', lambda day, **kwargs: plan(day)), \
                mock.patch.object(closures, 'relocate', lambda stops: stops), \
                mock.patch.object(closures, 'service_date', lambda t: t['serviceDate']), \
                mock.patch.object(mapping, 'is_replacement', lambda r: r['replacement']), \
                mock.patch.object(roads, 'route_window', route), \
                mock.patch.object(roads.legs, 'get_many', lambda keys: {k: stored[k] for k in keys if k in stored}), \
                mock.patch.object(roads.legs, 'put_many', stored.update), \
                mock.patch.object(Command, '_patterns', return_value=[]), \
                mock.patch.object(Command, '_check') as check, \
                mock.patch.object(Command, '_rail', create=True) as rail:
            call_command('road_shapes', morning=True, gap=0, stdout=out, stderr=out, **options)
        check.assert_not_called()  # shape_checks.json is read-only on the server
        rail.assert_called_once()
        return stored, asked, out.getvalue()

    def plan(self, day):
        stamp = day.strftime('%Y%m%d')
        named = [{**s, 'name': n} for s, n in zip(STOPS, ('Maribor', 'Pesnica', 'Šentilj'))]
        feed = _bus('feed', [named[2], named[0]], stamp)
        suppressed = _bus('gone', [named[0], named[2]], stamp)
        train = _bus('train', [named[1], named[0]], stamp, replacement=False)
        return {'synthetic': [_bus('syn', named, stamp)], 'suppressed': {'gone': 'x'},
                'trips': {t['id']: [t] for t in (feed, suppressed, train)}}

    def test_routes_the_legs_of_todays_and_tomorrows_replacement_buses_once(self):
        stored, asked, _ = self.run_morning(self.plan)
        self.assertEqual(sorted(asked), [['Maribor', 'Pesnica', 'Šentilj'], ['Šentilj', 'Maribor']])
        self.assertEqual(len(stored), 3)  # not the suppressed feed bus's, nor the train's

    def test_a_dry_run_lists_the_legs_and_asks_nothing(self):
        stored, asked, out = self.run_morning(self.plan, dry_run=True)
        self.assertEqual((stored, asked), ({}, []))
        self.assertIn('to route: Maribor → Pesnica', out)
        self.assertIn('to route: Pesnica → Šentilj', out)

    def test_a_missing_plan_fails_the_run_after_the_other_day(self):
        with self.assertRaisesMessage(CommandError, '2026-11-25'):
            self.run_morning(lambda day: None if day.day == 25 else self.plan(day))


class RailTests(SimpleTestCase):
    def test_a_train_the_feed_gives_only_stops_for_gets_its_shape_worked_out(self):
        stops = [{**s, 'gtfsId': f'1:{n}', 'name': n} for s, n in zip(STOPS, ('Pragersko', 'Ptuj', 'Ormož'))]
        answer = {'routes': [{'patterns': [{'code': 'p', 'stops': stops, 'patternGeometry': None}]}]}
        command, out = Command(stdout=StringIO()), []
        command.dry = False
        with mock.patch.object(road_shapes, 'otp') as otp, mock.patch.object(raillines, 'feed_shapes'), \
                mock.patch.object(raillines, 'shape_from_others', return_value=None), \
                mock.patch.object(road_shapes, 'road_shape', lambda *a: out.append(a)):
            otp.return_value.query.return_value = answer
            command._rail()
        self.assertEqual([(a[0], len(a[1]), a[2]) for a in out], [([], 3, 'rail')])
        self.assertIn('Pragersko – Ormož', command.stdout._out.getvalue())

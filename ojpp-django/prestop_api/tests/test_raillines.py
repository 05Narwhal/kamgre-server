from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import geometry, raillines

SZ = 'IJPP:1161'
HOME = {'gtfsId': 'IJPP:1122804', 'name': 'Ljubljana'}
AWAY = {'gtfsId': 'IJPP:INTL-8100173', 'name': 'Graz Hauptbahnhof'}
DAY = date(2026, 11, 1)
METRE = 1 / geometry.KY
METRE_X = 1 / raillines._KX
TRAIN = [{'gtfsId': 'IJPP:trip'}]


def east(lat: float, km: float, start: float = 14.5) -> list:
    """A straight line due east."""
    return [[start, lat], [start + km * 1000 * METRE_X, lat]]


def detailed(lat: float, km: float = 5) -> list:
    """A straight line due east with a point every 100 m: a pattern that is not thinned."""
    return geometry.densify(east(lat, km), 100)


def length(line: list) -> float:
    return geometry.cumulative(line)[-1]


def shape(coords: list, stops: int = 3) -> dict:
    cum = geometry.cumulative(coords)
    return {'coords': coords, 'cum': cum, 'distances': [cum[-1] * i / (stops - 1) for i in range(stops)]}


def pattern(code: str = 'p', stops: list | None = None, **days) -> dict:
    return {'code': code, 'stops': [HOME] * 3 if stops is None else stops, **(days or {'d1': TRAIN})}


def route(*patterns, agency: str = SZ, name: str = 'LP 1', mode: str = 'RAIL') -> dict:
    return {'gtfsId': 'IJPP:1', 'shortName': name, 'mode': mode, 'agency': {'gtfsId': agency}, 'patterns': list(patterns)}


def detour(off: float, along: float = 1000) -> list:
    """Along the main line, off it by `off` metres over `along` metres of track, and back on it."""
    x = lambda m: 14.5 + m * METRE_X  # noqa: E731
    return [[14.5, 46.0], [x(2000), 46.0], [x(2100), 46.0 + off * METRE], [x(2000 + along - 100), 46.0 + off * METRE], [x(2000 + along), 46.0], [x(5000), 46.0]]


class MergeTests(SimpleTestCase):
    def test_the_same_track_twice_is_one_line(self):
        lines = raillines.merge([east(46.0, 5), east(46.0, 5)])
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(length(lines[0]), 5000, delta=20)  # east() measures at a fixed latitude

    def test_a_shape_running_the_other_way_adds_nothing(self):
        line = east(46.0, 5)
        self.assertEqual(len(raillines.merge([line, line[::-1]])), 1)

    def test_a_shorter_pattern_on_the_same_track_covers_it_once(self):
        lines = raillines.merge([east(46.0, 2), east(46.0, 5)])
        self.assertAlmostEqual(sum(map(length, lines)), 5000, delta=60)

    def test_double_track_is_one_line(self):
        self.assertEqual(len(raillines.merge([east(46.0, 5), east(46.0 + 10 * METRE, 5)])), 1)

    def test_a_line_far_away_stays_its_own(self):
        self.assertEqual(len(raillines.merge([east(46.0, 5), east(46.1, 5)])), 2)

    def test_a_branch_adds_only_the_branch_and_starts_on_the_main_line(self):
        main = east(46.0, 5)
        fork = main[0][0] + 2000 * METRE_X
        branch = [main[0], [fork, 46.0], [fork + 1000 * METRE_X, 46.0 + 3000 * METRE]]
        lines = raillines.merge([main, branch])
        self.assertEqual(len(lines), 2)
        ends = [end[1] for line in lines for end in (line[0], line[-1])]
        self.assertTrue(any(abs(lat - 46.0) < METRE for lat in ends))
        self.assertLess(min(map(length, lines)), 3300)  # the branch alone, not the 2 km it shares

    def test_a_shape_wandering_beside_the_track_is_dropped_however_long(self):
        self.assertEqual(len(raillines.merge([east(46.0, 5), detour(60, along=3000)])), 1)

    def test_a_real_detour_stays(self):
        self.assertEqual(len(raillines.merge([east(46.0, 5), detour(400, along=1000)])), 2)

    def test_a_shapes_short_approach_to_its_platform_is_dropped(self):
        main = detailed(46.0)  # the more detailed shape, so it goes first
        approach = [main[0], [14.5 + 3000 * METRE_X, 46.0], [14.5 + 3300 * METRE_X, 46.0 + 400 * METRE]]
        self.assertEqual(len(raillines.merge([main, approach])), 1)

    def test_the_detailed_shape_wins_over_a_thinned_one_on_the_same_track(self):
        fine = [[14.5 + k * 100 * METRE_X, 46.0 + (20 if k % 2 else 0) * METRE] for k in range(50)]
        lines = raillines.merge([[fine[0], fine[-1]], fine])
        self.assertEqual(len(lines), 1)
        self.assertGreater(len(lines[0]), 2)

    def test_a_thinned_shape_cutting_a_corner_adds_nothing(self):
        index = {}
        self.assertEqual(len(raillines.merge([east(46.0, 5)], index)), 1)
        self.assertEqual(raillines.merge([detour(400, along=1000)], index, raillines.THINNED_WANDER), [])

    def test_a_shared_index_adds_only_what_the_earlier_lines_lack(self):
        index = {}
        raillines.merge([east(46.0, 5)], index)
        self.assertEqual(raillines.merge([east(46.0, 5)], index), [])


class HomePartsTests(SimpleTestCase):
    def test_a_train_at_home_runs_all_of_it(self):
        self.assertEqual(raillines.home_parts([HOME] * 4), [(0, 3)])

    def test_a_train_going_abroad_stops_at_its_last_stop_here(self):
        self.assertEqual(raillines.home_parts([HOME, HOME, AWAY, AWAY]), [(0, 1)])

    def test_a_train_coming_from_abroad_starts_at_its_first_stop_here(self):
        self.assertEqual(raillines.home_parts([AWAY, AWAY, HOME, HOME]), [(2, 3)])

    def test_a_train_crossing_a_neighbour_runs_both_sides(self):
        self.assertEqual(raillines.home_parts([HOME, HOME, AWAY, HOME, HOME]), [(0, 1), (3, 4)])

    def test_a_stop_marked_by_its_country_is_abroad(self):
        self.assertEqual(raillines.home_parts([{'gtfsId': 'IJPP:1', 'name': 'Tarvisio autostazione (I)'}, HOME, HOME]), [(1, 2)])

    def test_a_train_with_one_stop_here_has_no_stretch(self):
        self.assertEqual(raillines.home_parts([AWAY, HOME]), [])
        self.assertEqual(raillines.home_parts([AWAY, HOME, AWAY]), [])


class StretchTests(SimpleTestCase):
    def test_a_line_with_no_train_today_but_one_this_week_counts(self):
        """The Velenje and Ajdovščina lines on a Sunday and a holiday."""
        found = raillines.stretches([route(pattern(d0=[], d1=TRAIN))], {'p': shape(detailed(46.0))})
        self.assertEqual(len(found[SZ]), 1)

    def test_a_train_on_the_last_day_of_the_week_counts(self):
        last = f'd{raillines.DAYS - 1}'
        self.assertEqual(len(raillines.stretches([route(pattern(**{last: TRAIN}))], {'p': shape(detailed(46.0))})[SZ]), 1)

    def test_a_pattern_with_no_train_all_week_does_not_count(self):
        self.assertEqual(raillines.stretches([route(pattern(d0=[], d1=[]))], {'p': shape(detailed(46.0))}), {})

    def test_a_replacement_bus_does_not_count(self):
        bus = route(pattern(), name='BUS 18969', mode='RAIL')
        self.assertEqual(raillines.stretches([bus], {'p': shape(detailed(46.0))}), {})

    def test_a_pattern_without_a_shape_is_skipped(self):
        self.assertEqual(raillines.stretches([route(pattern())], {}), {})

    def test_stops_that_do_not_match_the_shape_are_skipped(self):
        self.assertEqual(raillines.stretches([route(pattern(stops=[HOME] * 4))], {'p': shape(detailed(46.0))}), {})

    def test_only_what_lies_in_slovenia_is_kept(self):
        found = raillines.stretches([route(pattern(stops=[HOME, HOME, AWAY]))], {'p': shape(detailed(46.0, 4))})
        self.assertAlmostEqual(length(found[SZ][0]), 2000, delta=20)

    def test_a_train_only_abroad_counts_for_nothing(self):
        self.assertEqual(raillines.stretches([route(pattern(stops=[AWAY] * 3))], {'p': shape(detailed(46.0))}), {})

    def test_patterns_are_asked_for_by_how_far_their_shape_can_be_trusted(self):
        sparse = {'p': shape(geometry.densify(east(46.0, 20), 1000))}  # more points than stops, 1 km apart
        unshaped = {'p': shape(east(46.0, 5))}  # as many points as stops or fewer, far apart
        self.assertEqual(raillines.stretches([route(pattern())], sparse), {})
        self.assertEqual(len(raillines.stretches([route(pattern())], sparse, 'thinned')[SZ]), 1)
        self.assertEqual(raillines.stretches([route(pattern())], unshaped, 'thinned'), {})
        self.assertEqual(len(raillines.stretches([route(pattern())], unshaped, 'unshaped')[SZ]), 1)


class UnshapedTests(SimpleTestCase):
    """LP 4208 through the Bohinj valley: its stops joined by straight lines, across the mountain."""

    def test_a_straight_leg_between_stops_on_the_lines_is_not_drawn_however_far_it_cuts(self):
        index = {}
        curve = geometry.densify([[14.5, 46.0], [14.55, 46.05], [14.6, 46.0]], 100)  # 5 km off the chord between its ends
        raillines.merge([curve], index)
        self.assertEqual(raillines.merge_unshaped([[curve[0], curve[-1]]], index), [])

    def test_a_leg_to_a_stop_no_line_reaches_is_drawn(self):
        index = {}
        raillines.merge([detailed(46.0)], index)
        out = raillines.merge_unshaped([[[14.5, 46.0], [14.5, 46.05]]], index)
        self.assertEqual(len(out), 1)
        self.assertGreater(length(out[0]), 5000)

    def test_operators_keep_their_own_stretches(self):
        routes = [route(pattern('p')), route(pattern('q'), agency='IJPP:INTL-HZPP')]
        found = raillines.stretches(routes, {'p': shape(detailed(46.0)), 'q': shape(detailed(46.0))})
        self.assertEqual(sorted(found), [SZ, 'IJPP:INTL-HZPP'])


class QueryTests(SimpleTestCase):
    def test_it_asks_for_each_day_of_the_week_by_date(self):
        query = raillines._query(DAY)
        self.assertIn('d0: tripsForDate(serviceDate: "20261101")', query)
        self.assertIn('d7: tripsForDate(serviceDate: "20261108")', query)
        self.assertNotIn('d8:', query)


class LoadTests(SimpleTestCase):
    def load(self, routes, shapes):
        client = mock.Mock()
        client.query.return_value = {'routes': routes}
        with (mock.patch.object(raillines.scheduled, 'service_day', return_value=DAY),
              mock.patch.object(raillines, 'otp', return_value=client),
              mock.patch.object(raillines.scheduled.shapes, 'get', return_value=mock.Mock(value=shapes)),
              mock.patch.object(raillines, 'merge', wraps=raillines.merge) as merge):
            return raillines._load(), merge

    def setUp(self):
        raillines._built.update(key=None, lines=[])

    def test_the_merge_runs_again_only_when_the_stretches_change(self):
        first, merge = self.load([route(pattern())], {'p': shape(detailed(46.0))})
        self.assertEqual(merge.call_count, 1)
        again, merge = self.load([route(pattern())], {'p': shape(detailed(46.0))})
        self.assertEqual(merge.call_count, 0)
        self.assertIs(first, again)
        self.assertEqual(first[0]['operatorId'], SZ)
        self.assertEqual(first[0]['id'], f'{SZ}#0')
        self.assertGreaterEqual(len(first[0]['geometry']), 2)

    def test_a_stretch_only_a_thinned_or_unshaped_pattern_runs_is_still_drawn(self):
        shapes = {'a': shape(detailed(46.0)), 'b': shape(geometry.densify(east(46.2, 20), 1000)), 'c': shape(east(46.4, 5))}
        lines, _ = self.load([route(pattern('a'), pattern('b'), pattern('c'))], shapes)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len({line['id'] for line in lines}), 3)

    def test_a_track_two_operators_share_is_one_line_of_the_busier_one(self):
        routes = [route(pattern('a'), pattern('b')), route(pattern('c'), agency='IJPP:INTL-HZPP')]
        shapes = {'a': shape(detailed(46.0)), 'b': shape(detailed(46.0)[::-1]), 'c': shape(detailed(46.0))}
        lines, _ = self.load(routes, shapes)
        self.assertEqual([line['operatorId'] for line in lines], [SZ])

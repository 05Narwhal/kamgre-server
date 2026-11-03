from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import border, geometry, mapping, raillines, railtrack

SZ = 'IJPP:1161'
HOME = {'gtfsId': 'IJPP:1122804', 'name': 'Ljubljana'}
AWAY = {'gtfsId': 'IJPP:INTL-8100173', 'name': 'Graz Hauptbahnhof'}
DAY = date(2026, 11, 1)
METRE = 1 / geometry.KY
METRE_X = 1 / raillines._KX
TRAIN = [{'gtfsId': 'IJPP:trip'}]
# These lines lie near Ljubljana, where the real track would pull them onto itself: railtrack has its own tests.
AS_DRAWN = mock.patch.object(raillines.railtrack, 'load', new=lambda: mock.Mock(follow=lambda coords: coords, left=[]))


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

    def test_a_leg_drawn_to_a_stop_no_line_reaches_follows_the_track(self):
        index = {}
        raillines.merge([detailed(46.0)], index)
        # The track to the lone stop bends 1 km east of the straight leg on its way north.
        bend = [[14.5, 46.0], [14.5 + 1000 * METRE_X, 46.025], [14.5, 46.05]]
        track = railtrack.Track([bend])
        (out,) = raillines.merge_unshaped([[[14.5, 46.0], [14.5, 46.05]]], index, track.follow)
        self.assertEqual(track.strays(out), [])
        self.assertGreater(max(x for x, _ in out), 14.5 + 900 * METRE_X)

    def test_operators_keep_their_own_stretches(self):
        routes = [route(pattern('p')), route(pattern('q'), agency='IJPP:INTL-HZPP')]
        found = raillines.stretches(routes, {'p': shape(detailed(46.0)), 'q': shape(detailed(46.0))})
        self.assertEqual(sorted(found), [SZ, 'IJPP:INTL-HZPP'])


LENDAVA = {'gtfsId': 'IJPP:INTL-7900070', 'name': 'Lendava / Lendva'}
MURSKO = {'gtfsId': 'IJPP:INTL-7800106', 'name': 'Mursko Središće'}
# R 7353 in the feed, 2026-11-01: from Lendava south over the Mura into Croatia.
TO_CROATIA = [[16.44618, 46.55661], [16.44329, 46.51875], [16.44336, 46.5178], [16.44358, 46.51688], [16.44712, 46.50621]]


class BorderTests(SimpleTestCase):
    def test_the_border(self):
        for name, lon, lat, inside in (('Ljubljana', 14.51, 46.05, True), ('Lendava', 16.44618, 46.55661, True), ('Koper', 13.73, 45.55, True),
                                       ('Mursko Središće', 16.44712, 46.50621, False), ('Graz', 15.44, 47.07, False),
                                       ('Zagreb', 15.98, 45.81, False), ('Trieste', 13.77, 45.65, False), ('Budapest', 19.04, 47.5, False)):
            with self.subTest(name):
                self.assertEqual(border.contains(lon, lat), inside)

    def test_a_line_stops_where_it_leaves_slovenia_and_never_comes_back(self):
        kept = border.until_abroad(TO_CROATIA + TO_CROATIA[::-1])
        self.assertTrue(all(border.contains(*p) for p in kept))
        self.assertAlmostEqual(geometry.cumulative(kept)[-1], 4570, delta=100)  # the crossing, from the feed's shape

    def test_a_line_starting_abroad_has_nothing_in_slovenia(self):
        self.assertEqual(border.until_abroad(TO_CROATIA[::-1]), [])


DETAILED = geometry.densify(TO_CROATIA, 100)


@AS_DRAWN
class WayOutTests(SimpleTestCase):
    def test_slovenias_own_international_stop_is_at_home_and_the_border_point_is_not(self):
        self.assertFalse(raillines._is_abroad(LENDAVA))
        self.assertTrue(raillines._is_abroad(MURSKO))
        self.assertTrue(raillines._is_abroad({'gtfsId': 'IJPP:INTL-7943778', 'name': 'Hodos Drzavna meja'}))

    def test_every_crossing_of_a_pattern_is_a_way_out(self):
        self.assertEqual(raillines.ways_out([MURSKO, LENDAVA]), [(1, 0)])
        self.assertEqual(raillines.ways_out([LENDAVA, MURSKO]), [(0, 1)])
        self.assertEqual(raillines.ways_out([AWAY, HOME, AWAY]), [(1, 0), (1, 2)])
        self.assertEqual(raillines.ways_out([HOME, HOME, AWAY]), [(1, 2)])  # Jesenice, Šentilj: a line runs up to the station
        self.assertEqual(raillines.ways_out([AWAY, HOME, HOME, AWAY]), [(1, 0), (2, 3)])
        self.assertEqual(raillines.ways_out([HOME, HOME]), [])

    def lendava(self, stops=(LENDAVA, MURSKO), coords=TO_CROATIA):
        cum = geometry.cumulative(coords)
        return [route(pattern(stops=list(stops)), agency='IJPP:INTL-HZPP')], {'p': {'coords': coords, 'cum': cum, 'distances': [0, cum[-1]]}}

    def test_the_line_runs_from_the_station_to_the_border_either_way(self):
        for stops, coords in (((LENDAVA, MURSKO), DETAILED), ((MURSKO, LENDAVA), DETAILED[::-1])):
            routes, shapes = self.lendava(stops, coords)
            [part] = raillines.to_the_border(routes, shapes)['IJPP:INTL-HZPP']
            self.assertAlmostEqual(part[0][1], 46.55661, places=4)  # starts at Lendava
            self.assertTrue(all(border.contains(*p) for p in part))

    def test_every_point_drawn_lies_in_slovenia_when_trains_run_both_ways(self):
        one, shapes_one = self.lendava()
        two, shapes_two = self.lendava((MURSKO, LENDAVA), TO_CROATIA[::-1])
        two[0]['patterns'][0]['code'] = 'q'
        client = mock.Mock()
        client.query.return_value = {'routes': one + two}
        raillines._built.update(key=None, lines=[])
        with (mock.patch.object(raillines.scheduled, 'service_day', return_value=DAY), mock.patch.object(raillines, 'otp', return_value=client),
              mock.patch.object(raillines.feed_shapes, 'get', return_value=mock.Mock(value={'p': shapes_one['p'], 'q': shapes_two['p']}))):
            lines = raillines._load()
        raillines._built.update(key=None, lines=[])
        self.assertEqual(len(lines), 1)  # one track, however many trains
        self.assertEqual(lines[0]['operatorId'], 'IJPP:INTL-HZPP')
        self.assertGreater(length(lines[0]['geometry']), 4000)
        self.assertTrue(all(border.contains(*p) for p in lines[0]['geometry']))

    def test_a_shape_of_straight_lines_between_stops_does_not_reach_the_border(self):
        routes, shapes = self.lendava(coords=[TO_CROATIA[0], TO_CROATIA[-1]])
        self.assertEqual(raillines.to_the_border(routes, shapes), {})
        self.assertEqual(raillines.to_the_border(routes, shapes, 'thinned'), {})


class MergeToBorderTests(SimpleTestCase):
    def line(self, km: float) -> list:
        return geometry.densify(east(46.0, km), 100)

    def test_only_what_lies_past_the_last_kept_line_is_drawn_and_it_starts_on_that_line(self):
        index = {}
        raillines.merge([self.line(3)], index)
        [added] = raillines.merge_to_border([self.line(5)], index, [])
        self.assertAlmostEqual(length(added), 2000, delta=60)
        self.assertAlmostEqual(added[0][0], 14.5 + 3000 * METRE_X, delta=60 * METRE_X)
        self.assertAlmostEqual(added[-1][0], 14.5 + 5000 * METRE_X, delta=METRE_X)

    def test_a_stretch_with_no_line_near_it_is_drawn_whole(self):
        [added] = raillines.merge_to_border([self.line(5)], {}, [])
        self.assertAlmostEqual(length(added), 5000, delta=60)

    def test_a_short_stub_to_the_border_is_still_drawn(self):
        """Holmec's station lies 80 m from it."""
        index = {}
        raillines.merge([self.line(3)], index)
        [added] = raillines.merge_to_border([self.line(3.08)], index, [])
        self.assertLess(length(added), 150)

    def test_a_line_already_up_to_the_end_adds_nothing(self):
        index = {}
        raillines.merge([self.line(5)], index)
        self.assertEqual(raillines.merge_to_border([self.line(5)], index, []), [])

    def test_a_second_stretch_to_the_same_crossing_adds_nothing(self):
        index, ends = {}, []
        raillines.merge_to_border([self.line(5)], index, ends)
        self.assertEqual(raillines.merge_to_border([geometry.densify(east(46.0 + 60 * METRE, 5), 100)], index, ends), [])

    def test_a_thinned_shape_cutting_the_corner_to_a_crossing_adds_nothing(self):
        index, ends = {}, []
        raillines.merge_to_border([self.line(5)], index, ends)
        corner = [[14.5, 46.0 + 900 * METRE], [14.5 + 5000 * METRE_X, 46.0 + 900 * METRE]]
        self.assertEqual(raillines.merge_to_border([corner], index, ends, raillines.THINNED_WANDER), [])

    def test_another_crossing_is_drawn(self):
        index, ends = {}, []
        raillines.merge_to_border([self.line(5)], index, ends)
        self.assertEqual(len(raillines.merge_to_border([geometry.densify(east(46.2, 5), 100)], index, ends)), 1)
        self.assertEqual(len(ends), 2)


# LP 7812, 2026-11-03: the rail from Sveti Rok ob Sotli west to Rogatec. It runs along the Sotla and the border file puts five
# short stretches of it (up to 24 m deep) on the Croatian side, though every stop on it is in Slovenia.
SV_ROK_ROGATEC = [
    [15.76007, 46.2088], [15.758933, 46.208803], [15.757795, 46.208805], [15.756658, 46.208808],
    [15.75558, 46.208845], [15.754653, 46.20902], [15.753797, 46.20933], [15.753107, 46.209717],
    [15.75249, 46.21021], [15.752046, 46.210798], [15.75167, 46.211385], [15.75157, 46.21193],
    [15.7518, 46.21262], [15.75219, 46.213316], [15.752632, 46.213997], [15.753177, 46.214649],
    [15.753723, 46.215301], [15.754268, 46.215953], [15.75467, 46.216597], [15.754893, 46.217257],
    [15.754955, 46.217935], [15.754922, 46.218598], [15.75481, 46.21922], [15.75438, 46.21977],
    [15.75376, 46.22014], [15.752949999999998, 46.22041], [15.751907, 46.220643], [15.750863, 46.220877],
    [15.74982, 46.22111], [15.74892, 46.22126], [15.747774, 46.221404], [15.746629, 46.221549],
    [15.745483, 46.221693], [15.744338, 46.221837], [15.743192, 46.221982], [15.742217, 46.222057],
    [15.741247, 46.222003], [15.740181, 46.221787], [15.739089, 46.221513], [15.73805, 46.22124],
    [15.73721, 46.22094], [15.73648, 46.22038], [15.736035, 46.219655], [15.73559, 46.21892999999999],
    [15.734934, 46.218488], [15.734046, 46.218062], [15.733302, 46.217572], [15.73263, 46.21705],
    [15.731825, 46.21665], [15.73098, 46.21649], [15.73019, 46.21658], [15.729315, 46.216915],
    [15.728727, 46.217453], [15.728167, 46.218058], [15.72773, 46.21861], [15.72765, 46.21935],
    [15.727973, 46.21997], [15.728543, 46.220483], [15.72905, 46.22096], [15.729295, 46.22152],
    [15.72923, 46.22217], [15.72894, 46.222585], [15.72837, 46.22301], [15.72765, 46.22326],
    [15.72676, 46.22331], [15.725657, 46.22321], [15.724553, 46.22311], [15.723818, 46.223043],
]


class InsidePartsTests(SimpleTestCase):
    def test_a_track_along_the_border_keeps_its_route_between_two_stations(self):
        [part] = border.inside_parts(SV_ROK_ROGATEC)
        self.assertAlmostEqual(geometry.cumulative(part)[-1], geometry.cumulative(SV_ROK_ROGATEC)[-1], delta=60)

    def test_such_a_track_is_not_cut_where_it_is_followed_out_of_a_station(self):
        kept = border.until_abroad(SV_ROK_ROGATEC)
        self.assertAlmostEqual(geometry.cumulative(kept)[-1], geometry.cumulative(SV_ROK_ROGATEC)[-1], delta=60)

    def test_a_line_leaving_for_good_is_still_cut_at_the_border(self):
        self.assertLess(len(border.until_abroad(TO_CROATIA)), len(geometry.densify(TO_CROATIA, border.STEP)))

    def test_a_line_that_stays_home_keeps_its_points(self):
        line = geometry.densify(east(46.05, 2), 500)
        self.assertEqual(border.inside_parts(line), [line])

    def test_a_line_leaving_stops_short_of_the_border(self):
        [part] = border.inside_parts(TO_CROATIA)
        self.assertTrue(all(border.contains(*p) for p in part))
        self.assertAlmostEqual(geometry.cumulative(part)[-1], 4570, delta=100)

    def test_a_line_crossing_a_neighbour_has_a_gap_there(self):
        there_and_back = [*TO_CROATIA, *TO_CROATIA[::-1]]
        parts = border.inside_parts(there_and_back)
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(border.contains(*p) for part in parts for p in part))

    def test_a_line_wholly_abroad_has_nothing(self):
        self.assertEqual(border.inside_parts([[15.44, 47.07], [15.45, 47.07]]), [])


class QueryTests(SimpleTestCase):
    def test_it_asks_for_each_day_of_the_week_by_date(self):
        query = raillines._query(DAY)
        self.assertIn('d0: tripsForDate(serviceDate: "20261101")', query)
        self.assertIn('d7: tripsForDate(serviceDate: "20261108")', query)
        self.assertNotIn('d8:', query)


@AS_DRAWN
class LoadTests(SimpleTestCase):
    def load(self, routes, shapes):
        client = mock.Mock()
        client.query.return_value = {'routes': routes}
        with (mock.patch.object(raillines.scheduled, 'service_day', return_value=DAY),
              mock.patch.object(raillines, 'otp', return_value=client),
              mock.patch.object(raillines.feed_shapes, 'get', return_value=mock.Mock(value=shapes)),
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

    def test_a_train_going_abroad_is_drawn_from_its_last_station_to_the_border(self):
        coords = geometry.densify(TO_CROATIA, 100)
        cum = geometry.cumulative(coords)
        half = cum[-1] / 2
        near_half = geometry.slice_between(coords, cum, 0, half)
        shapes = {'home': {'coords': near_half, 'cum': geometry.cumulative(near_half), 'distances': [0, half]},
                  'out': {'coords': coords, 'cum': cum, 'distances': [0, half, cum[-1]]}}
        home = {'code': 'home', 'stops': [HOME, HOME], 'd1': TRAIN}
        out = {'code': 'out', 'stops': [HOME, HOME, MURSKO], 'd1': TRAIN}
        lines, _ = self.load([route(home, out)], shapes)
        self.assertEqual(len(lines), 2)  # the home line, and on from its last station
        self.assertAlmostEqual(sum(length(line['geometry']) for line in lines), 4570, delta=120)
        self.assertTrue(all(border.contains(*p) for line in lines for p in line['geometry']))


class FeedShapeTests(SimpleTestCase):
    """A long international train's shape as the feed gives it, not thinned to 400 points as the moving trains' are."""

    def shapes(self, coords: list, stops: list) -> dict:
        client = mock.Mock()
        client.query.return_value = {'routes': [{'patterns': [
            {'code': 'ic', 'patternGeometry': {'points': mapping.encode_polyline(coords)}, 'stops': [{'lat': s[1], 'lon': s[0]} for s in stops]}]}]}
        with mock.patch.object(raillines, 'otp', return_value=client):
            return raillines._load_shapes()

    def test_a_long_winding_shape_keeps_its_detail_and_counts_as_detailed(self):
        # 300 km winding gently every 300 m, as Koper - Hodos does: the thinning cut such corners by hundreds of metres.
        coords = [[14.0 + k * 300 * METRE_X, 46.0 + (40 * METRE if k % 2 else 0)] for k in range(1000)]
        stops = [coords[0], coords[500], coords[-1]]
        shape = self.shapes(coords, stops)['ic']
        self.assertGreater(len(shape['coords']), geometry.MAX_POINTS)
        self.assertEqual(raillines._kind(shape, [HOME] * 3), 'detailed')
        self.assertEqual(len(shape['distances']), 3)

    def test_a_pattern_without_a_shape_is_its_stops(self):
        stops = [[14.5, 46.0], [14.6, 46.0], [14.7, 46.1]]
        shape = self.shapes([], stops)['ic']
        self.assertEqual(shape['coords'], stops)
        self.assertEqual(raillines._kind(shape, [HOME] * 3), 'unshaped')

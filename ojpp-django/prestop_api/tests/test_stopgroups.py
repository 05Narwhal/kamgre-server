"""Stops next to each other going the same way are one stop; alike names count; opposite sides never merge."""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import sources, stopgroups, trips
from prestop_api.tests.test_kamgre import stop
from prestop_api.tests.test_lines import LINE_PAYLOAD
from prestop_api.tests.test_stopfix import EAST, NORTH, WEST

BOTH_WAYS = EAST + WEST  # a terminus: buses arrive one way and leave the other


def north_of(lat: float, meters: float) -> float:
    return lat + meters / 110_574


class SimilarNameTests(SimpleTestCase):
    def test_alike_names(self):
        for a, b in [('Brežice OB', 'Brežice Občina'), ('Brežice gim.', 'Brežice gimnazija'), ('Celje Zg.Hudinja', 'Celje Zgornja Hudinja'),
                     ('Bavarski dvor', 'Ljubljana Bavarski dvor'), ('Marles', 'Limbuš Marles'), ('Zg.Duplek', 'Zg. Duplek'),
                     ('Kranj AP', 'Kranj avtobusna postaja'), ('Bled / smer Lesce', 'Bled'), ('Pošta (smer Kranj)', 'Kozina pošta')]:
            self.assertTrue(stopgroups.similar(a, b), (a, b))

    def test_different_stops(self):
        for a, b in [('Kranj AP', 'Kranj ZD'), ('Kranj', 'Kranj Primskovo'), ('Šolska', 'Brezovica pri Ljubljani Š'),
                     ('Peron 1', 'Peron 12'), ('Kranj Labore', 'Kranj Globus'), ('Nova Gorica MAP', 'Nova Gorica AP')]:
            self.assertFalse(stopgroups.similar(a, b), (a, b))


class MergeTests(SimpleTestCase):
    def test_two_poles_of_one_feed_going_the_same_way_and_their_city_twin_are_one_stop(self):
        """Kranj AP: IJPP has two poles 22 m apart for the same direction; the 2026-10-12 rules kept the second apart."""
        stops = [stop('IJPP:1121237', 'Kranj AP', 46.24597, 14.35471), stop('MOKranj:112', 'Kranj AP', 46.24597, 14.35471),
                 stop('IJPP:1121238', 'Kranj AP', north_of(46.24597, 22), 14.35471)]
        merged, groups = stopgroups.merge(stops, ways={s['id']: NORTH for s in stops})
        self.assertEqual(len(merged), 1)
        self.assertEqual(groups['IJPP:1121238'], ['IJPP:1121237', 'IJPP:1121238', 'MOKranj:112'])

    def test_opposite_sides_never_merge_even_with_alike_names(self):
        stops = [stop('IJPP:1', 'Ljubljana Rakovnik', 46.03, 14.52), stop('LPP:1', 'Rakovnik', north_of(46.03, 20), 14.52),
                 stop('IJPP:2', 'Ljubljana Rakovnik', north_of(46.03, 5), 14.52)]
        merged, groups = stopgroups.merge(stops, ways={'IJPP:1': EAST, 'LPP:1': WEST, 'IJPP:2': WEST})
        self.assertEqual(groups['LPP:1'], ['IJPP:2', 'LPP:1'])
        self.assertNotIn('IJPP:1', groups)
        self.assertEqual(len(merged), 2)

    def test_alike_names_within_150_m_merge_under_the_fullest_name(self):
        stops = [stop('IJPP:1123647', 'Brežice OB', 45.90, 15.59), stop('Brezice:10', 'Brežice Občina', north_of(45.90, 140), 15.59)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1123647': EAST, 'Brezice:10': EAST})
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]['id'], merged[0]['name']), ('IJPP:1123647', 'Brežice Občina'))

    def test_beyond_150_m_stays_apart(self):
        stops = [stop('IJPP:1', 'Brežice OB', 45.90, 15.59), stop('Brezice:10', 'Brežice Občina', north_of(45.90, 200), 15.59),
                 stop('IJPP:2', 'Brežice OB', north_of(45.90, 200), 15.591)]
        merged, _ = stopgroups.merge(stops, ways={s['id']: EAST for s in stops})
        self.assertEqual(sorted(len(s.get('memberIds', [s['id']])) for s in merged), [1, 2])

    def test_a_group_never_spans_more_than_150_m(self):
        stops = [stop(f'IJPP:{i}', 'Velenje Pesje', north_of(46.36, 100 * i), 15.15) for i in range(3)]
        _, groups = stopgroups.merge(stops, ways={s['id']: NORTH for s in stops})
        self.assertEqual(len(groups.get('IJPP:1', [])), 2)
        self.assertNotIn('IJPP:2' if 'IJPP:0' in groups['IJPP:1'] else 'IJPP:0', groups)

    def test_a_terminus_served_both_ways_is_not_one_side_s_stop(self):
        stops = [stop('IJPP:1', 'Kropa', 46.29, 14.20), stop('IJPP:2', 'Kropa', north_of(46.29, 15), 14.20)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1': BOTH_WAYS, 'IJPP:2': EAST})
        self.assertEqual(len(merged), 2)

    def test_a_few_patterns_using_the_other_side_s_pole_do_not_make_it_two_way(self):
        """Kino Šiška (2026-10-14): IJPP's two poles each had a handful of patterns going the other way, so both looked
        two-way, were 'alike' and merged across the road, and LPP's one-way poles joined neither."""
        sw, ne = (46.0705, 14.4885), (46.0685, 14.4915)  # the stops before and after along Celovška
        a, b = (46.06964, 14.489526), (46.069202, 14.49031)  # the two sides, 78 m apart
        positions = {'prev': sw, 'next': ne, 'IJPP:1165648': a, 'IJPP:1165649': b, 'LPP:9afb': a, 'LPP:9cfa': b}
        runs = ([['next', 'IJPP:1165648', 'prev']] * 91 + [['prev', 'IJPP:1165648', 'next']] * 11
                + [['prev', 'IJPP:1165649', 'next']] * 79 + [['next', 'IJPP:1165649', 'prev']] * 3
                + [['next', 'LPP:9afb', 'prev']] * 5 + [['prev', 'LPP:9cfa', 'next']] * 5)
        ways = stopgroups.directions(runs, positions)
        self.assertEqual(len(ways['IJPP:1165648']), 1)
        stops = [stop('IJPP:1165648', 'Ljubljana Kino Šiška', *a), stop('IJPP:1165649', 'Ljubljana Kino Šiška', *b),
                 stop('LPP:9afb', 'Kino Šiška', *a), stop('LPP:9cfa', 'Kino Šiška', *b)]
        merged, groups = stopgroups.merge(stops, ways=ways)
        self.assertEqual(groups['LPP:9afb'], ['IJPP:1165648', 'LPP:9afb'])
        self.assertEqual(groups['LPP:9cfa'], ['IJPP:1165649', 'LPP:9cfa'])
        self.assertEqual([s['name'] for s in merged], ['Ljubljana Kino Šiška'] * 2)

    def test_ljubljana_tivoli_and_tivoli_going_the_same_way_are_one_stop(self):
        a, b = (46.060423, 14.497217), (46.060444, 14.497163)  # IJPP and LPP pole, 5 m apart
        positions = {'prev': (46.0615, 14.4955), 'next': (46.0590, 14.4990), 'IJPP:1165686': a, 'LPP:7484': b}
        ways = stopgroups.directions([['prev', 'IJPP:1165686', 'next']] * 91 + [['next', 'IJPP:1165686', 'prev']] * 4
                                     + [['prev', 'LPP:7484', 'next']] * 3, positions)
        merged, _ = stopgroups.merge([stop('IJPP:1165686', 'Ljubljana Tivoli', *a), stop('LPP:7484', 'Tivoli', *b)], ways=ways)
        self.assertEqual([(s['name'], s.get('memberIds')) for s in merged], [('Ljubljana Tivoli', ['IJPP:1165686', 'LPP:7484'])])

    def test_a_stop_served_both_ways_alike_often_stays_two_way(self):
        ways = stopgroups.directions([['w', 'x', 'e']] * 6 + [['e', 'x', 'w']] * 2, {'w': (46.0, 13.999), 'x': (46.0, 14.0), 'e': (46.0, 14.001)})
        self.assertEqual(len(ways['x']), 2)

    def test_one_feed_with_an_unknown_direction_stays_apart(self):
        stops = [stop('IJPP:1', 'Kranj AP', 46.24597, 14.35471), stop('IJPP:2', 'Kranj AP', north_of(46.24597, 10), 14.35471)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1': NORTH})
        self.assertEqual(len(merged), 2)

    def test_a_railway_station_keeps_its_name_and_takes_only_namesakes(self):
        stops = [stop('IJPP:rail', 'Kranj', 46.2400, 14.3500, modes=('rail',)), stop('IJPP:1', 'Kranj ŽP', north_of(46.24, 40), 14.35),
                 stop('MOKranj:150', 'Kranj kolodvor', north_of(46.24, 60), 14.35)]
        merged, groups = stopgroups.merge(stops, ways={'IJPP:1': EAST, 'MOKranj:150': EAST})
        self.assertEqual(groups['IJPP:1'], ['IJPP:rail', 'IJPP:1'])
        self.assertEqual(next(s['name'] for s in merged if s['id'] == 'IJPP:rail'), 'Kranj')


class MemberNameTests(SimpleTestCase):
    def test_a_line_view_names_each_member_stop_itself(self):
        payload = {**LINE_PAYLOAD, 'patterns': [{**LINE_PAYLOAD['patterns'][0], 'stops': [
            {'gtfsId': 'LPP:1', 'name': 'Bavarski dvor', 'lat': 46.0588, 'lon': 14.5059}, {'gtfsId': 'LPP:2', 'name': 'Ajdovščina', 'lat': 46.0546, 'lon': 14.5057}]}]}
        with mock.patch.object(sources, 'stop_group', return_value=['IJPP:1', 'LPP:1']), mock.patch.object(trips, 'road_shape', return_value=([], True)):
            line, _ = trips.build_line(payload, date(2026, 10, 10))
        self.assertEqual(line['patterns'][0]['stops'][0]['name'], 'Bavarski dvor')

    def test_a_merged_board_row_names_the_member_stop_it_leaves_from(self):
        row = lambda sid, trip: {'id': f'{sid}@{trip}', 'stopId': sid, 'routeName': trip, 'scheduledAt': '2026-10-13T10:00:00Z', 'destination': 'Bled'}
        boards = {'IJPP:1': [row('IJPP:1', '1')], 'LPP:1': [row('LPP:1', '2')]}
        with mock.patch.object(sources, 'stop_group', return_value=['IJPP:1', 'LPP:1']), \
                mock.patch.object(sources, 'alerts', return_value=[]), \
                mock.patch.object(sources, '_member_board', side_effect=lambda m, *a: boards[m]), \
                mock.patch.object(sources, 'stop_names', return_value={'IJPP:1': 'Ljubljana Bavarski dvor', 'LPP:1': 'Bavarski dvor'}), \
                mock.patch.object(sources, '_with_live_platforms', side_effect=lambda entries, *a, **k: entries):
            items = sources.board('IJPP:1', 'departure', 0, 'sl')
        self.assertEqual({i['stopId']: i['stopName'] for i in items}, {'IJPP:1': 'Ljubljana Bavarski dvor', 'LPP:1': 'Bavarski dvor'})

    def test_a_merged_board_drops_another_feeds_copy_but_keeps_a_second_bus(self):
        """D3: A6196 13:10 Škofja Loka – Kranj AP runs as two trips of one feed (IJPP:455744 + IJPP:455745), and on
        2026-10-22 two vehicles drove them (as every such pair recorded that day: 82 of 82): both are buses. A copy
        from another feed (LPP 51 as IJPP's too) is still one bus, and one trip at two members in one minute one row."""
        def row(sid, trip, line, dest='Kranj AP', at='2026-10-22T11:10:00Z'):
            return {'id': f'{trip}@20261022/{sid}', 'tripId': trip, 'stopId': sid, 'routeName': line, 'scheduledAt': at, 'destination': dest}
        boards = {'IJPP:1': [row('IJPP:1', 'IJPP:455744', 'A6196'), row('IJPP:1', 'IJPP:455745', 'A6196'),
                             row('IJPP:1', 'IJPP:77', '51', 'Polhov Gradec'), row('IJPP:1', 'IJPP:5', '5', 'Bled')],
                  'LPP:1': [row('LPP:1', 'LPP:9', '51', 'Polhov Gradec')],
                  'IJPP:2': [row('IJPP:2', 'IJPP:5', '5', 'Bled')]}
        with mock.patch.object(sources, 'stop_group', return_value=['IJPP:1', 'LPP:1', 'IJPP:2']), \
                mock.patch.object(sources, 'alerts', return_value=[]), \
                mock.patch.object(sources, '_member_board', side_effect=lambda m, *a: boards[m]), \
                mock.patch.object(sources, 'stop_names', return_value={}), \
                mock.patch.object(sources, '_with_live_platforms', side_effect=lambda entries, *a, **k: entries):
            items = sources._board('IJPP:1', 'departure', 0, 'sl')
        self.assertEqual(sorted(i['tripId'] for i in items), ['IJPP:455744', 'IJPP:455745', 'IJPP:5', 'IJPP:77'])

    def test_a_train_the_feed_lists_twice_is_one_row(self):
        """A train number runs once: LP 4208 Nova Gorica 07:28 – Jesenice is in the feed on two routes (IJPP:456511 on
        IJPP:64515, IJPP:476680 on IJPP:66421, the same times; 23 Oct 2026), and D3's second-bus rule listed it twice."""
        def row(trip, mode='rail', line='LP 4208'):
            return {'id': f'{trip}@20261023/1', 'tripId': trip, 'stopId': 'IJPP:1', 'routeName': line, 'mode': mode,
                    'scheduledAt': '2026-10-23T05:28:00Z', 'destination': 'Jesenice'}
        boards = {'IJPP:1': [row('IJPP:456511'), row('IJPP:476680'), row('IJPP:8', 'bus', 'A1'), row('IJPP:9', 'bus', 'A1')], 'IJPP:2': []}
        with mock.patch.object(sources, 'stop_group', return_value=['IJPP:1', 'IJPP:2']), \
                mock.patch.object(sources, 'alerts', return_value=[]), \
                mock.patch.object(sources, '_member_board', side_effect=lambda m, *a: boards[m]), \
                mock.patch.object(sources, 'stop_names', return_value={}), \
                mock.patch.object(sources, '_with_live_platforms', side_effect=lambda entries, *a, **k: entries):
            items = sources._board('IJPP:1', 'departure', 0, 'sl')
        self.assertEqual(sorted(i['tripId'] for i in items), ['IJPP:456511', 'IJPP:8', 'IJPP:9'])
        # A station merged with nothing (Most na Soči) as well.
        with mock.patch.object(sources, 'stop_group', return_value=['IJPP:1']), \
                mock.patch.object(sources, 'alerts', return_value=[]), \
                mock.patch.object(sources, '_member_board', side_effect=lambda m, *a: boards[m]), \
                mock.patch.object(sources, '_with_live_platforms', side_effect=lambda entries, *a, **k: entries):
            items = sources._board('IJPP:1', 'departure', 0, 'sl')
        self.assertEqual(sorted(i['tripId'] for i in items), ['IJPP:456511', 'IJPP:8', 'IJPP:9'])

    def test_a_board_asked_for_before_the_stop_index_is_built_waits_for_it(self):
        """D3: for ~20 s after a start (warm.py builds the stop index after the timetable) a merged stop's board
        listed its head stop only; a board waits for the index, other callers still never wait."""
        from prestop_api.upstream import Cached
        index = Cached(lambda: {'groups': {'IJPP:1': ['IJPP:1', 'LPP:1']}}, ttl=3600, max_stale=3600)
        with mock.patch.object(sources, 'stops', index):
            self.assertEqual(sources.stop_group('IJPP:1'), ['IJPP:1'])
            self.assertIsNone(index.peek())
            self.assertEqual(sources.stop_group('IJPP:1', wait=True), ['IJPP:1', 'LPP:1'])
        failing = Cached(mock.Mock(side_effect=RuntimeError('OTP down')), ttl=3600, max_stale=3600)
        with mock.patch.object(sources, 'stops', failing), self.assertLogs('prestop_api.sources', 'WARNING'):
            self.assertEqual(sources.stop_group('IJPP:1', wait=True), ['IJPP:1'])


class SearchTests(SimpleTestCase):
    """Search shows one result per place: namesakes far apart (Radovljica's bus stop, 340 m from its station) are two."""

    def test_namesakes_beyond_the_merge_range_or_bus_and_rail_stay_apart(self):
        listed = [stop('IJPP:1122815', 'Radovljica', 46.340415, 14.173759, modes=('rail',)),
                  stop('IJPP:1129160', 'Radovljica', 46.343418, 14.17281),
                  stop('IJPP:1', 'Kovor', 46.30, 14.30), stop('IJPP:2', 'Kovor', north_of(46.30, 30), 14.30),  # both sides of the road
                  stop('IJPP:3', 'Kovor', north_of(46.30, 400), 14.30)]
        with mock.patch.object(sources.stops, 'get', return_value=mock.Mock(value={'list': listed})):
            found = sources.search_stations('Radovljica', 10)
            # The town first (both stations), then each of them on its own.
            self.assertEqual([(p['id'], p['modes']) for p in found], [('town:IJPP:1122815', ['bus', 'rail']), ('IJPP:1122815', ['rail']), ('IJPP:1129160', ['bus'])])
            self.assertEqual((found[0]['category'], found[0]['stopId'], found[0]['stopIds']), ('town', 'IJPP:1122815', ['IJPP:1122815', 'IJPP:1129160']))
            self.assertEqual(found[1]['latitude'], 46.340415)  # the station where it is, not between the two
            self.assertEqual(sorted(p['stopId'] for p in sources.search_stations('Kovor', 10)), ['IJPP:1', 'IJPP:3'])

    def test_a_town_is_its_railway_station_and_its_bus_station(self):
        listed = [stop('IJPP:1122811', 'Kranj', 46.238955, 14.348073, modes=('bus', 'rail')),
                  stop('IJPP:1121309', 'Kranj ŽP', 46.23705, 14.349335),  # the station's own bus stop, 230 m
                  stop('IJPP:1121246', 'Kranj Globus', 46.242085, 14.355485),
                  stop('IJPP:1121237', 'Kranj AP', 46.24589, 14.354703),  # the bus station, 940 m
                  stop('IJPP:1121238', 'Kranj AP', 46.24582, 14.35453),  # its other side
                  stop('IJPP:9', 'Kranjska Gora', 46.4847, 13.7856)]
        with mock.patch.object(sources.stops, 'get', return_value=mock.Mock(value={'list': listed})):
            found = sources.search_stations('kranj', 10)
            self.assertEqual([p['id'] for p in found][:3], ['town:IJPP:1122811', 'IJPP:1122811', 'IJPP:1121237'])
            self.assertEqual(found[0]['stopIds'], ['IJPP:1122811', 'IJPP:1121237', 'IJPP:1121238'])  # every pole of both
            self.assertEqual({p['id'] for p in found[3:]}, {'IJPP:1121309', 'IJPP:1121246', 'IJPP:9'})
            # Stations stop being one town some way apart, and a bus stop that only shares the start of the name is not one.
            far = [stop('IJPP:1', 'Kranj', 46.0, 14.0, modes=('rail',)), stop('IJPP:2', 'Kranj AP', north_of(46.0, 3500), 14.0)]
            with mock.patch.object(sources.stops, 'get', return_value=mock.Mock(value={'list': far})):
                self.assertEqual([p['id'] for p in sources.search_stations('Kranj', 10)], ['IJPP:1', 'IJPP:2'])
            self.assertEqual([p['id'] for p in sources.search_stations('Kranjska', 10)], ['IJPP:9'])
        # A part of a town with its own halt and bus stop is not a town.
        district = [stop('IJPP:1', 'Celje', 46.0, 14.0, modes=('rail',)), stop('IJPP:2', 'Celje Lava', 46.01, 14.0, modes=('rail',)),
                    stop('IJPP:3', 'Celje Lava', north_of(46.01, 200), 14.0)]
        with mock.patch.object(sources.stops, 'get', return_value=mock.Mock(value={'list': district})):
            self.assertEqual([p['id'] for p in sources.search_stations('Celje Lava', 10)], ['IJPP:2', 'IJPP:3'])


def way(*degrees: float) -> list[tuple[float, float]]:
    """Directions of travel (degrees from north, busiest first) as stopgroups.directions gives them."""
    import math
    return [(round(math.sin(math.radians(d)), 2), round(math.cos(math.radians(d)), 2)) for d in degrees]


def merged_ids(merged: list[dict]) -> list[list[str]]:
    return sorted(sorted(s.get('memberIds') or [s['id']]) for s in merged)


class NamedCasesTests(SimpleTestCase):
    """The stops the user reported (spec 2026-10-19 A3), with the feeds' positions and directions of 2026-10-19."""

    def test_kosmaceva_is_one_stop_per_side(self):
        # IJPP's and LPP's eastbound poles are 20 m apart; their busiest ways differ (89° and 347°), but every way at
        # one is a way at the other.
        stops = [stop('IJPP:1167169', 'Kosmačeva', 46.100885, 14.460836), stop('IJPP:1167170', 'Kosmačeva', 46.100982, 14.461081),
                 stop('LPP:d987', 'Kosmačeva', 46.100723, 14.460546), stop('LPP:fb77', 'Kosmačeva', 46.101002, 14.461034)]
        ways = {'IJPP:1167169': way(89, 22), 'IJPP:1167170': way(213, 203), 'LPP:d987': way(212, 163), 'LPP:fb77': way(347, 103)}
        merged, _ = stopgroups.merge(stops, ways=ways)
        self.assertEqual(merged_ids(merged), [['IJPP:1167169', 'LPP:fb77'], ['IJPP:1167170', 'LPP:d987']])

    def test_litostrojska_sits_at_a_pole_and_the_turning_loop_is_its_own_stop(self):
        stops = [stop('IJPP:1167150', 'Litostrojska', 46.076794, 14.488728), stop('LPP:300f', 'LITOSTROJSKA', 46.077721, 14.488358),
                 stop('LPP:9a48', 'Litostrojska', 46.076759, 14.488915), stop('IJPP:1167151', 'Litostrojska', 46.076783, 14.489016),
                 stop('LPP:ac3a', 'Litostrojska', 46.076813, 14.488618)]
        ways = {'IJPP:1167150': way(26), 'LPP:300f': way(338, 169), 'LPP:9a48': way(29, 353, 18), 'IJPP:1167151': way(209, 210, 29),
                'LPP:ac3a': way(213, 207, 209, 183, 158)}
        merged, _ = stopgroups.merge(stops, ways=ways)
        self.assertEqual(merged_ids(merged), [['IJPP:1167150', 'LPP:9a48'], ['IJPP:1167151', 'LPP:ac3a'], ['LPP:300f']])
        north = next(s for s in merged if 'LPP:9a48' in (s.get('memberIds') or []))
        self.assertEqual((north['latitude'], north['longitude']), (46.076759, 14.488915))  # the LPP pole, not between two

    def test_slovenija_avto_is_one_stop_per_side(self):
        # The IJPP pole served both ways stands 3.6 m from the LPP northbound pole: one stop there, not a southbound
        # marker on the northbound side.
        stops = [stop('IJPP:1165667', 'Ljubljana Slovenija avto', 46.072988, 14.486411), stop('LPP:484b', 'Slovenija avto', 46.073196, 14.486220),
                 stop('IJPP:1165669', 'Ljubljana Slovenija avto', 46.073882, 14.486591), stop('LPP:dfde', 'Slovenija avto', 46.073914, 14.486595)]
        ways = {'IJPP:1165667': way(149, 145), 'LPP:484b': way(175, 147, 145, 104, 205), 'IJPP:1165669': way(173, 334, 357),
                'LPP:dfde': way(29, 46, 57, 353, 331)}
        merged, _ = stopgroups.merge(stops, ways=ways)
        self.assertEqual(merged_ids(merged), [['IJPP:1165667', 'LPP:484b'], ['IJPP:1165669', 'LPP:dfde']])

    def test_trzic_bus_station_is_one_station(self):
        from prestop_api import stopfix
        stops = [stop('IJPP:1131250', 'Tržič', 46.362263, 14.308901), stop('IJPP:1131251', 'Tržič', 46.362291, 14.308698),
                 stop('IJPP:1131252', 'Tržič', 46.362150, 14.308822)]
        ways = {'IJPP:1131250': way(230, 51), 'IJPP:1131251': way(244, 224), 'IJPP:1131252': way(65, 44)}
        self.assertEqual(len(stopgroups.merge(stops, ways=ways)[0]), 3)  # the feed's three bays, served opposite ways
        merged, _ = stopgroups.merge(stops, stopfix.read_overrides()['merge'], ways=ways)
        self.assertEqual(merged_ids(merged), [['IJPP:1131250', 'IJPP:1131251', 'IJPP:1131252']])

    def test_one_pole_in_two_feeds_is_one_stop_whatever_their_lines_do_next(self):
        stops = [stop('IJPP:1121360', 'Zgornje Bitnje K', 46.221942, 14.339947), stop('MOKranj:103', 'Zgornje Bitnje K', 46.221940, 14.339950),
                 stop('IJPP:1121361', 'Zgornje Bitnje K', 46.222059, 14.339611), stop('MOKranj:105', 'Zgornje Bitnje K', 46.222060, 14.339610)]
        ways = {'IJPP:1121360': way(343), 'MOKranj:103': way(261), 'IJPP:1121361': way(161), 'MOKranj:105': way(85)}
        merged, _ = stopgroups.merge(stops, ways=ways)
        self.assertEqual(merged_ids(merged), [['IJPP:1121360', 'MOKranj:103'], ['IJPP:1121361', 'MOKranj:105']])

    def test_two_poles_of_one_feed_both_served_both_ways_stay_apart_across_the_road(self):
        stops = [stop('IJPP:1', 'Notranje Gorice mostiček', 46.0, 14.4), stop('IJPP:2', 'Notranje Gorice mostiček', north_of(46.0, 20), 14.4)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1': way(90, 270), 'IJPP:2': way(270, 90)})
        self.assertEqual(len(merged), 2)
        # Termini elsewhere do not make them one place: runs pass through both.
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1': way(90, 270), 'IJPP:2': way(270, 90)}, ends={'IJPP:9'})
        self.assertEqual(len(merged), 2)


class TwinTests(SimpleTestCase):
    """Spec 2026-10-23 E7: the twins stop_audit found (E6) become one marker; opposite sides still never do."""

    def test_kolodvor_and_sz_kolodvor_two_termini_at_one_spot_are_one_stop(self):
        # LPP's two poles 5 m apart, both served both ways (lines end and start there), busiest ways opposite.
        stops = [stop('LPP:db9f7130', 'KOLODVOR', 46.057991, 14.514928), stop('LPP:e65047c0', 'SŽ KOLODVOR', north_of(46.057991, 5), 14.514928)]
        ways = {'LPP:db9f7130': way(90, 270), 'LPP:e65047c0': way(270, 90)}
        self.assertEqual(len(stopgroups.merge(stops, ways=ways)[0]), 2)  # as before E7, without knowing where runs end
        merged, _ = stopgroups.merge(stops, ways=ways, ends={'LPP:db9f7130', 'LPP:e65047c0'})
        self.assertEqual(merged_ids(merged), [['LPP:db9f7130', 'LPP:e65047c0']])
        self.assertEqual(merged[0]['name'], 'SŽ KOLODVOR')
        # Further apart than one spot, one feed's termini are two places.
        far = [stops[0], stop('LPP:e65047c0', 'SŽ KOLODVOR', north_of(46.057991, 40), 14.514928)]
        self.assertEqual(len(stopgroups.merge(far, ways=ways, ends={'LPP:db9f7130', 'LPP:e65047c0'})[0]), 2)

    def test_two_poles_of_one_feed_for_one_way_differing_only_in_case_are_one_stop(self):
        stops = [stop('LPP:91fb', 'Sostro', 46.04, 14.62), stop('LPP:d9f2', 'SOSTRO', north_of(46.04, 9), 14.62)]
        merged, _ = stopgroups.merge(stops, ways={'LPP:91fb': way(80, 20), 'LPP:d9f2': way(85)})
        self.assertEqual(merged_ids(merged), [['LPP:91fb', 'LPP:d9f2']])
        # Beyond one spot they are two poles of their own.
        far = [stops[0], stop('LPP:d9f2', 'SOSTRO', north_of(46.04, 40), 14.62)]
        self.assertEqual(len(stopgroups.merge(far, ways={'LPP:91fb': way(80, 20), 'LPP:d9f2': way(85)})[0]), 2)

    def test_a_pole_served_both_ways_and_one_for_its_main_way_are_one_stop_only_at_one_pole(self):
        # Cesta na Drenik: IJPP's two poles 4 m apart; Kropa's (test above) 15 m apart stay two.
        stops = [stop('IJPP:1150250', 'Cesta na Drenik', 46.07, 14.47), stop('IJPP:1150251', 'Cesta na Drenik', north_of(46.07, 4), 14.47)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1150250': BOTH_WAYS, 'IJPP:1150251': EAST})
        self.assertEqual(merged_ids(merged), [['IJPP:1150250', 'IJPP:1150251']])

    def test_opposite_sides_of_one_feed_at_one_spot_stay_apart(self):
        stops = [stop('IJPP:1128105', 'Padna', 45.45, 13.70), stop('IJPP:1128106', 'Padna', north_of(45.45, 8), 13.70)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1128105': way(0), 'IJPP:1128106': way(180)}, ends=set())
        self.assertEqual(len(merged), 2)

    def test_two_feeds_namesake_bus_stations_are_one_station(self):
        # Velenje: IJPP's bus station and the city line's "AP Velenje" 83 m apart, both where runs start and end.
        stops = [stop('IJPP:1122728', 'Velenje', 46.3600, 15.1100), stop('MOVelenje:2', 'AP Velenje', north_of(46.3600, 83), 15.1100)]
        ways = {'IJPP:1122728': way(90, 270), 'MOVelenje:2': way(90, 270)}
        self.assertEqual(len(stopgroups.merge(stops, ways=ways)[0]), 2)
        merged, _ = stopgroups.merge(stops, ways=ways, ends={'IJPP:1122728', 'MOVelenje:2'})
        self.assertEqual(merged_ids(merged), [['IJPP:1122728', 'MOVelenje:2']])
        # A turning loop of the same name that is no bus station stays a place of its own beyond NEAR_METERS.
        loop = [stop('IJPP:1167150', 'Litostrojska', 46.0768, 14.4887), stop('LPP:300f', 'LITOSTROJSKA', north_of(46.0768, 106), 14.4887)]
        self.assertEqual(len(stopgroups.merge(loop, ways={'IJPP:1167150': way(26), 'LPP:300f': way(338, 169)}, ends={'IJPP:1167150', 'LPP:300f'})[0]), 2)

    def test_a_bus_station_s_bays_served_opposite_ways_stay_as_they_were(self):
        stops = [stop('IJPP:1131250', 'Tržič', 46.362263, 14.308901), stop('IJPP:1131251', 'Tržič', 46.362291, 14.308698),
                 stop('IJPP:1131252', 'Tržič', 46.362150, 14.308822)]
        ways = {'IJPP:1131250': way(230, 51), 'IJPP:1131251': way(244, 224), 'IJPP:1131252': way(65, 44)}
        self.assertEqual(len(stopgroups.merge(stops, ways=ways, ends={s['id'] for s in stops})[0]), 3)


class SideTests(SimpleTestCase):
    """place_sides: Slovenia drives on the right, so the northbound stop is east of the southbound one."""

    def pair(self, east_lon, west_lon):
        north, south = stop('IJPP:n', 'Vas', 46.0, east_lon), stop('IJPP:s', 'Vas', 46.0, west_lon)
        return [north, south], {'IJPP:n': way(0), 'IJPP:s': way(180)}

    def test_poles_on_one_spot_move_apart_each_to_its_side(self):
        markers, ways = self.pair(14.5, 14.5)
        self.assertEqual(stopgroups.place_sides(markers, list(markers), ways), 2)
        north, south = markers
        self.assertGreater(north['longitude'], south['longitude'])
        self.assertAlmostEqual(stopgroups.meters(north, south), 8, delta=0.5)  # 4 m each side of the middle
        self.assertEqual((north['latitude'], south['latitude']), (46.0, 46.0))  # along the road they stay

    def test_swapped_poles_change_sides_and_a_close_osm_pole_wins(self):
        markers, ways = self.pair(14.4999, 14.5001)  # the northbound one ~15 m west of the southbound one
        osm = [(46.00002, 14.50011)]  # a mapped pole 8.5 m east of the middle
        stopgroups.place_sides(markers, list(markers), ways, osm=osm)
        north, south = markers
        self.assertEqual((north['latitude'], north['longitude']), osm[0])
        self.assertLess(south['longitude'], 14.5)

    def test_stops_on_their_own_sides_hand_placed_ones_and_far_namesakes_stay(self):
        for markers, ways, fixed in [(*self.pair(14.5001, 14.4999), set()), (*self.pair(14.5, 14.5), {'IJPP:n'})]:
            before = [dict(m) for m in markers]
            self.assertEqual(stopgroups.place_sides(markers, list(markers), ways, fixed), 0)
            self.assertEqual(markers, before)
        far = [stop('IJPP:n', 'Vas', 46.0, 14.5), stop('IJPP:s', 'Vas', north_of(46.0, 90), 14.5)]
        self.assertEqual(stopgroups.place_sides(far, list(far), {'IJPP:n': way(0), 'IJPP:s': way(180)}), 0)

class MarkerPoleTests(SimpleTestCase):
    """Spec 2026-10-23 E8: a merged marker sits on a pole, not at a far member that comes first by id."""
    POLE = (46.0594, 14.5206)

    def test_poles_far_apart_put_the_marker_where_most_members_stand(self):
        # Ljubljana Viadukt: IJPP's and LPP's pole 5 m apart, line 27's LPP pole 130 m west came first by id.
        lat, lon = self.POLE
        stops = [stop('IJPP:1165693', 'Viadukt', lat, lon), stop('LPP:f14a', 'Viadukt', north_of(lat, 5), lon),
                 stop('LPP:abca', 'Viadukt', lat, lon - 130 / 77_230)]
        merged, _ = stopgroups.merge(stops, ways={s['id']: way(225) for s in stops})
        self.assertEqual(merged_ids(merged), [['IJPP:1165693', 'LPP:abca', 'LPP:f14a']])
        self.assertLess(stopgroups.meters(merged[0], {'latitude': lat, 'longitude': lon}), 10)

    def test_a_pole_placed_by_hand_places_its_marker(self):
        # Zg. Duplek: IJPP's stop moved onto its OSM pole (stop_overrides.csv); Marprom's pole is 70 m off.
        lat, lon = self.POLE
        stops = [stop('IJPP:1120991', 'Zg. Duplek', lat, lon), stop('MARPROM:403', 'Zg. Duplek', north_of(lat, 70), lon)]
        ways = {'IJPP:1120991': way(0), 'MARPROM:403': way(0)}
        self.assertEqual(stopgroups.merge(stops, ways=ways)[0][0]['latitude'], round(north_of(lat, 70), 6))
        merged, _ = stopgroups.merge(stops, ways=ways, fixed=frozenset({'IJPP:1120991'}))
        self.assertEqual(merged_ids(merged), [['IJPP:1120991', 'MARPROM:403']])
        self.assertEqual((merged[0]['latitude'], merged[0]['longitude']), (lat, lon))

    def test_a_railway_station_keeps_its_marker(self):
        lat, lon = self.POLE
        stops = [stop('IJPP:rail', 'Grosuplje', lat, lon, modes=('rail',)), stop('IJPP:1', 'Grosuplje', north_of(lat, 60), lon),
                 stop('IJPP:2', 'Grosuplje', north_of(lat, 66), lon)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1': EAST, 'IJPP:2': WEST}, fixed=frozenset({'IJPP:1'}))
        rail = next(s for s in merged if s['id'] == 'IJPP:rail')
        self.assertEqual((rail['latitude'], rail['longitude']), (lat, lon))

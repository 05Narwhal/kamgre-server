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

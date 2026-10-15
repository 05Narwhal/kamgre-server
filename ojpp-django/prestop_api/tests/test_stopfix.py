import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import stopfix, stopgroups
from prestop_api.tests.test_kamgre import stop

CSV = '''# comment
stop_id,type,lat,lon,merge_into,label,note
IJPP:1121103,stop,45.538642,13.737744,,,OSM
IJPP:1121103,station,45.538642,13.737744,,,OSM
IJPP:1123012,stop,,,IJPP:1121103,,hub
LPP:avtomontaza,stop,,,IJPP:1167340,Aleja,renamed
SZ:42,replacement,46.05,14.51,,Bus stop in front of the station,notice
X:bad,teleport,1,2,,,unknown type
'''


def otp_stop(id_, lat, lon):
    return {'gtfsId': id_, 'name': id_, 'lat': lat, 'lon': lon}


class OverrideTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'stop_overrides.csv'
        self.path.write_text(CSV, encoding='utf-8')
        self.overrides = stopfix.read_overrides(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def test_rows_by_type(self):
        self.assertEqual(self.overrides['stops'], {'IJPP:1121103': (45.538642, 13.737744)})
        self.assertEqual(self.overrides['stations'], {'IJPP:1121103': (45.538642, 13.737744)})
        self.assertEqual(self.overrides['merge'], {'IJPP:1123012': 'IJPP:1121103', 'LPP:avtomontaza': 'IJPP:1167340'})
        self.assertEqual(self.overrides['names'], {'LPP:avtomontaza': 'Aleja'})
        self.assertEqual(self.overrides['replacement']['SZ:42'][0]['label'], 'Bus stop in front of the station')

    def test_avtomontaza_is_folded_into_aleja(self):
        # LPP's "Avtomontaža" is the pole of Aleja on line 1: one stop, called Aleja everywhere.
        raw = [{**otp_stop('IJPP:1167340', 46.077094, 14.482374), 'name': 'Aleja'},
               {**otp_stop('LPP:avtomontaza', 46.077312, 14.4824), 'name': 'Avtomontaža'}]
        fixed = stopfix.correct(raw, self.overrides, {})
        self.assertEqual([s['name'] for s in fixed], ['Aleja', 'Aleja'])
        built = [stop(s['gtfsId'], s['name'], s['lat'], s['lon'], operators=(s['gtfsId'].split(':')[0] + ':x',)) for s in fixed]
        merged, groups = stopgroups.merge(built, self.overrides['merge'])
        self.assertEqual([(s['id'], s['name']) for s in merged], [('IJPP:1167340', 'Aleja')])
        self.assertEqual(groups['LPP:avtomontaza'], ['IJPP:1167340', 'LPP:avtomontaza'])
        with mock.patch.object(stopfix, 'tables', return_value=(self.overrides, {})):
            self.assertEqual(stopfix.renamed('LPP:avtomontaza', 'Avtomontaža'), 'Aleja')
            self.assertEqual(stopfix.renamed('IJPP:1', 'Kino Šiška'), 'Kino Šiška')
            self.assertIsNone(stopfix.renamed(None, None))

    def test_override_beats_the_road_snap(self):
        snaps = {stopfix.snap_key('IJPP:1121103', 45.53824, 13.738235): [45.5, 13.7, 80.0]}
        [fixed] = stopfix.correct([otp_stop('IJPP:1121103', 45.53824, 13.738235)], self.overrides, snaps)
        self.assertEqual((fixed['lat'], fixed['lon']), (45.538642, 13.737744))
        self.assertEqual(fixed['feedLat'], 45.53824)

    def test_snap_only_between_the_limits(self):
        none = {'stops': {}}
        snaps = {stopfix.snap_key('A', 46.0, 14.0): [46.0003, 14.0, 33.0],
                 stopfix.snap_key('B', 46.1, 14.0): [46.1006, 14.0, 66.0],
                 stopfix.snap_key('C', 46.2, 14.0): [46.202, 14.0, 222.0]}
        fixed = stopfix.correct([otp_stop('A', 46.0, 14.0), otp_stop('B', 46.1, 14.0), otp_stop('C', 46.2, 14.0)], none, snaps)
        self.assertEqual([(s['lat'], s['lon']) for s in fixed], [(46.0, 14.0), (46.1006, 14.0), (46.2, 14.0)])

    def test_applying_twice_changes_nothing(self):
        raw = [otp_stop('IJPP:1121103', 45.53824, 13.738235), otp_stop('IJPP:1123012', 45.53897, 13.738534)]
        once = stopfix.correct(raw, self.overrides, {})
        twice = stopfix.correct(once, self.overrides, {})
        self.assertEqual([(s['lat'], s['lon']) for s in once], [(s['lat'], s['lon']) for s in twice])


class NormalizeTests(SimpleTestCase):
    def test_stop_kind_words_case_and_diacritics_go(self):
        for name in ('Koper AP', 'KOPER', 'Koper avtobusna postaja', 'Koper, AP'):
            self.assertEqual(stopgroups.normalize(name), 'koper', name)
        self.assertEqual(stopgroups.normalize('Postojna žel. post.'), 'postojna')
        self.assertEqual(stopgroups.normalize('Šentilj ŽP'), 'sentilj')

    def test_place_words_stay(self):
        self.assertEqual(stopgroups.normalize('Kozina pošta'), 'kozinaposta')
        self.assertEqual(stopgroups.normalize('Apače'), 'apace')


class MergeRadiusTests(SimpleTestCase):
    def test_city_and_intercity_stop_going_the_same_way_merge(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Koper', 45.53824, 13.73824), stop('MOKoper:1', 'Koper AP', 45.53864, 13.73767)],
                                     ways={'IJPP:1': [(1.0, 0.0)], 'MOKoper:1': [(0.9, 0.44)]})
        self.assertEqual(merged[0]['memberIds'], ['IJPP:1', 'MOKoper:1'])

    def test_namesakes_beyond_150_m_stay_apart(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Koper', 45.5380, 13.7380), stop('MOKoper:1', 'Koper', 45.5395, 13.7380)])  # ~166 m
        self.assertEqual(len(merged), 2)

    def test_namesakes_of_one_feed_stay_apart(self):
        # A village's stops on both sides of the road and a third at the junction: three stops.
        merged, _ = stopgroups.merge([
            stop('IJPP:1126449', 'Kozina', 45.6077743, 13.9345464), stop('IJPP:1126450', 'Kozina', 45.6077029, 13.9344103),
            stop('IJPP:1126451', 'Kozina', 45.6075275, 13.9344812), stop('IJPP:1126452', 'Kozina pošta', 45.6094029, 13.9388835)])
        self.assertEqual(len(merged), 4)

    def test_bus_stops_named_after_the_railway_station_join_it(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Celje ŽP', 46.2312, 15.2687), stop('IJPP:2', 'Celje ŽP', 46.2314, 15.2690),
                                      stop('IJPP:rail', 'Celje', 46.2318, 15.2694, modes=('rail',))])
        self.assertEqual(merged[0]['memberIds'], ['IJPP:rail', 'IJPP:1', 'IJPP:2'])


EAST, WEST, NORTH = [(1.0, 0.0)], [(-1.0, 0.0)], [(0.0, 1.0)]


class DirectionTests(SimpleTestCase):
    def test_city_and_intercity_stops_going_the_same_way_merge(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Primskovo', 46.2400, 14.3600), stop('MOKranj:1', 'Primskovo', 46.2402, 14.3601)],
                                     ways={'IJPP:1': EAST, 'MOKranj:1': EAST})
        self.assertEqual(merged[0]['memberIds'], ['IJPP:1', 'MOKranj:1'])

    def test_opposite_sides_of_the_road_stay_apart(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Primskovo', 46.2400, 14.3600), stop('MOKranj:1', 'Primskovo', 46.2402, 14.3601)],
                                     ways={'IJPP:1': EAST, 'MOKranj:1': WEST})
        self.assertEqual(len(merged), 2)

    def test_both_sides_do_not_chain_through_one_city_stop(self):
        stops = [stop('IJPP:1', 'Primskovo', 46.2400, 14.3600), stop('IJPP:2', 'Primskovo', 46.2403, 14.3600),
                 stop('MOKranj:1', 'Primskovo', 46.2401, 14.3600)]
        _, groups = stopgroups.merge(stops)  # no directions known: only the nearest pair at one spot
        self.assertEqual(groups['MOKranj:1'], ['IJPP:1', 'MOKranj:1'])
        self.assertNotIn('IJPP:2', groups)

    def test_far_apart_without_a_direction_stay_apart(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Primskovo', 46.2400, 14.3600), stop('MOKranj:1', 'Primskovo', 46.2404, 14.3600)])  # ~44 m
        self.assertEqual(len(merged), 2)

    def test_directions_from_patterns(self):
        ways = stopgroups.directions([['a', 'b', 'c']], {'a': (46.0, 14.0), 'b': (46.0, 14.001), 'c': (46.001, 14.001)})
        self.assertEqual(ways['a'], [(1.0, 0.0)])
        self.assertTrue(stopgroups.same_way(ways['b'], NORTH))
        self.assertFalse(stopgroups.same_way(EAST, WEST))
        self.assertIsNone(stopgroups.same_way(None, EAST))

    def test_forced_merge_and_pinned_marker(self):
        merged, _ = stopgroups.merge([stop('IJPP:1121103', 'Koper', 45.53824, 13.73824), stop('IJPP:1123012', 'Koper', 45.53897, 13.73853)],
                                     forced={'IJPP:1123012': 'IJPP:1121103'}, pinned={'IJPP:1121103': (45.538642, 13.737744)})
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]['latitude'], merged[0]['longitude']), (45.538642, 13.737744))

    def test_report_lists_each_member_with_its_distance(self):
        stops = [stop('IJPP:1', 'Koper', 45.53824, 13.73824), stop('MOKoper:1', 'Koper', 45.53864, 13.73767)]
        merged, _ = stopgroups.merge(stops, ways={'IJPP:1': [(1.0, 0.0)], 'MOKoper:1': [(1.0, 0.0)]})
        rows = stopgroups.report(stops, merged)
        self.assertEqual([r['stop_id'] for r in rows], ['IJPP:1', 'MOKoper:1'])
        self.assertTrue(all(0 <= r['meters'] < 75 for r in rows))

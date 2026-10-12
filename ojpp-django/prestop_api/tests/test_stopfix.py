import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from prestop_api import stopfix, stopgroups
from prestop_api.tests.test_kamgre import stop

CSV = '''# comment
stop_id,type,lat,lon,merge_into,label,note
IJPP:1121103,stop,45.538642,13.737744,,,OSM
IJPP:1121103,station,45.538642,13.737744,,,OSM
IJPP:1123012,stop,,,IJPP:1121103,,hub
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
        self.assertEqual(self.overrides['merge'], {'IJPP:1123012': 'IJPP:1121103'})
        self.assertEqual(self.overrides['replacement']['SZ:42'][0]['label'], 'Bus stop in front of the station')

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
    def test_city_and_intercity_stop_within_150_m_merge(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Koper', 45.53824, 13.73824), stop('MOKoper:1', 'Koper AP', 45.53864, 13.73767)])
        self.assertEqual(merged[0]['memberIds'], ['IJPP:1', 'MOKoper:1'])

    def test_namesakes_beyond_150_m_stay_apart(self):
        merged, _ = stopgroups.merge([stop('IJPP:1', 'Koper', 45.5380, 13.7380), stop('MOKoper:1', 'Koper', 45.5395, 13.7380)])  # ~166 m
        self.assertEqual(len(merged), 2)

    def test_three_bays_of_one_feed_become_one_station(self):
        merged, groups = stopgroups.merge([
            stop('IJPP:1126449', 'Kozina', 45.6077743, 13.9345464), stop('IJPP:1126450', 'Kozina', 45.6077029, 13.9344103),
            stop('IJPP:1126451', 'Kozina', 45.6075275, 13.9344812), stop('IJPP:1126452', 'Kozina pošta', 45.6094029, 13.9388835)])
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(groups['IJPP:1126451']), 3)

    def test_forced_merge_and_pinned_marker(self):
        merged, _ = stopgroups.merge([stop('IJPP:1121103', 'Koper', 45.53824, 13.73824), stop('IJPP:1123012', 'Koper', 45.53897, 13.73853)],
                                     forced={'IJPP:1123012': 'IJPP:1121103'}, pinned={'IJPP:1121103': (45.538642, 13.737744)})
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]['latitude'], merged[0]['longitude']), (45.538642, 13.737744))

    def test_report_lists_each_member_with_its_distance(self):
        stops = [stop('IJPP:1', 'Koper', 45.53824, 13.73824), stop('MOKoper:1', 'Koper', 45.53864, 13.73767)]
        merged, _ = stopgroups.merge(stops)
        rows = stopgroups.report(stops, merged)
        self.assertEqual([r['stop_id'] for r in rows], ['IJPP:1', 'MOKoper:1'])
        self.assertTrue(all(0 < r['meters'] < 75 for r in rows))

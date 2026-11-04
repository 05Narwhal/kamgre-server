"""Koper's correction (prestop_api/citytt/arriva_koper.py): Arriva's grid timetables read from the words of two real
pages (line 9's working days, page 1; line 2's working days, page 2, which prints line 2A's runs too), and the
correction keeping only line 9 and line 2's 10:55 / 11:55."""
import json
from pathlib import Path

from django.test import SimpleTestCase

from prestop_api.citytt import CITIES, arriva_koper, build

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'citytt'
WORDS = json.loads((FIXTURES / 'koper-9-and-2.words.json').read_text(encoding='utf-8'))
for page in WORDS.values():
    for w in page:
        w['bottom'] = w['top'] + 8


class ReaderTests(SimpleTestCase):
    def test_line_9_two_tables_one_direction(self):
        (t,) = arriva_koper.read([WORDS['line9']])
        self.assertEqual((t['line'], t['direction'], t['service']), ('9', 0, 'D'))
        self.assertEqual(t['stops'], ['Koper', 'Lesnina', 'Banka I', 'Tržnica', 'Zeleni park', 'Potniški terminal', 'Sv.Ana p.t.',
                                      'PH Sonce', 'Sv.Ana V.n.', 'Kosovelov trg', 'Banka', 'Stadion', 'Koper'])
        self.assertEqual(len(t['runs']), 29)
        self.assertEqual([r[0] for r in t['runs']][:3] + [t['runs'][-1][0]], ['06:20', '06:40', '07:00', '18:30'])
        self.assertEqual(t['runs'][0][7], '06:30')   # PH Sonce
        self.assertTrue(t['title'].startswith('Koper AP-Potniški terminal'))

    def test_line_2_with_2a_runs_codes_above_the_header(self):
        tables = {(t['line'], t['direction']): t for t in arriva_koper.read([WORDS['line2']])}
        self.assertEqual(set(tables), {('2', 0), ('2A', 0), ('2', 1), ('2A', 1)})
        out = tables[('2', 0)]
        self.assertEqual((out['stops'][0], out['stops'][-1], len(out['stops'])), ('Koper', 'Bolnišnica', 18))
        self.assertIn('10:55', [r[0] for r in out['runs']])
        a = tables[('2A', 0)]['runs'][0]
        self.assertIsNone(a[6])   # 2A skips Mandrač
        self.assertEqual(tables[('2', 1)]['stops'][0], 'Bolnišnica')

    def test_a_time_off_every_row_fails(self):
        words = [dict(w) for w in WORDS['line9']]
        moved = next(w for w in words if w['text'] == '18:30')
        moved['top'] += 6   # half a row down: on no stop's row
        with self.assertRaisesRegex(ValueError, 'on no stop'):
            arriva_koper.read([words])


class CorrectionTests(SimpleTestCase):
    def tables(self):
        return arriva_koper.read([WORDS['line9']]) + arriva_koper.read([WORDS['line2']])

    def test_keeps_line_9_and_line_2s_two_runs(self):
        out, problems = build.corrected(CITIES['MOKoper'], self.tables())
        self.assertEqual(problems, [])
        self.assertEqual(sorted((t['line'], t['direction'], len(t['runs'])) for t in out), [('2', 0, 2), ('9', 0, 29)])
        two = next(t for t in out if t['line'] == '2')
        self.assertEqual([r[0] for r in two['runs']], ['10:55', '11:55'])

    def test_a_listed_run_gone_is_a_problem(self):
        tables = [t if t['line'] != '2' or t['direction'] else {**t, 'runs': [r for r in t['runs'] if r[0] != '11:55']}
                  for t in self.tables()]
        _, problems = build.corrected(CITIES['MOKoper'], tables)
        self.assertEqual(problems, ['line 2 0: no run leaves at 11:55 any more'])

    def test_a_leg_with_no_plausible_road_takes_the_feeds_drawing(self):
        a = {'id': 'MOKoper:1', 'name': 'A', 'lon': 13.7268, 'lat': 45.5453}
        b = {'id': 'MOKoper:2', 'name': 'B', 'lon': 13.7288, 'lat': 45.5498}
        far = [[a['lon'], a['lat']], [a['lon'] + 0.05, a['lat'] + 0.05], [b['lon'], b['lat']]]
        quay = [[a['lon'], a['lat']], [13.7275, 45.5475], [b['lon'], b['lat']]]
        borrowed = []
        shape = build.road_shape([a, b], route=lambda window: [far], known={('MOKoper:1', 'MOKoper:2'): quay}, borrowed=borrowed)
        self.assertEqual((shape[0], shape[-1], borrowed), (quay[0], quay[-1], ['A → B']))
        with self.assertRaisesRegex(build.BuildError, 'no plausible road from A to B'):
            build.road_shape([a, b], route=lambda window: [far], known={})

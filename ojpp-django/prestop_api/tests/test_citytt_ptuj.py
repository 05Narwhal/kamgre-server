"""Ptuj's city buses (prestop_api/citytt/arriva_ocr.py): Arriva's picture-only timetables, read from the words
tesseract found on the real pages (fixtures/citytt/ptuj-*.words.json, saved from `ocr()` on the 1 Sep 2026 PDFs),
so no PNG or tesseract is needed here."""
import json
from pathlib import Path

from django.test import SimpleTestCase

from prestop_api.citytt import arriva_ocr

FIXTURES = Path(__file__).parent / 'fixtures' / 'citytt'


def page(name: str) -> dict:
    return json.loads((FIXTURES / f'{name}.words.json').read_text(encoding='utf-8'))


def firsts(table: dict) -> list[str]:
    return [next(v for v in run if v) for run in table['runs']]


class ReaderTests(SimpleTestCase):
    def test_line_1_two_grids_one_above_the_other_are_workdays_and_weekends(self):
        tables = arriva_ocr.read(page('ptuj-1'), '1')
        self.assertEqual([t['service'] for t in tables], ['D', 'SONP'])
        workdays, weekends = tables
        self.assertEqual(len(workdays['stops']), 21)
        self.assertEqual(firsts(workdays), ['06:10', '06:40', '07:10', '07:40', '08:10', '08:40', '09:30', '11:30', '12:00',
                                            '12:30', '13:30', '14:30', '15:00', '15:30', '16:30', '17:30', '19:30', '20:30'])
        self.assertEqual(workdays['runs'][-1][-1], '21:18')       # the last long loop, back at Ptuj AP
        self.assertEqual(sum(1 for v in workdays['runs'][0] if v), 13)   # a short loop ends at Ptuj AP, row 13
        self.assertEqual(firsts(weekends), ['07:00', '08:00', '08:30', '09:00', '09:30', '11:00', '11:30', '12:00',
                                            '12:30', '13:00', '14:00'])
        short = weekends['runs'][2]   # 08:30 goes straight to the hospital and TC Super Mesto: rows 2-13 are "–"
        self.assertEqual((short[0], short[1:13], short[13], short[-1]), ('08:30', [None] * 12, '08:32', '08:48'))
        self.assertEqual(workdays['title'], 'Ptuj')

    def test_line_4_two_times_read_as_one_word_land_in_their_own_columns(self):
        (table,) = arriva_ocr.read(page('ptuj-4'), '4')
        self.assertEqual(len(table['stops']), 57)
        self.assertEqual(len(table['runs']), 10)
        row = next(i for i, name in enumerate(table['stops']) if name.endswith('02*,04'))
        self.assertEqual([run[row] for run in table['runs']][2:5], ['09:17', '10:32', '12:47'])
        self.assertEqual(firsts(table), ['06:42', '07:40', '08:20', '09:40', '12:00', '13:05', '13:40', '14:02', '14:30', '15:05'])
        self.assertEqual(table['runs'][8][-1], '15:00')   # the 14:30 run ends at Ptuj AP 15:00 (OTP: 14:50)

    def test_the_title_gives_the_line_when_the_file_name_does_not(self):
        self.assertEqual(arriva_ocr.read(page('ptuj-4'))[0]['line'], '4')

    def test_a_time_going_backwards_fails_instead_of_guessing(self):
        broken = page('ptuj-4')
        for w in broken['words']:
            if w['text'] == '12:45':
                w['text'] = '11:45'
        with self.assertRaisesRegex(arriva_ocr.ReadError, 'Suha veja 02 12:44 then .* 11:45'):
            arriva_ocr.read(broken, '4')

    def test_a_missing_day_code_fails(self):
        broken = page('ptuj-1')
        broken['words'] = [w for w in broken['words'] if 'SO/NEP' not in w['text']]
        with self.assertRaisesRegex(arriva_ocr.ReadError, 'unknown day code'):
            arriva_ocr.read(broken, '1')


class SplitTests(SimpleTestCase):
    def test_joined_words_split_where_their_characters_sit(self):
        xs = [0, 100, 200, 300]
        parts = arriva_ocr._split([{'text': '10:32*|12:47*', 'x': 100, 'y': 5, 'w': 130},
                                   {'text': '|SO/NEP', 'x': 250, 'y': 5, 'w': 70},
                                   {'text': '|', 'x': 200, 'y': 5, 'w': 4},
                                   {'text': '09:15', 'x': 50, 'y': 5, 'w': 50}], xs)
        self.assertEqual([(p['text'], round(p['x'])) for p in parts],
                         [('10:32*', 65), ('12:47*', 135), ('SO/NEP', 255), ('09:15', 50)])

    def test_saved_words_without_a_width_take_one_column_per_part(self):
        (a, b) = arriva_ocr._split([{'text': '10:32|12:47', 'x': 200, 'y': 5}], [0, 100, 200, 300])
        self.assertLess(a['x'], 200)
        self.assertGreater(b['x'], 200)

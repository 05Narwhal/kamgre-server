"""Postojna's poster (prestop_api/citytt/nomago_postojna.py): the boxes of page 2 read from its real words (2026-11-04,
"Vozni red velja od 01. 10. 2026"), the Saturday runs from the legend's window, the school runs split where they wait."""
import json
from pathlib import Path

from django.test import SimpleTestCase

from prestop_api.citytt import nomago_postojna

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'citytt'
WORDS = json.loads((FIXTURES / 'postojna-poster.words.json').read_text(encoding='utf-8'))
for w in WORDS:
    w['bottom'] = w['top'] + 8


def starts(t):
    return [next(v for v in r if v) for r in t['runs']]


class ReaderTests(SimpleTestCase):
    def setUp(self):
        self.tables = {(t['line'], t['service']): t for t in nomago_postojna.read(WORDS)}

    def test_every_box(self):
        self.assertEqual(set(self.tables), {
            ('Proga 1', 'D'), ('Proga 1', 'SO'), ('Proga 2', 'D'), ('Proga 2', 'SO'), ('Šolska 1', 'Š'), ('Šolska 2', 'Š'),
            ('Šolska 3', 'Š'), ('Šolska 4', 'Š'), ('Šolska Popoldanska 1,2', 'Š'), ('Šolska Popoldanska 3', 'Š'), ('Delavska', 'D')})

    def test_main_grid_columns(self):
        one = self.tables[('Proga 1', 'D')]
        self.assertEqual((one['stops'][0], one['stops'][-1], len(one['stops'])), ('Industrijska cona', 'Kazarje - prihod', 23))
        self.assertEqual(len(one['runs']), 13)
        self.assertEqual(starts(one)[:5], ['08:13', '08:40', '09:10', '09:40', '10:38'])   # the first leaves Primorka
        self.assertEqual(one['runs'][4][2], '10:40')   # Industrijska cona 10:38 goes on from Kazarje
        self.assertEqual(len(self.tables[('Proga 2', 'D')]['runs']), 11)

    def test_saturdays_from_the_legend(self):
        self.assertEqual(nomago_postojna._saturdays(WORDS), {'1': ('08:13', '12:10'), '2': ('08:15', '13:14')})
        self.assertEqual(starts(self.tables[('Proga 1', 'SO')]), ['08:13', '08:40', '09:10', '09:40', '10:38', '11:10', '11:40'])
        self.assertEqual(starts(self.tables[('Proga 2', 'SO')]), ['08:15', '08:55', '09:35', '11:15', '11:55', '12:35'])

    def test_school_boxes(self):
        self.assertEqual(starts(self.tables[('Šolska 1', 'Š')]), ['07:02'])
        four = self.tables[('Šolska 4', 'Š')]
        self.assertEqual((four['stops'][0], starts(four)), ('Raubarkomanda', ['07:32']))
        afternoon = self.tables[('Šolska Popoldanska 1,2', 'Š')]
        self.assertEqual(starts(afternoon), ['13:27', '13:49'])
        self.assertEqual(afternoon['stops'][-1], 'Šolski center')
        self.assertIn('Raubarkomanda 1 Če je potnik: no time, left out', afternoon['notes'])
        three = self.tables[('Šolska Popoldanska 3', 'Š')]
        self.assertEqual(starts(three), ['12:35', '14:12'])   # everyone alights at Zagon at 13.20, it runs again at 14.12
        self.assertEqual(starts(self.tables[('Delavska', 'D')]), ['05:52'])

    def test_a_saturday_window_no_run_fits_fails(self):
        words = [dict(w, text='814') if w['text'] == '813' else w for w in WORDS]
        with self.assertRaisesRegex(ValueError, 'Proga 1: no runs fit Saturdays 08:14'):
            nomago_postojna.read(words)

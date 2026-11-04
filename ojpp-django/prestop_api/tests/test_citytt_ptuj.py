"""Ptuj's city buses (prestop_api/citytt/arriva_ocr.py): Arriva's picture-only timetables, read from the words
tesseract found on the real pages (fixtures/citytt/ptuj-*.words.json, saved from `ocr()` on the 1 Sep 2026 PDFs),
so no PNG or tesseract is needed here."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import citytt
from prestop_api.citytt import arriva_ocr, build, poles

PTUJ = citytt.CITIES['Ptuj']

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


class FeedTests(SimpleTestCase):
    """The Ptuj folder replaces OTP's Ptuj feed: its stop ids, its services per line and its OCR'd names."""

    def test_lines_2_to_5_have_no_summer_and_line_1_runs_all_year(self):
        rows, dates = build.calendar(PTUJ)
        off = {(d['service_id'], d['date']) for d in dates if d['exception_type'] == '2'}
        on = {(d['service_id'], d['date']) for d in dates if d['exception_type'] == '1'}
        self.assertIn(('DS', '20270701'), off)              # a Thursday in July: lines 2-5 do not run
        self.assertIn(('DS', '20270831'), off)
        self.assertNotIn(('DS', '20270630'), off)           # school year's last day
        self.assertNotIn(('D', '20270701'), off)            # line 1 does
        self.assertIn(('D', '20261225'), off)               # Christmas, a Friday: no workday buses ...
        self.assertIn(('SONP', '20261225'), on)             # ... the Sunday and holiday ones
        self.assertEqual({r['service_id'] for r in rows}, {'D', 'DS', 'SONP'})

    def test_a_line_s_day_code_names_the_city_s_service(self):
        self.assertIn(('4', 'D', 'DS'), PTUJ.line_services)
        self.assertNotIn('1', {line for line, _, _ in PTUJ.line_services})

    def test_stops_keep_otp_s_ids_and_a_stop_printed_twice_is_one_call(self):
        # Line 4: Ptuj AP 08:46, then Ptuj AP 09:00 on the next row: the bus waits there.
        pole = lambda n, name: {'id': f'Ptuj:{n}', 'name': name, 'lat': 46.42, 'lon': 15.87 + n / 1000}  # noqa: E731
        all_poles = {p['id']: p for p in (pole(1, 'Ptuj AP'), pole(2, 'Zadružni trg parkirišče'), pole(3, 'Ptuj Breg'))}
        t = {'line': '4', 'title': 'Breg - Turnisce', 'direction': 0, 'service': 'DS',
             'stops': ['Zadružni trg parkirišče', 'Ptuj AP', 'Ptuj AP', 'Ptuj Breg'], 'runs': [['08:43', '08:46', '09:00', '09:05']]}
        rows, problems = build.compose(PTUJ, [t], lambda table: ['Ptuj:2', 'Ptuj:1', 'Ptuj:1', 'Ptuj:3'],
                                       lambda pts: [[p['lon'], p['lat']] for p in pts], all_poles)
        self.assertEqual(problems, [])
        calls = [(r['stop_id'], r['arrival_time'], r['departure_time']) for r in rows['stop_times.txt']]
        self.assertEqual(calls, [('2', '08:43:00', '08:43:00'), ('1', '08:46:00', '09:00:00'), ('3', '09:05:00', '09:05:00')])
        self.assertEqual(sorted(s['stop_id'] for s in rows['stops.txt']), ['1', '2', '3'])

    def test_feed_poles_are_the_feed_s_own_stops(self):
        stop = lambda sid, name: {'id': sid, 'name': name, 'latitude': 46.42, 'longitude': 15.87, 'modes': ['bus']}  # noqa: E731
        fake = SimpleNamespace(
            stops=SimpleNamespace(get=lambda: SimpleNamespace(value={'all': [stop('Ptuj:1129013', 'Ptuj AP'), stop('IJPP:5', 'Ptuj AP'),
                                                                              stop('Ptuj:osm9', 'Terme Ptuj')]})),
            patterns=SimpleNamespace(get=lambda: SimpleNamespace(value={'patterns': []})))
        with mock.patch('prestop_api.sources', fake, create=True):
            stops, _ = build.feed_poles(PTUJ)
        self.assertEqual([s['id'] for s in stops], ['Ptuj:1129013'])  # not IJPP's, and an own OSM pole comes from OSM again


class NameTests(SimpleTestCase):
    def test_a_misread_name_takes_the_pole_name_it_clearly_is(self):
        named = lambda *names: {f'p{i}': {'names': [n]} for i, n in enumerate(names)}  # noqa: E731
        found = named('Zadružni trg parkirišče', 'Pod gradom parkirišče', 'Suha veja', 'Draženci 18e', 'Trg')
        self.assertEqual(poles.misread('ZadruiZni trg parkiriSée', found), 'Zadružni trg parkirišče')
        self.assertEqual(poles.misread('Suha veja 02', found), 'Suha veja')     # a pole named without the number
        self.assertIsNone(poles.misread('Draženci 21d', found))                  # never another house number
        self.assertIsNone(poles.misread('Knjiznica', found))
        # two spellings of one place are not a tie
        self.assertEqual(poles.misread('Pod gradom parkiriSée', {**found, 'q': {'names': ['Pod gradom - parkirišče']}})[:10], 'Pod gradom')

    def test_the_town_s_station_is_not_alike_a_stop_ending_in_the_town(self):
        self.assertFalse(poles.alike('Dom upokojencev Ptuj', 'Ptuj AP', 'Ptuj'))
        self.assertFalse(poles.alike('Ptuj AP', 'Terme Ptuj', 'Ptuj'))
        self.assertTrue(poles.alike('Ptuj AP', 'Ptuj AP', 'Ptuj'))
        self.assertTrue(poles.alike('Ptuj bol.', 'Ptuj Bolnišnica', 'Ptuj'))

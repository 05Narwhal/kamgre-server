"""SŽ replacement-timetable PDFs (prestop_api/szpdf): every fixture parses to its verified golden file.

The fixtures are the PDFs SŽ's notices linked on 2026-10-14 (tests/fixtures/szpdf/<first ID_ovire>.pdf). Each
golden <id>.expected.json was checked column by column against the page rendered at 200–400 dpi (cropped and zoomed
where dense); VERIFIED below lists, per golden, the column labels of every direction table that were checked.
Regenerate a golden only after checking the changed columns against the rendered page again:

    ojpp.sh manage szpdf_sync --fixtures prestop_api/tests/fixtures/szpdf --write-goldens
"""
import json
import shutil
from datetime import date
from functools import lru_cache
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import szpdf
from prestop_api.szpdf import texts

FIXTURES = Path(__file__).parent / 'fixtures' / 'szpdf'
IDS = sorted(p.stem for p in FIXTURES.glob('*.pdf'))
TESSERACT_MISSING = ('tesseract is not installed, so the pasted timetable image in 11056 cannot be read. Install it: '
                     'sudo apt-get install -y tesseract-ocr (WSL kali-linux and the server; update.sh does it there).')


@lru_cache(maxsize=None)
def parsed(pid: str) -> dict:
    return szpdf.parse(FIXTURES / f'{pid}.pdf')


def table(doc: dict, direction: str) -> dict:
    found = [t for t in doc['tables'] if t['direction'] == direction]
    assert len(found) == 1, (direction, [t['direction'] for t in doc['tables']])
    return found[0]


def column(t: dict, label: str, vehicle: str = 'BUS') -> dict:
    found = [c for c in t['columns'] if c['label'] == label and c['vehicle'] == vehicle]
    assert len(found) == 1, (label, [c['label'] for c in t['columns']])
    return found[0]


class LesceJeseniceTests(SimpleTestCase):
    """11248: Lesce Bled – Jesenice / Beljak, 12–18 Oct, with trains split into several buses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = parsed('11248')
        cls.south = table(cls.doc, 'LJUBLJANA / LESCE BLED - JESENICE - BELJAK / VILLACH (A)')

    def test_validity_footnotes_and_status(self):
        self.assertEqual(self.doc['status'], 'ok', self.doc['problems'])
        self.assertEqual(self.doc['valid'], {'from': '2026-10-12', 'to': '2026-10-18', 'dates': None})
        self.assertEqual({k: v['rule'] for k, v in self.doc['footnotes'].items()},
                         {'2': 'workdays', '3': 'weekends_holidays', '6': 'not_saturday'})
        self.assertEqual(self.doc['footnotes']['2']['text'], 'Ne vozi ob sobotah, nedeljah in praznikih.')

    def test_stations_in_travel_order(self):
        self.assertEqual(self.south['stations'], ['LJUBLJANA', 'Litostroj', 'KRANJ', 'LESCE BLED', 'Žirovnica',
                                                  'Slovenski Javornik', 'JESENICE', 'BELJAK'])
        self.assertEqual(self.south['source'], 'text')

    def test_2400_is_a_bus_from_lesce_bled_only(self):
        col = column(self.south, '2400')
        self.assertEqual((col['train'], col['part'], col['vehicle'], col['additional'], col['footnotes']),
                         ('2400', None, 'BUS', False, ['2']))
        self.assertEqual(col['calls'], [
            {'station': 'LESCE BLED', 'dep': '05:40'},
            {'station': 'Žirovnica', 'arr': '05:47', 'dep': '05:47'},
            {'station': 'Slovenski Javornik', 'arr': '05:52', 'dep': '05:52'},
            {'station': 'JESENICE', 'arr': '05:57'},
        ])
        self.assertEqual(col['problems'], [])

    def test_318_is_three_buses(self):
        self.assertEqual(column(self.south, '318/1')['calls'], [
            {'station': 'LJUBLJANA', 'dep': '07:42'},
            {'station': 'Litostroj', 'arr': '07:51', 'dep': '07:51'},
            {'station': 'JESENICE', 'arr': '08:32', 'dep': '08:35'},
            {'station': 'BELJAK', 'arr': '09:25'},
        ])
        self.assertEqual(column(self.south, '318/2')['calls'], [
            {'station': 'LJUBLJANA', 'dep': '07:42'},
            {'station': 'Litostroj', 'arr': '07:51', 'dep': '07:51'},
            {'station': 'KRANJ', 'arr': '08:22', 'dep': '08:22'},
            {'station': 'LESCE BLED', 'arr': '08:47'},
        ])
        third = column(self.south, '318/3')
        self.assertEqual((third['train'], third['part']), ('318', 3))
        self.assertEqual(third['calls'], [
            {'station': 'KRANJ', 'dep': '07:47'},
            {'station': 'LESCE BLED', 'arr': '08:12', 'dep': '08:12'},
            {'station': 'JESENICE', 'arr': '08:32'},
        ])

    def test_414_runs_past_midnight(self):
        self.assertEqual(column(self.south, '414')['calls'], [
            {'station': 'LJUBLJANA', 'dep': '22:10'},
            {'station': 'KRANJ', 'arr': '22:50', 'dep': '22:50'},
            {'station': 'LESCE BLED', 'arr': '23:15', 'dep': '23:15'},
            {'station': 'JESENICE', 'arr': '23:35', 'dep': '23:38'},
            {'station': 'BELJAK', 'arr': '24:28'},
        ])

    def test_return_direction_and_stops(self):
        north = table(self.doc, 'BELJAK / VILLACH (A) - JESENICE - LESCE BLED / LJUBLJANA')
        self.assertEqual(north['stations'][:3], ['BELJAK', 'JESENICE', 'Slovenski Javornik'])
        self.assertEqual(column(north, '2401')['calls'][0], {'station': 'JESENICE', 'dep': '04:24'})
        self.assertIn({'station': 'LJUBLJANA', 'text': 'Nova Avtobusna postaja LJUBLJANA (peroni 37, 38 in 39)'},
                      self.doc['stops'])
        self.assertIn({'station': 'BELJAK', 'text': 'zunanja stran ŽP'}, self.doc['stops'])


class VintgarImageTests(SimpleTestCase):
    """11056: the return half of the table is a screenshot pasted over stale text; bus 4292 is only in the image."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = parsed('11056')

    def test_tesseract_is_installed(self):
        self.assertTrue(shutil.which('tesseract'), TESSERACT_MISSING)

    def test_4292_comes_from_the_image(self):
        self.assertTrue(shutil.which('tesseract'), TESSERACT_MISSING)
        back = table(self.doc, 'VINTGAR - JESENICE')
        self.assertEqual(back['source'], 'mixed')
        col = column(back, '4292')
        self.assertEqual(col['footnotes'], ['3'])
        self.assertEqual(col['calls'], [
            {'station': 'VINTGAR', 'dep': '09:23'},
            {'station': 'Kočna', 'arr': '09:25', 'dep': '09:25'},
            {'station': 'JESENICE', 'arr': '09:31'},
        ])
        self.assertEqual(column(back, '4208')['footnotes'], ['2'])
        self.assertEqual([c['label'] for c in back['columns']],
                         ['4200', '600', '4208', '4292', '4210', '4212', '4214', '4291', '4220'])
        self.assertEqual(self.doc['status'], 'ok', self.doc['problems'])

    def test_without_tesseract_the_stale_columns_are_unusable(self):
        with mock.patch('prestop_api.szpdf.ocr.shutil.which', return_value=None):
            doc = szpdf.parse(FIXTURES / '11056.pdf')
        self.assertEqual(doc['status'], 'unsure')
        back = table(doc, 'VINTGAR - JESENICE')
        self.assertEqual(back['source'], 'text')
        self.assertTrue(all('under a pasted image that was not read' in c['problems'] for c in back['columns']))
        self.assertTrue(all(not c['problems'] for c in table(doc, 'JESENICE - VINTGAR')['columns']))

    def test_the_text_half_is_text(self):
        there = table(self.doc, 'JESENICE - VINTGAR')
        self.assertEqual(there['source'], 'text')
        self.assertEqual(column(there, '4295')['footnotes'], ['3'])


class LjubljanaJeseniceTests(SimpleTestCase):
    """11198: Ljubljana – Kranj / Jesenice / Beljak, 19–23 Oct, 76 columns, footnote 98 and red extra buses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = parsed('11198')
        cls.south = table(cls.doc, 'LJUBLJANA - JESENICE - BELJAK / VILLACH')
        cls.north = table(cls.doc, 'BELJAK / VILLACH - JESENICE - LJUBLJANA')

    def test_footnote_98_names_the_day_the_train_runs(self):
        self.assertEqual(self.doc['footnotes']['98'], {
            'text': 'dne 19. 10. se nadomestni prevoz NE opravlja; VOZI VLAK!',
            'rule': 'train_runs_on', 'dates': ['2026-10-19']})
        self.assertEqual(column(self.south, '2400')['footnotes'], ['98', '2'])

    def test_podnart_bus_leaves_five_minutes_earlier(self):
        podnart = [n for n in self.doc['stationNotes'] if n['station'] == 'PODNART']
        self.assertEqual(len(podnart), 1)
        self.assertEqual(podnart[0]['minutesEarlier'], 5)
        self.assertTrue(podnart[0]['text'].startswith('Za postajo PODNART je organiziran prevoz'))

    def test_red_columns_are_additional_buses(self):
        red = [c for c in self.south['columns'] if c['additional']]
        self.assertEqual([c['label'] for c in red], ['2402', '314', '2412', '2414', '2416'])
        self.assertEqual(red[0]['calls'][0], {'station': 'Škofja Loka', 'dep': '06:31'})
        self.assertFalse(column(self.south, '38/1')['additional'])

    def test_bus_star_runs_on_workdays_only(self):
        star = [c for c in self.north['columns'] if c['mark'] == '*']
        self.assertEqual([(c['label'], c['additional']) for c in star], [('2403', True)])
        self.assertEqual(star[0]['footnotes'], ['98', '*'])
        self.assertEqual(self.doc['footnotes']['*']['rule'], 'workdays')

    def test_76_columns(self):
        self.assertEqual((len(self.south['columns']), len(self.north['columns'])), (38, 38))
        self.assertEqual(column(self.south, '2430')['calls'][-1], {'station': 'JESENICE', 'arr': '24:09'})


class LayoutTests(SimpleTestCase):
    def test_two_directions_side_by_side_and_a_row_under_an_arrowhead(self):
        doc = parsed('11125')
        there, back = doc['tables']
        self.assertEqual((there['direction'], back['direction']), ('ORMOŽ - SREDIŠČE', 'SREDIŠČE - ORMOŽ'))
        self.assertEqual(back['stations'], ['SREDIŠČE', 'Obrež', 'Frankovci', 'ORMOŽ'])
        self.assertEqual(column(there, '7802')['calls'][-1], {'station': 'SREDIŠČE', 'arr': '08:46'})
        self.assertEqual(column(back, '7803')['calls'], [
            {'station': 'SREDIŠČE', 'dep': '09:49'},
            {'station': 'Obrež', 'arr': '09:59', 'dep': '09:59'},
            {'station': 'Frankovci', 'arr': '10:11', 'dep': '10:11'},
            {'station': 'ORMOŽ', 'arr': '10:24'},
        ])

    def test_a_list_of_days(self):
        doc = parsed('11144')
        self.assertEqual(doc['valid'], {'from': '2026-10-10', 'to': '2026-10-25',
                                        'dates': ['2026-10-10', '2026-10-11', '2026-10-17', '2026-10-24', '2026-10-25']})
        self.assertEqual(doc['footnotes']['7']['rule'], 'sundays')
        # The stop list continues on page 2.
        self.assertIn({'station': 'NOTRANJE GORICE', 'text': 'AP Notranje Gorice Šola (nad ŽP)'}, doc['stops'])

    def test_characters_in_another_font_keep_their_place(self):
        # Edited cells mix fonts whose glyphs sit a point lower: 11:03 and 26609, not 1:310 and 02669.
        self.assertEqual(column(table(parsed('11120'), 'DIVAČA - KOPER'), '503')['calls'][0],
                         {'station': 'DIVAČA', 'dep': '11:03'})
        ljubljana = table(parsed('10088'), 'LJUBLJANA - LOGATEC')
        self.assertIn('26609', [c['label'] for c in ljubljana['columns']])

    def test_a_doubled_colon_is_still_a_time(self):
        col = column(table(parsed('10088'), 'LOGATEC - LJUBLJANA'), '26639')
        self.assertIn({'station': 'Ljubljana Tivoli', 'arr': '17:00', 'dep': '17:00'}, col['calls'])

    def test_a_minivan_and_a_bus_for_the_same_train(self):
        there = table(parsed('11194'), 'VIŠNJA GORA - GROSUPLJE')
        self.assertEqual(column(there, '3232', '8+1')['calls'][1], {'station': 'Žalna', 'arr': '08:14', 'dep': '08:14'})
        self.assertEqual(len(column(there, '3232', 'BUS')['calls']), 2)

    def test_a_stop_name_printed_at_the_end_of_the_line_before(self):
        # 11188 prints "LITOSTROJ– na AP … obračališče) LJUBLJANA STEGNE" and "– na AP mestnega prometa Tehnounion".
        self.assertEqual(parsed('11188')['stops'][1:3], [
            {'station': 'LITOSTROJ', 'text': 'na AP mestnega prometa Litostrojska(ob Litostrojski - NE obračališče)'},
            {'station': 'LJUBLJANA STEGNE', 'text': 'na AP mestnega prometa Tehnounion'},
        ])

    def test_connecting_buses_are_additional(self):
        doc = parsed('11058')
        self.assertTrue(all(c['additional'] for t in doc['tables'] for c in t['columns']))
        late = column(table(doc, 'LESCE BLED - BLED JEZERO'), '*2424/**2494 / 4219')
        self.assertEqual((late['train'], late['footnotes']), ('2424', []))


class TextTests(SimpleTestCase):
    def test_validity(self):
        cases = {
            'Od 12. 10. do  18. 10. 2026': ('2026-10-12', '2026-10-18', None),
            'Od 14. 12. 2025 do 12. 12. 2026': ('2025-12-14', '2026-12-12', None),
            'Od 26. do 30. 10. 2026': ('2026-10-26', '2026-10-30', None),
            '14. 10. 2026': ('2026-10-14', '2026-10-14', ['2026-10-14']),
            '17. in 18. 10. ter 24. in 25.10. 2026': ('2026-10-17', '2026-10-25',
                                                      ['2026-10-17', '2026-10-18', '2026-10-24', '2026-10-25']),
            '22. 10. in 23. 10. 2026': ('2026-10-22', '2026-10-23', ['2026-10-22', '2026-10-23']),
        }
        for text, (start, end, dates) in cases.items():
            self.assertEqual(texts.validity(text), {'from': start, 'to': end, 'dates': dates}, text)
        self.assertIsNone(texts.validity('vsak dan'))
        self.assertIsNone(texts.validity('Od 31. 2. do 3. 3. 2026'))

    def test_footnote_rules(self):
        year = date(2026, 10, 12)
        cases = {
            'Ne vozi ob sobotah, nedeljah in praznikih.': ('workdays', None),
            'ne vozi ob sobotah, nedeljah in praznikih - dela prostih dneh v RS': ('workdays', None),
            'Vozi le ob delovnikih': ('workdays', None),
            'Vozi ob sobotah, nedeljah in praznikih': ('weekends_holidays', None),
            'Ne vozi ob sobotah': ('not_saturday', None),
            'Vozi ob nedeljah': ('sundays', None),
            'dne 19. 10. se nadomestni prevoz NE opravlja; VOZI VLAK!': ('train_runs_on', ['2026-10-19']),
            'Prevoz se opravi preko preko mejnega prehoda Sočerga': ('info', None),
            'Vozi ob praznikih in ob polni luni': (None, None),
        }
        for text, (rule, dates) in cases.items():
            self.assertEqual(texts.footnote_rule(text, year), (rule, dates), text)


# Every column of every golden, as checked against the rendered page on 2026-10-14 (395 columns; 200–300 dpi crops,
# 400 dpi for the pasted image in 11056 and 600 dpi where a label looked overprinted).
VERIFIED = {
    '9457': ["77074", "77064"],
    '9459': ["44201 44202 44203 27501 27521 27523", "27511 27911 44211 44212 44213 27533 27532 27531"],
    '9463': ["51206 60606 14006 36006 61206 52606", "31006 17006 61706 52306"],
    '10088': ["26729 26728 26369 26368 26769 26768 26509 26508 26609 26608 18969 18968 26589 26588", "26019 26018 26219 26218 26199 26198 27519 27518 26639 26638 26159 26158 26799 26798"],
    '11056': ["4295 4201 4203 4290 4211 4205 4213 601 4219", "4200 600 4208 4292 4210 4212 4214 4291 4220"],
    '11058': ["4290 318/4211 316/4205 2408/4213 312/601 *2424/**2494 / 4219", "4200/2403 600 / *2409/**2499 4214/2423"],
    '11120': ["503", "502"],
    '11125': ["7802 3840", "7803 3841"],
    '11144': ["2674 481 503 2606 2678 2752 210 2680 509", "2633 508 2671 1825 2791 211 2675 502 1475 2697"],
    '11157': ["4209 4225", "4254 4210"],
    '11159': ["3237 3205 3235 3209", "3210 3220 3212 3234"],
    '11161': ["640", "2501 2519"],
    '11165': ["640", "2501 2519"],
    '11186': ["1824 1804 1896", "1825 1897 1803"],
    '11188': ["4290 316 2408 314 2414 2416 312 310 2494 18", "2403 2499 313 2497 2419 2423"],
    '11194': ["3232 3232 3210 3210 3220 3220 3212 3212 3296 3296 3234 3234", "3235 3235 3209 3209 3211 3211 3297 3297 3213 3213 3215 3215"],
    '11198': ["2400 38/1 38/2 38/3 2402 2402 4290 318/1 318/2 318/3 2404 2442 316 2444 214/1 214/2 214/3 2448 2408 314 314 2412 2412 2414 2414 2416 2416 312 2418 2420 310 2494 2424 2426 18 2428 414 2430", "2401 2441 2403 2403 2443 2405 2405 2407 415 2499 2409 2453 311/1 311/2 311/3 2411 2449 313 2415 315/1 315/2 315/3 2417 2497 115/1 115/2 115/3 2419 2421 317/1 317/2 317/3 2423 319 4291 2427 19 39"],
    '11203': ["4505 3235 3209 3211 3297 3213 3215", "4504 3206 3232 3210 3220 3212 3296"],
    '11205': ["3528 3506", "3529 3505 3507"],
    '11218': ["3148 3146 3156 3152 3150", "3161 3145 3149 3151 3153 3155"],
    '11222': ["4290 316 2408 314 2414 2416 312 310 2494 18", "2403 2499 313 2497 2419 2423"],
    '11226': ["4505 4505 4507 4507 4509 4509 4525 4525 4527 4527", "4506 4506 4508 4508 4510 4510 4512 4512 4514 4514 4516 4516"],
    '11230': ["4201 4203 4213 601 4219", "4200 600 4296 4214 4220", "4211 4211 4205 4205", "4208 4208 4210 4210"],
    '11248': ["2400 38/1 38/2 38/3 2402 4290 318/1 318/2 318/3 2404 316 214/1 214/2 214/3 2408 314 2412 2414 2416 312 2418 2420 310 2494 2424 2426 18 2428 414 2430", "2401 2441 2403 2405 2407 415 2499 2409 311/1 311/2 311/3 2411 313 2415 315/1 315/2 315/3 2417 2497 115/1 115/2 115/3 2419 2421 317/1 317/2 317/3 2423 319 4291 2427 19 39"],
}


class GoldenTests(SimpleTestCase):
    def test_every_fixture_matches_its_verified_golden(self):
        self.assertEqual(len(IDS), 24)
        self.assertEqual(sorted(VERIFIED), IDS, 'every golden lists the columns checked against the rendered page')
        for pid in IDS:
            with self.subTest(pid=pid):
                golden = json.loads((FIXTURES / f'{pid}.expected.json').read_text(encoding='utf-8'))
                doc = parsed(pid)
                self.assertEqual(doc['status'], 'ok', doc['problems'])
                self.assertEqual(doc, golden)
                labels = [' '.join(c['label'] for c in t['columns']) for t in golden['tables']]
                self.assertEqual(labels, VERIFIED[pid], 'columns checked against the rendered page')

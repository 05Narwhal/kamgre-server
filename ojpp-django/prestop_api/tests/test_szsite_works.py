"""SŽ's works from our reader (prestop_api/szsite/works.py): the status page's `roadworks` items as lineWorks, and
zamudil.line_works taking them ahead of zamudil.si's maintenance while the copy is fresh. Offline."""
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import zamudil
from prestop_api.szsite import parse, works
from prestop_api.szsite.store import Store

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'szsite'


def items() -> list:
    return parse.works((FIXTURES / 'stanje.html').read_text(encoding='utf-8'))


def anywhere(name, near):
    return [near[0] + len(name) / 1000, near[1]]


def along(chord):
    a, b = chord
    return [a, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.001], b]


class ConvertTests(SimpleTestCase):
    def test_only_works_one_line_per_station_pair(self):
        found = works.convert(items(), anywhere, along)
        # 17 "Dela na progi" entries in the saved page, 14 of them works ("DELA NA PROGI: …"); the bus link
        # Lesce Bled - Bled Jezero ("DODATNO"), "OBVESTILO: Vlak vozi samo do/s postaje Ljubljana Šiška" and the car
        # train's loading times ("OPOZORILO") are notices filed under that kind
        self.assertEqual(len(found), 14)
        self.assertTrue(all(w['title'].startswith('DELA NA PROGI') for w in found))
        zalog = [w for w in found if w['relation'] == 'Ljubljana - Ljubljana Zalog']
        self.assertEqual([(w['validFrom'], w['validTo']) for w in zalog], [('2026-11-10', '2026-11-13')])  # the entry, not the bus's 15 Nov
        self.assertFalse(any(w['relation'].startswith(('Jesenice /', 'Bled Jezero', 'Nova Gorica')) for w in found))
        for w in found:
            self.assertGreater(len(w['geometry']), 2)
            self.assertTrue(w['sourceUrl'].startswith('https://'))
            self.assertNotIn('<', w['message'])

    def test_a_relation_off_the_track_or_unknown_is_left_out(self):
        self.assertEqual(works.convert(items(), anywhere, lambda chord: chord), [])  # not followed: no straight line
        self.assertEqual(works.convert(items(), lambda name, near: None, along), [])

    def test_a_relation_of_several_lines_numbers_them(self):
        item = dict(WORK, Relacija=['Kranj / Kamnik - Ljubljana'])
        self.assertEqual([w['id'] for w in works.convert([item], anywhere, along)], ['sz-9001-1', 'sz-9001-2'])

    def test_a_name_with_no_station_is_the_station_at_the_items_point(self):
        stops = {'all': STOPS['all'] + [{'id': 'IJPP:3', 'name': 'Kresnice', 'modes': ['rail'], 'latitude': 46.1033, 'longitude': 14.7914}]}
        station = works._station_finder(stops)
        self.assertEqual(station('Kresnica', [14.7913, 46.1032]), [14.7914, 46.1033])
        self.assertIsNone(station('Kresnica', [14.70, 46.20]))  # nothing within NEAR_STATION
        self.assertEqual(station('Ljubljana', [14.7913, 46.1032]), [14.510, 46.058])  # a known name is never swapped

    def test_relation_pairs(self):
        self.assertEqual(works.pairs('Šentjur-Celje'), [('Šentjur', 'Celje')])
        self.assertEqual(works.pairs('Lesce-Bled - Bled Jezero'), [('Lesce-Bled', 'Bled Jezero')])
        self.assertEqual(works.pairs('Kranj / Kamnik - Ljubljana'), [('Kranj', 'Ljubljana'), ('Kamnik', 'Ljubljana')])
        self.assertEqual(works.pairs('Ljubljana'), [])


WORK = {'ID_ovire': ['9001'], 'Vrsta': ['Dela na progi'], 'Naslov': ['DELA NA PROGI: Ljubljana - Borovnica'],
        'Cas': ['01.11.2026-30.11.2026'], 'Relacija': ['Ljubljana - Borovnica'], 'Opis': ['<p>Zapora tira.</p>'],
        'Koordinate': ['14.40', '45.98'], 'Lokacija': '44002'}
STOPS = {'all': [{'id': 'IJPP:1', 'name': 'Ljubljana', 'modes': ['rail'], 'latitude': 46.058, 'longitude': 14.510},
                 {'id': 'IJPP:2', 'name': 'Borovnica', 'modes': ['rail'], 'latitude': 45.918, 'longitude': 14.364}]}


class LeadTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        works._memo.update(stamp=None, value=None)
        self.stops = mock.patch('prestop_api.sources.stops', SimpleNamespace(get=lambda: SimpleNamespace(value=STOPS)))
        self.track = mock.patch('prestop_api.railtrack.along', along)
        self.stops.start(), self.track.start()
        self.addCleanup(self.stops.stop), self.addCleanup(self.track.stop)

    def test_the_readers_works_lead_while_fresh(self):
        Store(self.dir).keep('works', [WORK])
        with override_settings(PRESTOP_SZSITE_WORKS=True, PRESTOP_SZSITE_DIR=self.dir):
            found = zamudil.line_works()
            self.assertEqual(zamudil.works_source(), 'sz:site-works')
        self.assertEqual([w['id'] for w in found], ['sz-9001'])
        self.assertEqual(found[0]['geometry'][0], [14.51, 46.058])
        self.assertEqual(found[0]['geometry'][-1], [14.364, 45.918])
        self.assertEqual(found[0]['message'], 'Zapora tira.')
        self.assertEqual(found[0]['sourceUrl'], works.SOURCE)

    def test_stale_copy_or_switch_off_falls_back_to_zamudil(self):
        Store(self.dir).keep('works', [WORK], now=time.time() - works.FRESH - 1)
        for on in (True, False):
            with override_settings(PRESTOP_SZSITE_WORKS=on, PRESTOP_SZSITE_DIR=self.dir), \
                    mock.patch.object(zamudil, 'enabled', return_value=False):
                self.assertIsNone(works.line_works())
                self.assertEqual(zamudil.line_works(), [])
                self.assertEqual(zamudil.works_source(), 'sz:zamudil-works')

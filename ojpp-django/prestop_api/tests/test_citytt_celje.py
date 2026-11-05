"""Celje's Word timetables (prestop_api/citytt/nomago_celje.py): three real files of the 2026-09 set (Nomago, "Čas
veljavnosti 01.09.2026 - 30.06.2029") covering every layout quirk, and the errors made by editing their XML in memory.

    celje-10  I and --- cells, a stop with arrival and departure rows, a Saturday column
    celje-3   DŠ, several tables, rows that fell out of the table as paragraphs, a header without its own table
    celje-1a  cells holding two runs' times, the 'Smer' line split over cells
    celje-4   the whole head of the file inside the table, run cells two columns wide
"""
import io
import re
import zipfile
from pathlib import Path

from django.test import SimpleTestCase

from prestop_api.citytt import nomago_celje

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'citytt'


def tables(name):
    return {t['service']: t for t in nomago_celje.parse(FIXTURES / f'celje-{name}.docx')}


def starts(t):
    return [next(v for v in r if v) for r in t['runs']]


def ends(t):
    return [[v for v in r if v][-1] for r in t['runs']]


def document_xml(name):
    return zipfile.ZipFile(FIXTURES / f'celje-{name}.docx').read('word/document.xml').decode('utf-8')


def read(xml):
    return nomago_celje.read(xml.encode('utf-8'), 'edited.docx')


def replace_once(xml, old, new, last=False):
    i = xml.rindex(old) if last else xml.index(old)
    return xml[:i] + new + xml[i + len(old):]


class TenTests(SimpleTestCase):
    def setUp(self):
        self.tables = tables('10')
        self.d = self.tables['D']

    def test_tables_and_runs(self):
        self.assertEqual(set(self.tables), {'D', 'SO'})
        for t in self.tables.values():
            self.assertEqual((t['line'], t['title'], t['direction']), ('10', 'Bukovžlak-Ljubečna', 0))
            self.assertEqual((t['stops'][0], t['stops'][-1]), ('Celje ŽP', 'Celje ŽP'))
            self.assertEqual(t['notes'], ['Čas veljavnosti voznega reda:01.09.2026 - 30.06.2029'])
            self.assertEqual((t['valid_from'], t['valid_to']), ('2026-09-01', '2029-06-30'))
            self.assertTrue(all(len(r) == len(t['stops']) for r in t['runs']))
            # The file's 35 stops less the 7 every run passes (I) or skips (-): no stop is on no run's way.
            self.assertTrue(all(any(r[i] for r in t['runs']) for i in range(len(t['stops']))))
        self.assertEqual(len(self.d['stops']), 28)
        self.assertEqual(starts(self.d), ['05:30', '07:30', '11:30', '13:30', '15:30', '17:30'])
        self.assertEqual(ends(self.d), ['06:15', '08:15', '12:15', '14:15', '16:15', '18:15'])
        self.assertEqual((starts(self.tables['SO']), ends(self.tables['SO'])), (['13:30'], ['14:15']))

    def test_calls(self):
        run = self.d['runs'][0]
        self.assertEqual(run[:3], ['05:30', '05:32', '05:34'])
        # Out, Trnovlje pri Celju Gaji is passed (I) and Začret skipped (-) by every run: only the way back has them.
        self.assertEqual(self.d['stops'][8:10], ['Trnovlje Etra', 'Začret K'])
        self.assertEqual((run[8], run[9]), ('05:44', '05:46'))
        self.assertEqual(self.d['stops'].count('Trnovlje pri Celju Gaji'), 1)
        self.assertEqual(run[self.d['stops'].index('Trnovlje pri Celju Gaji')], '06:01')

    def test_arrival_and_departure_rows_are_one_call_with_the_later_time(self):
        i = self.d['stops'].index('Ljubečna OŠ')
        self.assertEqual([r[i] for r in self.d['runs']], ['05:55', '07:55', '11:55', '13:55', '15:55', '17:55'])
        for t in self.tables.values():
            for r in t['runs']:
                self.assertNotIn('05:52', r)
                self.assertNotIn('13:52', r)
        # The two rows without a name are no stops; Ljubečna Opekarna and Ropan, passed (I), are none either.
        self.assertEqual(self.d['stops'][i - 1:i + 2], ['Ljubečna GD', 'Ljubečna OŠ', 'Ljubečna nadvoz'])
        self.assertEqual(self.d['runs'][0][i - 1:i + 2], ['05:51', '05:55', '05:57'])

    def test_a_file_object_and_bytes_read_the_same(self):
        data = (FIXTURES / 'celje-10.docx').read_bytes()
        self.assertEqual(nomago_celje.parse(data), nomago_celje.parse(io.BytesIO(data)))
        self.assertEqual(nomago_celje.parse(data), nomago_celje.parse(FIXTURES / 'celje-10.docx'))

    def test_a_time_going_back_is_an_error(self):
        xml = replace_once(document_xml('10'), '<w:t>05:34</w:t>', '<w:t>05:20</w:t>')
        with self.assertRaisesRegex(ValueError, r'edited\.docx: line 10, stop Celje Kid\.ul\.Emo: run 1 goes back from 05:32 to 05:20'):
            read(xml)

    def test_an_unknown_service_code_is_an_error(self):
        xml = replace_once(document_xml('10'), '<w:t>SO</w:t>', '<w:t>XX</w:t>')
        with self.assertRaisesRegex(ValueError, 'service code "XX" is not known'):
            read(xml)

    def test_a_code_the_legend_does_not_explain_is_an_error(self):
        xml = replace_once(document_xml('10'), '<w:t>SO</w:t>', '<w:t>XX</w:t>', last=True)   # the legend's "SO- Vozi ob sobotah"
        with self.assertRaisesRegex(ValueError, 'service code "SO" is not explained in the legend'):
            read(xml)

    def test_a_time_on_a_row_without_a_stop_is_an_error(self):
        xml = replace_once(document_xml('10'), '<w:t>Celeiapark</w:t>', '<w:t></w:t>')
        with self.assertRaisesRegex(ValueError, 'no stop name'):
            read(xml)

    def test_a_missing_validity_is_an_error(self):
        xml = document_xml('10').replace('Čas', 'Cas')
        with self.assertRaisesRegex(ValueError, 'no "Čas veljavnosti'):
            read(xml)


class ThreeTests(SimpleTestCase):
    def setUp(self):
        self.tables = tables('3')

    def test_school_days_and_the_runs_of_every_table(self):
        self.assertEqual(set(self.tables), {'D', 'DS', 'SO'})
        self.assertEqual([len(self.tables[s]['runs']) for s in ('D', 'DS', 'SO')], [29, 2, 8])   # 39 runs in all
        d = self.tables['D']
        self.assertEqual((d['line'], d['title'], len(d['stops']), d['stops'][0], d['stops'][-1]),
                         ('3', 'Hudinja-Škofja vas', 23, 'Celje ŽP', 'Celje ŽP'))
        self.assertEqual((starts(d)[0], starts(d)[-1], ends(d)[-1]), ('04:55', '19:55', '20:40'))
        self.assertEqual((starts(self.tables['DS']), ends(self.tables['DS'])), (['05:55', '06:55'], ['06:40', '07:40']))
        self.assertEqual(self.tables['DS']['runs'][0][:4], ['05:55', '05:58', '05:59', '06:01'])

    def test_rows_that_fell_out_of_the_table_are_the_last_stops_of_their_runs(self):
        names = self.tables['D']['stops']
        self.assertEqual(names[21:], ['Celeiapark', 'Celje ŽP'])
        (d,) = [r for r in self.tables['D']['runs'] if r[0] == '11:55']           # run 19, first column of the table
        (so,) = [r for r in self.tables['SO']['runs'] if r[0] == '11:55']         # run 20
        for run in (d, so):
            self.assertEqual((run[20], run[21], run[22]), ('12:36', '12:38', '12:40'))
        (last,) = [r for r in self.tables['D']['runs'] if r[0] == '14:25']        # run 27, the last column of the paragraphs
        self.assertEqual((last[21], last[22]), ('15:08', '15:10'))

    def test_a_stop_with_a_wait_is_one_call(self):
        i = self.tables['D']['stops'].index('Škofja vas')
        run = self.tables['D']['runs'][0]
        self.assertEqual(run[i], '05:20')            # 05:14 arrives, 05:20 leaves
        self.assertNotIn('05:14', run)

    def test_a_row_with_too_few_times_is_an_error(self):
        xml = document_xml('3')
        paragraph = re.search(r'<w:p>(?:(?!</w:p>).)*?<w:t>12:38</w:t>(?:(?!</w:p>).)*?Celeiapark(?:(?!</w:p>).)*?</w:p>', xml, re.S)
        short = '<w:p><w:r><w:t>12:38 13:08 13:38 14:08 14:38 14:38 15:0811Celeiapark</w:t></w:r></w:p>'
        self.assertIsNotNone(paragraph)
        with self.assertRaisesRegex(ValueError, r'line 3: "12:38 13:08 .*" has 7 times, the table has 9 runs'):
            read(xml.replace(paragraph.group(0), short))

    def test_a_row_with_too_many_times_is_an_error(self):
        xml = document_xml('3')
        paragraph = re.search(r'<w:p>(?:(?!</w:p>).)*?<w:t>12:38</w:t>(?:(?!</w:p>).)*?Celeiapark(?:(?!</w:p>).)*?</w:p>', xml, re.S)
        long = '<w:p><w:r><w:t>12:38 12:38 13:08 13:38 13:38 14:08 14:38 14:38 15:08 15:09 11Celeiapark</w:t></w:r></w:p>'
        with self.assertRaisesRegex(ValueError, 'more times than the table has runs'):
            read(xml.replace(paragraph.group(0), long))


class OneATests(SimpleTestCase):
    def setUp(self):
        self.tables = tables('1a')

    def test_the_line_comes_from_the_cells(self):
        d = self.tables['D']
        self.assertEqual((d['line'], d['title'], d['direction']), ('1a', 'Čopova-Lava most', 0))
        self.assertEqual([len(self.tables[s]['runs']) for s in ('D', 'SO')], [18, 7])       # 25 runs in three blocks
        self.assertEqual((len(d['stops']), d['stops'][6]), (14, 'Celje Lava most'))

    def test_a_cell_with_two_times_is_two_runs(self):
        d, so = self.tables['D'], self.tables['SO']
        # the last row of the second block prints "12:29 12:29", "13:09 13:49" and "15:09 15:49" in cells two columns wide
        self.assertEqual(ends(d)[7:11], ['11:39', '12:29', '13:09', '13:49'])
        self.assertEqual([r[-1] for r in so['runs'] if r[0] == '11:50'], ['12:29'])
        self.assertEqual([r[-1] for r in d['runs'] if r[0] in ('12:30', '13:10')], ['13:09', '13:49'])
        self.assertEqual(ends(so)[:3], ['08:29', '10:29', '12:29'])

    def test_arrival_and_departure_of_the_turn(self):
        d = self.tables['D']
        self.assertEqual([r[6] for r in d['runs']][:3], ['06:56', '07:36', '08:16'])   # 06:43 arrives, 06:56 leaves
        self.assertTrue(all(r[5] and r[7] for r in d['runs']))


class FourTests(SimpleTestCase):
    def setUp(self):
        self.tables = tables('4')

    def test_everything_inside_the_table(self):
        d, so = self.tables['D'], self.tables['SO']
        self.assertEqual((d['line'], d['title']), ('4', 'Nakupovalna'))
        self.assertEqual((len(d['runs']), len(so['runs']), len(d['stops'])), (10, 6, 34))
        self.assertEqual(starts(d), ['09:20', '10:20', '11:20', '13:20', '14:20', '15:20', '16:20', '17:20', '18:20', '20:20'])
        self.assertEqual(starts(so), ['09:20', '11:20', '13:20', '14:20', '16:20', '18:20'])
        self.assertEqual((ends(d)[-1], ends(so)[-1]), ('21:15', '19:15'))


class NationalPoleTests(SimpleTestCase):
    """Line 5's Čret and Teharje stops are only in the national feed: a correction falls back to its poles."""

    def test_a_stop_the_feed_and_osm_lack_takes_the_national_pole(self):
        from prestop_api.citytt import build, poles
        own = [{'id': 'CELEBUS:1', 'name': 'Celje AP', 'lat': 46.23, 'lon': 15.27}]
        national = [{'id': 'IJPP:1130959', 'name': 'Čret Pišek', 'lat': 46.21, 'lon': 15.29},
                    {'id': 'IJPP:5', 'name': 'Celje AP', 'lat': 46.23, 'lon': 15.27}]
        found, _ = poles.unify(own, [])
        lacking = {n for n in ['Celje AP', 'Čret Pišek'] if not poles.candidates(n, found, 'Celje')}
        self.assertEqual(sorted(poles.fallback(lacking, national, 'Celje')), ['IJPP:1130959'])  # never a second Celje AP
        self.assertEqual(build.stop_id('IJPP:1130959', 'CELEBUS'), 'ijpp1130959')  # apart from the feed's own numbers
        self.assertEqual(build.stop_id('IJPP:1130959'), '1130959')

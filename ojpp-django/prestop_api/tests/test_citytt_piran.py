"""Piran's city buses (prestop_api/citytt/arriva_grid.py): Arriva's grid timetables, read from small word fixtures
laid out like the real PDFs, joined where one bus is printed in two files, and built into a feed with a calendar per service."""
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import citytt, supplement
from prestop_api.citytt import arriva_grid, build

PIRAN = citytt.CITIES['Piran']
COLS = [200, 260, 320, 380]   # x of the run columns; the row names end left of 170


def w(text, cx, top):
    """A word centred on cx."""
    width = 6 * len(text)
    return {'text': text, 'x0': cx - width / 2, 'x1': cx + width / 2, 'top': top, 'bottom': top + 10}


def label(text, top, number=None):
    """A row name from x = 20 (and the stray stop number 1.1.2 prints after it)."""
    words, x = [], 20
    for part in text.split():
        words.append({'text': part, 'x0': x, 'x1': x + 6 * len(part), 'top': top, 'bottom': top + 10})
        x += 6 * len(part) + 4
    if number:
        words.append({'text': number, 'x0': 140, 'x1': 146, 'top': top, 'bottom': top + 10})
    return words


def header(top, title, first, second, cols=COLS):
    """Title, then two heading rows: first = (row name, values), second likewise (the codes and the run numbers in either order)."""
    words = label(title, 5)
    for k, (name, values) in enumerate((first, second)):
        words += label(name, top + 12 * k)
        words += [w(v, cols[j], top + 12 * k) for j, v in enumerate(values)]
    return words


def rows(top, spec, cols=COLS):
    """spec: [(name, {column: text}, stray stop number or None)] at 14 pt a row."""
    words = []
    for k, (name, cells, number) in enumerate(spec):
        t = top + 14 * k
        words += label(name, t, number) if name else []
        words += [w(text, cols[j], t) for j, text in cells.items()]
    return words


class ReaderTests(SimpleTestCase):
    def test_a_grid_with_krka_the_bypass_and_a_stray_cell(self):
        # Codes above run numbers; Lucija AP is printed twice (arrival, departure); in column 1 the bus goes on to Krka;
        # column 0 calls at Fizine at the minute it called at Pirat (the bypass: it does not stop); column 2 has a cell
        # that follows nothing (06:30 after 22:11).
        names = ['Piran', 'Pirat', 'Fizine', 'Lucija AP', 'Lucija AP', 'TC Tuš']
        cells = [{0: '05:30', 1: '06:00', 2: '22:00'}, {0: '05:31', 1: '06:01', 2: '22:01'},
                 {0: '05:31', 1: '06:01', 2: '22:02'}, {0: '05:40', 1: '06:10', 2: '22:10'},
                 {0: '05:41', 1: '06:11', 2: '22:11'}, {0: '05:45', 2: '06:30'}]
        words = header(20, 'Line 1.1.1 Piran AP-Beli Križ', ('Avtobusna', ['D*', 'D*', 'PESO']), ('postajališča', ['1', '2', '3']))
        words += rows(50, [(n, c, None) for n, c in zip(names, cells)])
        words.append(w('Krka', COLS[1], 50 + 14 * 5))
        words += label('Remarks: D* - drives on workdays', 50 + 14 * 6)
        tables = arriva_grid.read([words])
        by = {(t['line'], t['direction'], t['service']): t for t in tables}
        self.assertEqual(sorted(by), [('1.1.1', 0, 'D'), ('1.1.1', 0, 'FRI')])   # PESO is Friday
        d = by[('1.1.1', 0, 'D')]
        self.assertEqual(d['stops'], ['Piran', 'Pirat', 'Fizine', 'Lucija AP', 'TC Tuš'])   # Lucija AP once
        self.assertEqual(d['runs'], [['05:30', '05:31', None, '05:41', '05:45'],   # Fizine dropped, departure from Lucija AP
                                     ['06:00', '06:01', None, '06:11', None]])
        self.assertEqual(d['krka'], [False, True])
        self.assertTrue(any('calls at the same minute' in n and 'Fizine' in n for n in d['notes']))
        fri = by[('1.1.1', 0, 'FRI')]
        self.assertEqual(fri['runs'], [['22:00', '22:01', '22:02', '22:11', None]])   # 06:30 dropped
        self.assertTrue(any('06:30 at TC Tuš dropped' in n for n in fri['notes']))

    def test_run_numbers_above_codes_stop_numbers_and_dashes(self):
        names = ['Piran', 'Lucija AP', 'Strunjan', 'Krka zdrav.']
        cells = [{0: '06:15', 1: '07:00', 3: '09:00'}, {0: '06:29', 1: '07:10', 3: '09:14'},
                 {0: '06:36', 1: '07:20', 2: '07:00', 3: '09:21'}, {0: '06:39', 1: '07:23', 2: '07:03', 3: '09:24'}]
        for c in cells[:2]:   # "-" where a run does not call
            c.update({j: '-' for j in range(4) if j not in c})
        words = header(20, 'Linija 1.1.2 Piran-Portorož', ('postaje', ['1', '2', '3', '4']), ('postajališča', ['V', 'D*', 'SONP', '**V']))
        words += rows(50, [(n, c, str(k + 2)) for k, (n, c) in enumerate(zip(names, cells))])
        words += label('V - vozi vsak dan', 50 + 14 * 4)
        tables = arriva_grid.read([words])
        by = {t['service']: t for t in tables}
        self.assertEqual(sorted(by), ['D', 'SONP', 'V'])        # **V is summer only
        self.assertEqual(by['V']['runs'], [['06:15', '06:29', '06:36', '06:39']])
        self.assertEqual(by['D']['runs'], [['07:00', '07:10', '07:20', '07:23']])
        self.assertEqual(by['SONP']['runs'], [[None, None, '07:00', '07:03']])
        self.assertEqual(by['V']['stops'], names)
        self.assertTrue(any('**V (summer only) left out' in n for t in tables for n in t['notes']))

    def test_later_pages_without_row_names_continue_the_grid_by_height(self):
        names = ['Piran', 'Pirat', 'Lucija AP']
        page1 = header(20, 'Line 1.1.1 Piran AP-Beli Križ', ('BUS', ['SO'] * 3), ('STOP', ['1', '2', '3']))
        page1 += rows(50, [(n, {0: f'0{6 + k}:00', 1: f'0{6 + k}:30', 2: f'0{6 + k}:45'}, None) for k, n in enumerate(names)])
        page2 = header(20, 'Line 1.1.1 Piran AP-Beli Križ', ('', ['SO'] * 3), ('', ['4', '5', '6']))
        page2 += rows(50, [('', {0: f'1{k}:00', 1: f'1{k}:30', 2: f'1{k}:45'}, None) for k, _ in enumerate(names)])
        tables = arriva_grid.read([page1, page2])
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]['service'], 'SO')
        self.assertEqual(tables[0]['stops'], names)
        self.assertEqual(tables[0]['runs'], [['06:00', '07:00', '08:00'], ['06:30', '07:30', '08:30'], ['06:45', '07:45', '08:45'],
                                             ['10:00', '11:00', '12:00'], ['10:30', '11:30', '12:30'], ['10:45', '11:45', '12:45']])

    def test_an_unknown_day_code_fails_instead_of_guessing(self):
        words = header(20, 'Line 1.1.1 Piran AP-Beli Križ', ('Avtobusna', ['ZZ', 'D*', 'D*']), ('postajališča', ['1', '2', '3']))
        words += rows(50, [('Piran', {0: '06:00', 1: '07:00', 2: '08:00'}, None), ('Pirat', {0: '06:01', 1: '07:01', 2: '08:01'}, None)])
        with self.assertRaisesRegex(arriva_grid.ReadError, "unknown day code 'ZZ'"):
            arriva_grid.read([words])


STOPS = ['Piran', 'Bernardin K', 'Lucija AP']
LONG = STOPS + ['Krka zdrav.']


def table(line, direction, service, runs, krka=None):
    stops = (LONG if line == '1.1.2' else STOPS)[::1 if direction == 0 else -1]
    return {'line': line, 'title': 'Piran AP-Lucija AP', 'stops': stops, 'runs': runs, 'direction': direction, 'service': service,
            'notes': [], 'krka': krka or [False] * len(runs)}


def files(out_d=None, out_so=None, out_v=None, extra=()):
    """Every table the combine requires: outbound 1.1.1 D and SO as given (runs, krka flags), 1.1.2 V runs as given."""
    tables = []
    for d in (0, 1):
        plain = [['05:30', '05:33', '05:40']] if d == 0 else [['05:40', '05:33', '05:30']]
        for service, given in (('D', out_d), ('SO', out_so)):
            runs, krka = given if given and d == 0 else (plain, None)
            tables.append(table('1.1.1', d, service, runs, krka))
        tables.append(table('1.1.1', d, 'NP', plain))
        tables.append(table('1.1.2', d, 'V', out_v if out_v and d == 0 else []))
    return tables + list(extra)


class CombineTests(SimpleTestCase):
    def test_a_krka_run_is_the_1_1_2_bus_and_goes(self):
        tables, notes = arriva_grid.combine(files(out_d=([['05:30', '05:33', '05:40'], ['06:15', '06:18', '06:29']], [False, True]),
                                                  out_v=[['06:15', '06:18', '06:29', '06:39']]), PIRAN)
        d = next(t for t in tables if (t['line'], t['direction'], t['service']) == ('1.1.1', 0, 'D'))
        self.assertEqual(d['runs'], [['05:30', '05:33', '05:40']])
        self.assertEqual(d['krka'], [False])
        v = next(t for t in tables if (t['line'], t['direction'], t['service']) == ('1.1.2', 0, 'V'))
        self.assertEqual(v['runs'], [['06:15', '06:18', '06:29', '06:39']])   # the 1.1.2 trip stays
        self.assertTrue(any(n.startswith('MERGED: 1.1.1 out D Piran 06:15 = 1.1.2 out V Piran 06:15') and n.endswith('dropped') for n in notes), notes)

    def test_a_krka_run_no_1_1_2_run_matches_stays_and_is_reported(self):
        tables, notes = arriva_grid.combine(files(out_so=([['08:00', '08:03', '08:10']], [True]), out_v=[['06:15', '06:18', '06:29', '06:39']]), PIRAN)
        so = next(t for t in tables if (t['line'], t['direction'], t['service']) == ('1.1.1', 0, 'SO'))
        self.assertEqual(so['runs'], [['08:00', '08:03', '08:10']])
        self.assertTrue(any(n.startswith('UNMATCHED') and '08:00' in n for n in notes), notes)

    def test_a_1_1_2_run_covering_part_of_the_days_with_no_service_for_the_rest_fails(self):
        friday = table('1.1.2', 0, 'FRI', [['06:15', '06:18', '06:29', '06:39']])
        with self.assertRaisesRegex(arriva_grid.ReadError, 'covers only part of it'):
            arriva_grid.combine(files(out_d=([['06:15', '06:18', '06:29']], [True]), extra=[friday]), PIRAN)

    def test_a_missing_file_is_an_error_not_a_thinner_timetable(self):
        tables = [t for t in files() if t['service'] != 'NP']
        with self.assertRaisesRegex(arriva_grid.ReadError, r'line 1\.1\.1 has no timetable for NP \(out\): a file may be missing'):
            arriva_grid.combine(tables, PIRAN)
        with self.assertRaisesRegex(arriva_grid.ReadError, 'line 1.1.2 has no timetable for V'):
            arriva_grid.combine([t for t in files() if t['line'] != '1.1.2'], PIRAN)


class CalendarTests(SimpleTestCase):
    def test_each_service_runs_on_its_weekdays_and_holidays_by_its_flag(self):
        rows, dates = build.calendar(PIRAN)
        by = {r['service_id']: r for r in rows}
        self.assertEqual(sorted(by), ['D', 'FRI', 'NP', 'SO', 'SONP', 'V'])
        self.assertEqual([by['D'][d] for d in ('monday', 'friday', 'saturday', 'sunday')], ['1', '1', '0', '0'])
        self.assertEqual([by['FRI'][d] for d in ('thursday', 'friday', 'saturday')], ['0', '1', '0'])
        self.assertEqual([by['SONP'][d] for d in ('friday', 'saturday', 'sunday')], ['0', '1', '1'])
        self.assertEqual({r['start_date'] for r in rows}, {'20261101'})
        self.assertEqual({r['end_date'] for r in rows}, {'20270331'})
        ex = {(d['service_id'], d['date']): d['exception_type'] for d in dates}
        # Christmas 2026 is a Friday: the workday services stop, the holiday ones start.
        self.assertEqual([ex.get((s, '20261225')) for s in ('D', 'FRI', 'SO', 'NP', 'SONP', 'V')], ['2', '2', None, '1', '1', None])
        # Independence and Unity Day, a Saturday: SO stops, NP starts; SONP and V run as usual.
        self.assertEqual([ex.get((s, '20261226')) for s in ('D', 'SO', 'NP', 'SONP', 'V')], [None, '2', '1', None, None])
        self.assertEqual(ex[('D', '20270329')], '2')       # Easter Monday
        self.assertNotIn(('NP', '20261227'), ex)           # an ordinary Sunday
        self.assertFalse([k for k in ex if k[1] < '20261101' or k[1] > '20270331'])

    def test_only_the_services_in_use_get_rows(self):
        rows, dates = build.calendar(PIRAN, {'D', 'NP'})
        self.assertEqual([r['service_id'] for r in rows], ['D', 'NP'])
        self.assertEqual({d['service_id'] for d in dates}, {'D', 'NP'})


def pole(i, name, lat, lon):
    return {'id': f'IJPP:{i}', 'name': name, 'lat': lat, 'lon': lon}


def straight(window):
    return [[[a['lon'], a['lat']], [b['lon'], b['lat']]] for a, b in zip(window, window[1:])]


PAGES = {
    'https://arriva.si/avtobusni-prevozi/mestni-avtobusni-prevozi/mestni-avtobusni-prevozi-piran/vozni-red-in-cenik-piran/':
        '<a href="https://arriva.si/wp-content/uploads/2026/09/Linija-1.1.1_POPE.pdf">a</a>'
        '<a href="https://arriva.si/wp-content/uploads/2026/06/Linija-1.1.1._NP_1.11.2026.pdf">b</a>'
        '<a href="https://arriva.si/wp-content/uploads/2025/12/Linija-1.1.2-.pdf">c</a>'
        '<a href="https://arriva.si/wp-content/uploads/2026/06/Linija-1.1.1_SOB-1.pdf">stale</a>'
        '<a href="https://arriva.si/wp-content/uploads/2025/06/Cenik-Mestni-promet-Piran-od-1.2.2025-naprej.pdf">price list</a>',
    PIRAN.pages[0]:
        '<a href="https://arriva.si/wp-content/uploads/2026/10/Line-1.1.1._Sat_1.11.2026.pdf">Saturdays</a>'
        '<a href="https://arriva.si/wp-content/uploads/2026/10/Line-1.1.1._SH_1.11.2026.pdf">stale</a>',
}


class FetchTests(SimpleTestCase):
    def fetch(self, pages):
        get = lambda url: pages[url].encode() if url in pages else b'%PDF ' + url.encode()  # noqa: E731
        with mock.patch.object(build, '_get', side_effect=get), mock.patch.object(build.time, 'sleep'):
            return build.fetch(PIRAN)

    def test_the_four_files_are_read_and_the_stale_ones_ignored(self):
        _, got = self.fetch(PAGES)
        self.assertEqual(sorted(f['name'] for f in got), sorted(PIRAN.files))

    def test_a_vanished_or_new_file_is_reported(self):
        gone = {**PAGES, PIRAN.pages[0]: '<p>nothing</p>'}
        with self.assertRaisesRegex(build.BuildError, 'Line-1.1.1._Sat_1.11.2026.pdf is no longer linked'):
            self.fetch(gone)
        new = {**PAGES, PIRAN.pages[0]: PAGES[PIRAN.pages[0]] + '<a href="https://arriva.si/wp-content/uploads/2026/11/Linija-1.1.1_SOB_2.pdf">x</a>'}
        with self.assertRaisesRegex(build.BuildError, 'Linija-1.1.1_SOB_2.pdf is new on the pages'):
            self.fetch(new)


class BuildTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = mock.patch.object(supplement, 'LOCAL_GTFS', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sources(self, page=None):
        feed = [pole(1, 'Piran', 45.5283, 13.5683), pole(2, 'Bernardin K', 45.5240, 13.5780),
                pole(3, 'Lucija AP', 45.5000, 13.6010), pole(4, 'Krka zdrav.', 45.5340, 13.6110)]
        names = [f.rsplit('/', 1)[-1] for f in PIRAN.files]
        return build.Sources(page or f'<p>{PIRAN.days}</p>', [{'url': f'https://arriva.si/{n}', 'name': n, 'data': b'%PDF'} for n in names], feed, [], [], [])

    def test_the_services_become_trips_with_calendars(self):
        by_file = {
            'Linija-1.1.1_POPE.pdf': [table('1.1.1', d, 'D', [['05:30', '05:33', '05:40'], ['06:15', '06:18', '06:29']], [False, True]) for d in (0,)] +
                                     [table('1.1.1', 1, 'D', [['05:40', '05:33', '05:30']])],
            'Line-1.1.1._Sat_1.11.2026.pdf': [table('1.1.1', d, 'SO', [['05:35', '05:38', '05:45']]) for d in (0, 1)],
            'Linija-1.1.1._NP_1.11.2026.pdf': [table('1.1.1', d, 'NP', [['05:35', '05:38', '05:45'], ['05:35', '05:38', '05:45']]) for d in (0, 1)],
            'Linija-1.1.2-.pdf': [table('1.1.2', 0, 'V', [['06:15', '06:18', '06:29', '06:39']]), table('1.1.2', 1, 'V', [])],
        }
        calls = iter(PIRAN.files)
        with mock.patch.object(arriva_grid, 'parse', side_effect=lambda path: [dict(t, runs=[list(r) for r in t['runs']], krka=list(t['krka']))
                                                                                  for t in by_file[next(calls)]]):
            out, status = build.build(PIRAN, self.sources(), date(2026, 11, 4), route=straight)
        self.assertEqual(status['end'], '2027-03-31')
        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['services'], {'1.1.1 out D': 1, '1.1.1 back D': 1, '1.1.1 out NP': 2, '1.1.1 back NP': 2,
                                              '1.1.1 out SO': 1, '1.1.1 back SO': 1, '1.1.2 out V': 1})
        self.assertTrue(any(n.startswith('MERGED: 1.1.1 out D Piran 06:15') for n in status['notes']))
        build.write(PIRAN, out, status, date(2026, 11, 4))
        self.assertEqual(json.loads((self.root / 'Piran' / 'status.json').read_text(encoding='utf-8'))['end'], '2027-03-31')
        feed = supplement.parse('Piran', supplement._local_zip(str(self.root / 'Piran')))
        self.assertEqual(sorted({t['serviceId'] for t in feed['trips'].values()}), ['D', 'NP', 'SO', 'V'])
        nps = [t for t in feed['trips'].values() if t['serviceId'] == 'NP' and t['directionId'] == 0]
        self.assertEqual(len(nps), 2)                      # two buses at one minute are two trips
        self.assertEqual(len({t['id'] for t in feed['trips'].values()}), len(feed['trips']))
        self.assertEqual([s['stopId'] for s in nps[0]['stops']], ['Piran:1', 'Piran:2', 'Piran:3'])
        self.assertTrue(supplement.runs(feed, 'NP', date(2026, 12, 25)))        # Christmas, a Friday
        self.assertFalse(supplement.runs(feed, 'D', date(2026, 12, 25)))
        self.assertTrue(supplement.runs(feed, 'SO', date(2026, 11, 7)))
        self.assertFalse(supplement.runs(feed, 'SO', date(2026, 12, 26)))       # a holiday Saturday runs NP
        self.assertEqual(citytt.health(date(2026, 11, 4))[1]['id'], 'city-timetables:Piran')

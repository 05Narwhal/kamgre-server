"""Marprom's (Maribor) timetables rebuilt as a hand-kept feed (prestop_api/citytt/marprom.py).

The reader's fixture is one real page (G1 towards Tezenska Dobrava, stop 001) as pdfplumber read it on 2026-11-04, cut
down to the hour columns 04–08 (tests/fixtures/citytt/marprom-g1-plus-s1.words.json); the other pages are made by `page()`
with the layout of the real ones (hour columns 31 pt apart from x=26, minutes stacked 18 pt apart, the stop list at x=669).
"""
import csv
import io
import json
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import citytt, supplement
from prestop_api.citytt import build, marprom

FIXTURES = Path(__file__).parent / 'fixtures' / 'citytt'
MARPROM = citytt.CITIES['MARPROM']
TITLES = {'weekday': ('Ponedeljek', 0), 'saturday': ('Sobota', 0), 'sunday': ('Nedelja', 0), 'weekday_holiday': ('Ponedeljek', 1)}


def w(text, x0, top, size=13.8, width=None):
    return {'text': text, 'x0': x0, 'x1': x0 + (width or 6 * len(text)), 'top': top, 'bottom': top + size, 'size': size}


def page(line, name, ident, stops, here, tables, headsign='Delta', hours=range(4, 24), extra=(), valid=True):
    """The words of one page. `tables` maps a kind to ['05:00', '05:20*', …]; the header lists `hours` (24+ is after midnight
    and printed as hour − 24)."""
    words = [w(line, 38, 26, 40.4), w('<>', 226.9, 69, 46.1), w('Smer', 125.8, 61.2, 19.7), w('→', 178.5, 61.3, 19.7)]
    for i, part in enumerate(name.split()):
        words.append(w(part, 226.9 + 70 * i, 19.9, 26.6))
    for i, part in enumerate(headsign.split()):
        words.append(w(part, 209.6 + 60 * i, 61.2, 19.7))
    words += [w('ID:', 595.4, 59.6), w(ident, 615.6, 59.6), w('Ime', 26.2, 92.1, 18.4), w('linije:', 64, 92.1, 18.4), w('Tezno', 119.7, 92.1, 18.4)]
    if valid:
        words += [w('velja', 488.1, 122.7), w('od', 519.4, 122.7), w('01.09.2026', 539.5, 122.7)]
    top = 124.7
    for kind, (title, school) in TITLES.items():
        words.append(w(title, 17.5, top, 20.8))
        if school:
            words.append(w('(ŠP)', 353, top + 5))
        header = top + 28
        for k, h in enumerate(hours):
            words.append(w(f'{h % 24:02d}', 26 + 31.1 * k, header))
        rows = {}
        for t in tables.get(kind, []):
            hour, rest = t.split(':')
            rows.setdefault(int(hour), []).append(rest)
        for k, h in enumerate(hours):
            for n, minute in enumerate(sorted(rows.get(h, []))):
                small = minute.endswith('*')
                words.append(w(minute, 26 + 31.1 * k + (0 if not small else -2), header + 19 + 18.4 * n, 11.5 if small else 13.8))
        top = header + 19 + 18.4 * max([len(v) for v in rows.values()] or [0]) + 20
    words += [w('od', 293.5, top + 5, 11.5), w('28.12.2026', 301, top + 5, 11.5), w('do', 360, top + 5, 11.5), w('31.12.2026,', 370, top + 5, 11.5),
              w('od', 293.5, top + 20, 11.5), w('28.4.2027', 301, top + 20, 11.5), w('do', 360, top + 20, 11.5), w('30.4.2027', 370, top + 20, 11.5),
              w('in', 421, top + 20, 11.5), w('od', 433, top + 20, 11.5), w('26.6.2027', 448, top + 20, 11.5), w('do', 497, top + 20, 11.5), w('31.8.2027', 511, top + 20, 11.5)]
    for i, stop in enumerate(stops):
        marker = '◆' if i == here or (isinstance(here, tuple) and i in here) else '●' if i in (0, len(stops) - 1) else '∨'
        words.append(w(marker, 668.9, 20 + 16.3 * i, 12.7))
        for k, part in enumerate(stop.split()):
            words.append(w(part, 690.5 + 40 * k, 21 + 16.3 * i, 10.4))
    return words + list(extra)


class ReaderTests(SimpleTestCase):
    def test_a_real_page(self):
        doc = marprom.read(json.loads((FIXTURES / 'marprom-g1-plus-s1.words.json').read_text(encoding='utf-8')))
        self.assertEqual((doc['line'], doc['name'], doc['headsign'], doc['line_name']), ('G1', 'Avtobusna postaja', 'Tezenska Dobrava', 'Tezno'))
        self.assertEqual((doc['stop_code'], doc['valid_from'], doc['position']), ('s1', date(2026, 9, 1), 0))   # "ID: 001"
        self.assertEqual(doc['stops_in_order'][:3] + doc['stops_in_order'][-1:], ['Avtobusna postaja', 'City - zdravstveni dom', 'Europark - Titov most', 'Tezenska Dobrava'])
        self.assertEqual(len(doc['stops_in_order']), 14)
        # The site's page for this stop lists 05:00 05:20 05:40 06:00 06:15 on a weekday.
        self.assertEqual([t for t, _ in doc['tables']['weekday']][:5], ['05:00', '05:20', '05:40', '06:00', '06:15'])
        self.assertEqual(doc['tables']['weekday_holiday'][:3], [('05:10', ''), ('05:30', ''), ('05:50', '')])
        self.assertEqual(doc['holiday_ranges'], [(date(2026, 12, 28), date(2026, 12, 31)), (date(2027, 4, 28), date(2027, 4, 30)), (date(2027, 6, 26), date(2027, 8, 31))])

    def test_minutes_belong_to_the_hour_column_they_stand_under(self):
        doc = marprom.read(json.loads((FIXTURES / 'marprom-g1-plus-s1.words.json').read_text(encoding='utf-8')))
        # Saturday's columns 04 and 05 are empty: the first minute is under 06, not the first column.
        self.assertEqual(doc['tables']['saturday'][:3], [('06:05', ''), ('06:35', ''), ('07:05', '')])
        self.assertEqual(doc['tables']['sunday'], [('06:05', ''), ('07:05', ''), ('08:05', '')])
        # A column with four minutes keeps all four, in order.
        self.assertEqual([t for t, _ in doc['tables']['weekday'] if t.startswith('06')], ['06:00', '06:15', '06:30', '06:45'])

    def test_template_placeholders_are_dropped_and_a_star_is_a_variant_mark(self):
        words = page('G4', 'Dom pod Gorco', '642', ['A', 'B Stop', 'C'], 1, {'weekday': ['06:00', '06:25*', '06:25']},
                     extra=[w('<>', 488.1, 150.5), w('*', 470, 560), w('Vozi', 485, 560), w('do', 510, 560), w('Lesarske', 525, 560), w('šole.', 580, 560)])
        header = next(x for x in words if x['text'] == '19' and abs(x['top'] - 152.7) < 1)
        header['text'] = '<1>9'   # pdfplumber without per-font splitting: the empty field inside hour 19's header
        doc = marprom.read(words)
        self.assertEqual(doc['stop_code'], 's642')
        self.assertEqual(doc['name'], 'Dom pod Gorco')
        self.assertEqual(doc['tables']['weekday'], [('06:00', ''), ('06:25', ''), ('06:25', '*')])
        self.assertEqual(doc['legend'], {'*': 'Vozi do Lesarske šole.'})

    def test_a_p_r_caption_beside_the_name_is_not_part_of_it(self):
        words = page('G5', 'P&R Koroški most', '636', ['A', 'B', 'C'], 1, {}, extra=[w('Pod', 119.7, 36.5, 9.3), w('koroškim', 138.9, 36.5, 9.3)])
        self.assertEqual(marprom.read(words)['name'], 'P&R Koroški most')

    def test_columns_after_the_last_hour_are_past_midnight(self):
        doc = marprom.read(page('G1', 'A', '001', ['A', 'B'], 0, {'weekday': ['23:50', '24:10']}, hours=[*range(21, 24), 24, 25]))
        self.assertEqual(doc['tables']['weekday'], [('23:50', ''), ('24:10', '')])

    def test_a_minute_under_no_hour_or_an_unreadable_page_fails(self):
        words = page('G1', 'A', '001', ['A', 'B'], 0, {'weekday': ['05:10']}, extra=[w('33', 700, 190)])
        words[-1]['x0'] = 640   # beyond the last column, inside the timetable
        words[-1]['x1'] = 650
        with self.assertRaises(marprom.ReadError):
            marprom.read(words)
        with self.assertRaises(marprom.ReadError):
            marprom.read([w('Nothing', 20, 20)])


def pages(*rows, stops=('Alfa', 'Beta', 'Gama', 'Delta'), line='G9', headsign='Delta'):
    """Pages of one direction: rows are (position, stop id, tables)."""
    return [marprom.read(page(line, stops[at], ident, list(stops), at, tables, headsign=headsign)) for at, ident, tables in rows]


class DirectionTests(SimpleTestCase):
    def test_pages_are_put_at_their_place_in_the_stop_list_and_the_last_stop_has_none(self):
        doc = marprom.direction(pages((1, '002', {'weekday': ['05:05']}), (0, '001', {'weekday': ['05:00', '06:00']}), (2, '003', {'weekday': ['05:10']})))
        self.assertEqual([c for c, _ in doc['stops']], ['s1', 's2', 's3', None])
        self.assertEqual(doc['stops'][-1], (None, 'Delta'))
        self.assertEqual(doc['tables']['weekday'], [[(300, ''), (360, '')], [(305, '')], [(310, '')], []])
        self.assertEqual(doc['no_page'], [])

    def test_a_stop_in_the_middle_without_a_page_is_listed(self):
        doc = marprom.direction(pages((0, '001', {}), (2, '003', {})))
        self.assertEqual(doc['no_page'], ['Beta'])

    def test_a_loop_has_its_first_stop_as_its_last(self):
        stops = ('Tabor', 'Beta', 'Gama', 'Tabor')
        words = page('G3', 'Tabor', '001', list(stops), (0, 3), {'weekday': ['05:00']})
        doc = marprom.read(words)
        self.assertEqual(doc['position'], 0)   # the page is the start's; the last is the end of the run
        with self.assertRaises(marprom.ReadError):   # two ◆ elsewhere than first and last
            marprom.read(page('G3', 'Beta', '002', list(stops), (1, 2), {}))

    def test_pages_of_two_timetables_fail(self):
        a = marprom.read(page('G9', 'Alfa', '001', ['Alfa', 'Beta'], 0, {}))
        b = marprom.read(page('G9', 'Beta', '002', ['Alfa', 'Beta'], 1, {}))
        b['valid_from'] = date(2026, 10, 1)
        with self.assertRaisesRegex(marprom.ReadError, 'valid_from'):
            marprom.direction([a, b])


def every(gap):
    return lambda i, j: [gap * (j - i)]


class ChainTests(SimpleTestCase):
    def test_short_run_depot_start_and_run_without_continuation(self):
        deps = [[(300, ''), (360, '')],               # A 05:00 06:00
                [(305, ''), (340, ''), (365, '')],    # B 05:05, 05:40 (starts here: no one led up to it), 06:05
                [(310, ''), (345, '')]]               # C 05:10, 05:45 (the 06:05 run goes no further)
        trips = marprom.chain(deps, every(5))
        self.assertEqual([[(i, m) for i, m, _ in t] for t in trips],
                         [[(0, 300), (1, 305), (2, 310)], [(1, 340), (2, 345)], [(0, 360), (1, 365)]])

    def test_no_time_is_made_up_and_a_stop_without_departures_is_passed_by(self):
        deps = [[(300, '')], [], [(310, '')]]
        trips = marprom.chain(deps, lambda i, j: [10] if (i, j) == (0, 2) else None)
        self.assertEqual(trips, [[(0, 300, ''), (2, 310, '')]])

    def test_a_run_time_that_is_off_by_more_than_the_tolerance_splits_the_trip(self):
        deps = [[(300, '')], [(309, '')]]
        self.assertEqual(len(marprom.chain(deps, every(5))), 2)
        self.assertEqual(len(marprom.chain(deps, every(8))), 1)

    def test_trips_keep_their_order(self):
        deps = [[(300, ''), (310, '')], [(303, ''), (313, '')]]
        trips = marprom.chain(deps, every(3))
        self.assertEqual([[(m) for _, m, _ in t] for t in trips], [[300, 303], [310, 313]])

    def test_twin_buses_stay_two(self):
        deps = [[(300, ''), (300, '')], [(305, ''), (305, '')]]
        self.assertEqual(marprom.chain(deps, every(5)), [[(0, 300, ''), (1, 305, '')]] * 2)

    def test_a_star_variant_stop_is_only_called_at_by_starred_trips(self):
        deps = [[(300, '*'), (330, '')],              # A: the first goes by the variant stop
                [(303, '*')],                         # V: the variant stop, all starred
                [(305, ''), (335, '')]]               # B
        run = lambda i, j: [{(0, 1): 3, (1, 2): 2, (0, 2): 5}[i, j]]  # noqa: E731
        trips = marprom.chain(deps, run)
        self.assertEqual([[i for i, _, _ in t] for t in trips], [[0, 1, 2], [0, 2]])
        self.assertEqual([t[-1][1] for t in trips], [305, 335])

    def test_run_times_are_kept_per_service_since_a_weekend_layover_is_longer(self):
        published = [('wd', [('a', 600), ('b', 602)]), ('wd', [('a', 660), ('b', 662)]), ('we', [('a', 600), ('b', 605)])]
        run = marprom.run_times(['a', 'b', 'c'], published, [[(1, '')], [(2, '')], [(3, '')]])
        self.assertEqual(run(0, 1), [2, 5])
        self.assertEqual(run(1, 2), [1])   # no published pair: both have one departure, the zip says 1


def zip_of(tables: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, rows in tables.items():
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
            z.writestr(f'{name}.txt', out.getvalue())
    return buf.getvalue()


def published(extra_trips=()):
    """A published feed shaped like Marprom's: a summer weekday service that ended, Saturday and Sunday to the year's end."""
    stops = [{'stop_id': str(10 * (i + 1)), 'stop_code': f's{i + 1}', 'stop_name': n, 'stop_lat': '46.5500', 'stop_lon': f'{15.60 + 0.01 * i:.4f}'}
             for i, n in enumerate(['Alfa', 'Beta', 'Gama', 'Delta'])]
    trips, times = [], []
    for tid, service, start in [('w1', '8726', 300), ('s1', '8727', 360), ('u1', '8728', 420), ('x1', '8729', 480), *extra_trips]:
        trips.append({'route_id': '7', 'service_id': service, 'trip_id': tid, 'trip_headsign': 'Alfa - Delta', 'trip_short_name': 'G9', 'direction_id': '0', 'shape_id': '70'})
        times += [{'trip_id': tid, 'arrival_time': marprom._time(start + 5 * k), 'departure_time': marprom._time(start + 5 * k), 'stop_id': s['stop_id'],
                   'stop_sequence': str(k + 1), 'timepoint': '1'} for k, s in enumerate(stops)]
    days = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
    calendar = [{'service_id': s, **{d: str(int(d in on)) for d in days}, 'start_date': '20260707', 'end_date': end}
                for s, on, end in [('8726', days[:5], '20260831'), ('8727', ('saturday',), '20261231'), ('8728', ('sunday',), '20261231'), ('8729', ('sunday',), '20260831')]]
    return {
        'agency': [{'agency_id': '3', 'agency_name': 'Marprom', 'agency_url': 'https://marprom.si', 'agency_timezone': 'Europe/Ljubljana', 'agency_lang': 'sl'}],
        'routes': [{'route_id': '7', 'agency_id': '3', 'route_short_name': 'G9', 'route_long_name': 'Test', 'route_type': '3'}],
        'stops': stops, 'trips': trips, 'stop_times': times, 'calendar': calendar,
        'calendar_dates': [{'service_id': '8727', 'date': '20261226', 'exception_type': '2'}, {'service_id': '8728', 'date': '20261225', 'exception_type': '1'},
                           {'service_id': '8728', 'date': '20261226', 'exception_type': '1'}],
        'shapes': [{'shape_id': '70', 'shape_pt_sequence': str(k), 'shape_pt_lat': '46.5500', 'shape_pt_lon': f'{15.60 + 0.005 * k:.4f}'} for k in range(8)] +
                  [{'shape_id': '71', 'shape_pt_sequence': '0', 'shape_pt_lat': '46.60', 'shape_pt_lon': '15.60'}, {'shape_id': '71', 'shape_pt_sequence': '1', 'shape_pt_lat': '46.60', 'shape_pt_lon': '15.61'}],
    }


PDF = {
    '001': {'weekday': ['05:00', '06:00'], 'saturday': ['06:00'], 'sunday': ['07:00'], 'weekday_holiday': ['05:30']},
    '002': {'weekday': ['05:05', '05:50', '06:05'], 'saturday': ['06:05'], 'sunday': ['07:05'], 'weekday_holiday': ['05:35']},
    '003': {'weekday': ['05:10', '05:55'], 'saturday': ['06:10'], 'sunday': ['07:10'], 'weekday_holiday': ['05:40']},
}


def fetched(tables=None, codes=('001', '002', '003'), **changes):
    tables = tables or PDF
    docs = pages(*[(i, code, tables[code]) for i, code in enumerate(codes)])
    file = {'url': 'https://www.marprom.si/dokumentacija/prihajajoci-vozni-redi/PVRG9-20260901_plus.pdf', 'name': 'PVRG9-20260901_plus.pdf', 'line': 'G9', 'dir': 'plus', 'data': b'pdf'}
    return marprom.Fetched(zip_of(published(**changes)), [file]), lambda data: docs


class FeedTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = mock.patch.object(supplement, 'LOCAL_GTFS', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.today = date(2026, 11, 4)

    def make(self, **kw):
        src, read = fetched(**kw)
        return marprom.make(MARPROM, src, self.today, read=read)

    def feed(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for name, text in files.items():
                z.writestr(name, text)
        return supplement.parse('MARPROM', buf.getvalue())

    def running(self, feed, day):
        return sorted(t['id'].split(':')[1] for t in feed['trips'].values() if supplement.runs(feed, t['serviceId'], day))

    def test_weekday_trips_come_from_the_pdfs_with_stable_ids_and_the_published_shape(self):
        files, status = self.make()
        feed = self.feed(files)
        weekday = [t for t in feed['trips'].values() if t['serviceId'] == 'pdf-weekday']
        self.assertEqual(sorted(t['id'] for t in weekday), ['MARPROM:G9-plus-wd-s1-0500', 'MARPROM:G9-plus-wd-s1-0600', 'MARPROM:G9-plus-wd-s2-0550'])
        first = feed['trips']['MARPROM:G9-plus-wd-s1-0500']
        self.assertEqual([(s['stopId'], s['departure']) for s in first['stops']], [('MARPROM:10', 300 * 60), ('MARPROM:20', 305 * 60), ('MARPROM:30', 310 * 60), ('MARPROM:40', 315 * 60)])
        self.assertEqual((first['shapeId'], first['headsign']), ('70', 'Alfa - Delta'))        # same stops as a published trip
        self.assertEqual(feed['trips']['MARPROM:G9-plus-wd-s2-0550']['shapeId'], '70')          # a published trip with more stops
        self.assertEqual(status['shapes'], {'published trip': 2, 'published trip with more stops': 2})
        self.assertEqual(status['lines'], {'G9': 3})
        self.assertEqual([t['id'] for t in feed['trips'].values() if t['serviceId'] == 'pdf-holiday'], ['MARPROM:G9-plus-sp-s1-0530'])
        self.assertEqual(files, self.make()[0])   # the same input, the same files

    def test_a_trip_gets_the_last_stop_no_page_exists_for(self):
        files, status = self.make()
        feed = self.feed(files)
        rows = [r for r in csv.DictReader(io.StringIO(files['stop_times.txt'])) if r['trip_id'] == 'G9-plus-wd-s1-0500']
        self.assertEqual([(r['stop_id'], r['departure_time'], r['timepoint']) for r in rows][-2:], [('30', '05:10:00', '1'), ('40', '05:15:00', '0')])   # read from the pages; from the published run time
        self.assertEqual([s['stopId'] for s in feed['trips']['MARPROM:G9-plus-wd-s2-0550']['stops']], ['MARPROM:20', 'MARPROM:30', 'MARPROM:40'])
        self.assertEqual([s['stopId'] for s in feed['trips']['MARPROM:G9-plus-wd-s1-0600']['stops']], ['MARPROM:10', 'MARPROM:20'])   # ends mid-way, no published trip ends after Beta
        self.assertEqual(status['noLastStop'], [])

    def test_a_lone_departure_at_the_last_page_is_a_trip_to_the_last_stop(self):
        feed = self.feed(self.make(tables={**PDF, '003': {**PDF['003'], 'weekday': ['05:10', '05:55', '23:00']}})[0])
        self.assertEqual([s['stopId'] for s in feed['trips']['MARPROM:G9-plus-wd-s3-2300']['stops']], ['MARPROM:30', 'MARPROM:40'])

    def test_the_last_stop_comes_from_a_published_end_then_by_name_from_any_line(self):
        ends = {'a': {'x': [('8726', 2)], 'y': [('8726', 3), ('8727', 9), ('8727', 9)]}}
        steps = {'a': {'x': [('8726', 2)], 'z': [('8726', 4), ('8727', 8)]}, 'b': {'z': [('8727', 7), ('8726', 6), ('8726', 8)]}}
        names = {'x': 'Tabor - Jadranska', 'y': 'Pekre', 'z': 'Turnerjeva'}
        summer = {'8726'}
        self.assertEqual(marprom.last_call('a', None, ends, steps, names, summer), ('y', 3))            # most trips; the weekday table's run time
        self.assertEqual(marprom.last_call('a', 'TABOR Jadranska', ends, steps, names, summer), ('x', 2))   # the page's name wins
        self.assertEqual(marprom.last_call('b', 'Turnerjeva', ends, steps, names, summer), ('z', 7))    # no published end here: any line's step to that name
        self.assertIsNone(marprom.last_call('b', 'Pekre', ends, steps, names, summer))
        self.assertIsNone(marprom.last_call('b', None, ends, steps, names, summer))                     # mid-way: nothing is made up

    def test_the_summer_tables_are_dropped_and_saturday_and_sunday_keep_their_trips(self):
        files, _ = self.make()
        feed = self.feed(files)
        self.assertNotIn('MARPROM:w1', feed['trips'])
        self.assertNotIn('MARPROM:x1', feed['trips'])
        self.assertEqual([t for t in feed['trips'] if t in ('MARPROM:s1', 'MARPROM:u1')], ['MARPROM:s1', 'MARPROM:u1'])
        self.assertEqual({r for r in feed['calendar']}, {'8727', '8728', 'pdf-weekday', 'pdf-holiday'})

    def test_calendar_weekday_school_holiday_public_holiday_and_saturday(self):
        feed = self.feed(self.make()[0])
        pdf = lambda day: [t for t in self.running(feed, day) if t.startswith('G9')]  # noqa: E731
        self.assertEqual(len(pdf(date(2026, 11, 5))), 3)                     # Thursday
        self.assertEqual(self.running(feed, date(2026, 11, 5)).count('s1'), 0)
        self.assertEqual(self.running(feed, date(2026, 12, 29)), ['G9-plus-sp-s1-0530'])   # a Tuesday in the school holidays: ŠP
        self.assertEqual(self.running(feed, date(2026, 12, 25)), ['u1'])      # a Friday public holiday runs as a Sunday
        self.assertEqual(self.running(feed, date(2026, 11, 7)), ['s1'])       # Saturday
        self.assertEqual(self.running(feed, date(2026, 11, 8)), ['u1'])       # Sunday
        self.assertEqual(self.running(feed, date(2026, 12, 26)), ['u1'])      # a Saturday holiday: Sunday's
        self.assertEqual(self.running(feed, date(2026, 8, 31)), [])           # before the PDFs: nothing of the summer tables
        self.assertEqual(self.running(feed, date(2026, 9, 1))[:1], ['G9-plus-wd-s1-0500'])

    def test_saturday_and_sunday_run_on_to_the_pdfs_end_only_when_the_pdfs_agree_with_them(self):
        files, status = self.make()
        self.assertTrue(status['weekend']['saturday']['agrees'])
        self.assertEqual((status['weekend']['saturday']['equal'], status['weekend']['saturday']['published']), (3, 3))
        self.assertEqual(status['end'], '2027-08-31')
        feed = self.feed(files)
        self.assertEqual(self.running(feed, date(2027, 3, 6)), ['s1'])             # a Saturday after the published end
        self.assertEqual(self.running(feed, date(2027, 2, 8)), ['u1'])             # Prešeren Day, a Monday
        self.assertEqual(self.running(feed, date(2027, 4, 28)), ['G9-plus-sp-s1-0530'])   # ŠP
        self.assertEqual(self.running(feed, date(2027, 5, 1)), ['u1'])             # a Saturday holiday
        different = {**PDF, '001': {**PDF['001'], 'saturday': ['06:30']}}
        files, status = self.make(tables=different)
        self.assertFalse(status['weekend']['saturday']['agrees'])
        self.assertTrue(status['weekend']['sunday']['agrees'])
        self.assertEqual(status['end'], '2026-12-31')   # what the calendar really covers
        feed = self.feed(files)
        self.assertEqual(self.running(feed, date(2026, 12, 19)), ['s1'])
        self.assertEqual(self.running(feed, date(2027, 1, 9)), [])
        self.assertEqual(self.running(feed, date(2027, 1, 10)), ['u1'])
        self.assertEqual(status['weekend']['saturday']['lines']['G9'], {'equal': 2, 'published': 3, 'pdf': 3})

    def test_a_true_duplicate_gets_a_suffix_and_only_it(self):
        twins = {**PDF, '001': {**PDF['001'], 'weekday': ['05:00', '05:00']}, '002': {**PDF['002'], 'weekday': ['05:05', '05:05']},
                 '003': {**PDF['003'], 'weekday': ['05:10', '05:10']}}
        feed = self.feed(self.make(tables=twins)[0])
        self.assertEqual(sorted(t for t in feed['trips'] if t.startswith('MARPROM:G9-plus-wd')), ['MARPROM:G9-plus-wd-s1-0500', 'MARPROM:G9-plus-wd-s1-0500-2'])

    def test_a_trip_whose_stops_no_published_trip_has_takes_a_shape_that_passes_them(self):
        files, status = self.make(tables={**PDF, '002': {**PDF['002'], 'weekday': []}})   # Beta has no weekday departures: Alfa → Gama
        feed = self.feed(files)
        self.assertEqual([s['stopId'] for s in feed['trips']['MARPROM:G9-plus-wd-s1-0500']['stops']], ['MARPROM:10', 'MARPROM:30', 'MARPROM:40'])
        trip = feed['trips']['MARPROM:G9-plus-wd-s1-0500']
        self.assertEqual((trip['shapeId'], trip['headsign']), ('70', 'Alfa - Delta'))   # the published trip with most stops in common
        self.assertEqual(status['shapes'].get('published shape'), 1)

    def test_a_stop_code_the_published_feed_lacks_fails_naming_the_stop(self):
        src, read = fetched()
        docs = pages((0, '001', PDF['001']), (1, '002', PDF['002']), (2, '009', PDF['003']), stops=('Alfa', 'Beta', 'Epsilon', 'Delta'))
        with self.assertRaisesRegex(build.BuildError, r'G9: stop codes not in the published feed: s9 Epsilon'):
            marprom.make(MARPROM, src, self.today, read=lambda data: docs)

    def test_a_missing_page_a_wrong_line_or_no_weekday_trips_fails(self):
        src, _ = fetched()
        with self.assertRaisesRegex(build.BuildError, 'not a readable PDF'):
            marprom.make(MARPROM, src, self.today, read=lambda data: marprom.parse(io.BytesIO(b'<html>404</html>')))
        with self.assertRaisesRegex(build.BuildError, 'is the timetable of line G8, not G9'):
            marprom.make(MARPROM, src, self.today, read=lambda data: pages((0, '001', PDF['001']), line='G8'))
        empty = {code: {**t, 'weekday': [], 'weekday_holiday': []} for code, t in PDF.items()}
        with self.assertRaisesRegex(build.BuildError, 'line G9 has no weekday trips'):
            self.make(tables=empty)

    def test_a_weekday_service_published_again_means_this_feed_is_not_needed(self):
        src, read = fetched()
        data = zip_of({**published(), 'calendar': published()['calendar'] + [{**published()['calendar'][0], 'service_id': '9000', 'end_date': '20270831'}]})
        with self.assertRaisesRegex(build.BuildError, 'runs weekday service 9000 again'):
            marprom.make(MARPROM, marprom.Fetched(data, src.files), self.today, read=read)

    def test_a_failed_build_keeps_the_folder_and_shows_in_health(self):
        files, status = self.make()
        build.write(MARPROM, files, status, self.today)
        row = [r for r in citytt.health(self.today) if r['id'] == 'city-timetables:MARPROM'][0]
        self.assertEqual((row['status'], row['name']), ('live', 'Maribor city buses (Marprom timetables)'))
        self.assertEqual(build.write(MARPROM, files, status, date(2026, 11, 5)), [])   # unchanged
        build.fail(MARPROM, 'G9: stop codes not in the published feed: s9 Epsilon', date(2026, 11, 6))
        self.assertTrue((self.root / 'MARPROM' / 'trips.txt').is_file())
        self.assertEqual(self.feed({p.name: p.read_text(encoding='utf-8') for p in (self.root / 'MARPROM').glob('*.txt')})['trips'].keys(), self.feed(files)['trips'].keys())
        row = [r for r in citytt.health(date(2026, 11, 6)) if r['id'] == 'city-timetables:MARPROM'][0]
        self.assertEqual((row['status'], row['updatedAt']), ('stale', '2026-11-04T00:00:00Z'))
        self.assertEqual(json.loads((self.root / 'MARPROM' / 'status.json').read_text(encoding='utf-8'))['status'], 'failed')

    def test_jesenice_is_untouched(self):
        self.assertEqual([r['id'] for r in citytt.health(self.today)], ['city-timetables:Jesenice', 'city-timetables:Piran', 'city-timetables:Ptuj',
                                                                                  'city-timetables:MARPROM'])


class FetchTests(SimpleTestCase):
    LINK = 'https://www.marprom.si/dokumentacija/prihajajoci-vozni-redi/PVR{line}-{day}_{which}.pdf'

    def setUp(self):
        self.asked: list[str] = []
        self.pages = {}

    def get(self, url):
        self.asked.append(url)
        if url == marprom.GTFS_URL:
            return zip_of(published())
        if url in self.pages:
            return self.pages[url].encode()
        return b'%PDF ' + url.encode()

    def page(self, *links):
        return '<a href="' + '">x</a><a href="'.join(links) + '">x</a><a href="https://www.marprom.si/dokumentacija/prihajajoci-vozni-redi/PVRG9-20260901_plus_001.pdf">stop</a>'

    def test_files_are_found_from_each_lines_page_in_one_pass_a_second_apart(self):
        link = lambda day, which: self.LINK.format(line='G9', day=day, which=which)  # noqa: E731
        self.pages['https://www.marprom.si/koda-linije_nova/g9_nova/'] = self.page(link('20260901', 'plus'), link('20260901', 'minus'),
                                                                                    link('20270901', 'plus'), link('20250901', 'plus'))
        clock = [0.0]
        sleeps = []
        with mock.patch.object(build, '_get', side_effect=self.get), mock.patch.object(marprom.time, 'sleep', side_effect=lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s))), \
                mock.patch.object(marprom.time, 'monotonic', side_effect=lambda: clock[0]):
            got = marprom.fetch(MARPROM, date(2026, 11, 4))
        self.assertEqual(self.asked, [marprom.GTFS_URL, 'https://www.marprom.si/koda-linije_nova/g9_nova/', link('20260901', 'plus'), link('20260901', 'minus')])
        self.assertEqual([(f['line'], f['dir'], f['name']) for f in got.files], [('G9', 'plus', 'PVRG9-20260901_plus.pdf'), ('G9', 'minus', 'PVRG9-20260901_minus.pdf')])
        self.assertEqual(len(sleeps), 3)
        self.assertTrue(all(s >= 1.0 for s in sleeps))   # the first request needs no wait

    def test_a_newer_date_in_the_name_is_taken_once_in_force_and_a_missing_direction_fails(self):
        link = lambda day, which: self.LINK.format(line='G9', day=day, which=which)  # noqa: E731
        url = 'https://www.marprom.si/koda-linije_nova/g9_nova/'
        self.pages[url] = self.page(link('20260901', 'plus'), link('20270101', 'plus'), link('20270101', 'minus'))
        with mock.patch.object(build, '_get', side_effect=self.get), mock.patch.object(marprom.time, 'sleep'):
            got = marprom.fetch(MARPROM, date(2027, 1, 2))
            self.assertEqual([f['name'] for f in got.files], ['PVRG9-20270101_plus.pdf', 'PVRG9-20270101_minus.pdf'])
            got = marprom.fetch(MARPROM, date(2026, 8, 1))   # nothing in force yet: the first to come
            self.assertEqual([f['name'] for f in got.files], ['PVRG9-20260901_plus.pdf', 'PVRG9-20270101_minus.pdf'])
            self.pages[url] = self.page(link('20260901', 'plus'))
            with self.assertRaisesRegex(build.BuildError, 'G9: no "minus" timetable linked'):
                marprom.fetch(MARPROM, date(2026, 11, 4))

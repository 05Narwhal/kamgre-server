"""SŽ's replacement timetables as the PDF reader writes them (sztimetables.py): loading, days, columns, stations."""
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

from prestop_api import sztimetables

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'sztimetables'
LESCE = 'ce3d572ef23d418e1f84217e54e10cc97e211ebdb4a7d1851a1e347bfd64c823'      # 11248 and 11147, 12. - 18. 10.
VINTGAR = 'ef10721ccea254cb5912634c9f58c680a3eb9f91c265e244988c6cba0445889a'    # 11056
GORENJSKA = '88254b697b658e6f46591a51a684c1bf092d8c0e6c71ede73bccf4c4ac93c671'  # 11198, 19. - 23. 10. (some columns)
LOGATEC = '48f1c8e07c3220820c6603adcef0f3bc39dfd6341d60cdfac3a0432fa874806b'    # 10088, unsure


def fixture(sha: str) -> dict:
    return json.loads((FIXTURES / f'{sha}.json').read_text(encoding='utf-8'))


def column(data: dict, label: str, additional: bool = False) -> dict:
    return next(c for t in data['tables'] for c in t['columns'] if c['label'] == label and c['additional'] == additional)


class LoadTests(SimpleTestCase):
    def setUp(self):
        sztimetables.reset()
        self.addCleanup(sztimetables.reset)

    def test_no_directory_means_no_timetables(self):
        with self.settings(PRESTOP_SZ_TIMETABLES_DIR=str(FIXTURES / 'missing')):
            self.assertIsNone(sztimetables.load(now=1000))
        with self.settings(PRESTOP_SZ_TIMETABLES_DIR=''):
            self.assertIsNone(sztimetables.load(now=2000))

    def test_every_notice_finds_its_file_through_the_index(self):
        with self.settings(PRESTOP_SZ_TIMETABLES_DIR=str(FIXTURES)):
            tables = sztimetables.load(now=1000)
        self.assertEqual(tables.file('11248')['sha256'], LESCE)
        self.assertIs(tables.file('11147'), tables.file('11248'))  # two notices link one PDF
        self.assertEqual(tables.file('11056')['tables'][1]['source'], 'mixed')
        self.assertIsNone(tables.file('9471'))
        self.assertIs(sztimetables.current(), tables)

    def test_reloads_at_most_once_a_minute_and_only_when_the_index_changed(self):
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        for f in FIXTURES.glob('*.json'):
            shutil.copy(f, work / f.name)
        with self.settings(PRESTOP_SZ_TIMETABLES_DIR=str(work)):
            first = sztimetables.load(now=1000)
            index = json.loads((work / 'index.json').read_text(encoding='utf-8'))
            del index['notices']['11056']
            (work / 'index.json').write_text(json.dumps(index), encoding='utf-8')
            self.assertIs(sztimetables.load(now=1030), first)        # checked a minute at most
            second = sztimetables.load(now=1061)
            self.assertIsNot(second, first)
            self.assertIsNone(second.file('11056'))
            self.assertIs(second.file('11248'), first.file('11248'))  # an unchanged file is not read again
            self.assertIs(sztimetables.load(now=1200), second)        # index unchanged: same timetables

    def test_a_notice_can_link_several_timetables(self):
        # 11248 links 12. - 18. 10. and a November timetable; index.json lists every file in "files", and each
        # file lists every notice that links it.
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        for f in FIXTURES.glob('*.json'):
            shutil.copy(f, work / f.name)
        november = {**fixture(LESCE), 'sha256': 'f' * 64, 'notices': ['11248', '11251'],
                    'valid': {'from': '2026-10-24', 'to': '2026-11-01', 'dates': None}}
        (work / f'{"f" * 64}.json').write_text(json.dumps(november), encoding='utf-8')
        index = json.loads((work / 'index.json').read_text(encoding='utf-8'))
        index['files'] = sorted(set(index['notices'].values()) | {'f' * 64})
        (work / 'index.json').write_text(json.dumps(index), encoding='utf-8')
        with self.settings(PRESTOP_SZ_TIMETABLES_DIR=str(work)):
            tables = sztimetables.load(now=1000)
        self.assertEqual(tables.file('11248')['sha256'], LESCE)  # the first one, as "notices" says
        self.assertEqual([f['sha256'] for f in tables.files_for('11248')], [LESCE, 'f' * 64])
        self.assertEqual(tables.file_on('11248', date(2026, 10, 14))['sha256'], LESCE)
        self.assertEqual(tables.file_on('11248', date(2026, 10, 26))['sha256'], 'f' * 64)
        self.assertEqual(tables.file_on('11251', date(2026, 10, 26))['sha256'], 'f' * 64)
        self.assertIsNone(tables.file_on('11248', date(2026, 10, 20)))

    def test_a_broken_file_is_left_out(self):
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        shutil.copy(FIXTURES / 'index.json', work / 'index.json')
        shutil.copy(FIXTURES / f'{LESCE}.json', work / f'{LESCE}.json')
        (work / f'{VINTGAR}.json').write_text('{"schema": 1, "tabl', encoding='utf-8')
        with self.settings(PRESTOP_SZ_TIMETABLES_DIR=str(work)), self.assertLogs('prestop_api.sztimetables', 'WARNING'):
            tables = sztimetables.load(now=1000)
        self.assertIsNotNone(tables.file('11248'))
        self.assertIsNone(tables.file('11056'))


class DayTests(SimpleTestCase):
    def test_slovenian_public_holidays(self):
        for day in (date(2026, 1, 2), date(2026, 4, 6), date(2026, 6, 25), date(2026, 12, 25), date(2027, 3, 29), date(2027, 11, 1)):
            self.assertTrue(sztimetables.holiday(day), day)
        for day in (date(2026, 10, 14), date(2026, 4, 7), date(2027, 3, 30)):
            self.assertFalse(sztimetables.holiday(day), day)

    def test_footnotes_decide_the_days(self):
        lesce = fixture(LESCE)
        wed, sat, sun, mon = date(2026, 10, 14), date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)
        self.assertTrue(sztimetables.runs_on(lesce, column(lesce, '2400'), wed))     # 2: workdays
        self.assertFalse(sztimetables.runs_on(lesce, column(lesce, '2400'), sun))
        self.assertFalse(sztimetables.runs_on(lesce, column(lesce, '4290'), wed))    # 3: weekends and holidays
        self.assertTrue(sztimetables.runs_on(lesce, column(lesce, '4290'), sun))
        self.assertFalse(sztimetables.runs_on(lesce, column(lesce, '2426'), sat))    # 6: not on Saturdays
        self.assertTrue(sztimetables.runs_on(lesce, column(lesce, '2426'), sun))
        self.assertTrue(sztimetables.runs_on(lesce, column(lesce, '318/1'), sat))    # no footnote: every valid day
        self.assertFalse(sztimetables.runs_on(lesce, column(lesce, '318/1'), mon))   # outside 12. - 18. 10.

    def test_a_day_the_train_runs_after_all(self):
        gorenjska = fixture(GORENJSKA)
        self.assertFalse(sztimetables.runs_on(gorenjska, column(gorenjska, '2400'), date(2026, 10, 19)))  # 98: train runs
        self.assertTrue(sztimetables.runs_on(gorenjska, column(gorenjska, '2400'), date(2026, 10, 20)))
        self.assertTrue(sztimetables.runs_on(gorenjska, column(gorenjska, '316'), date(2026, 10, 19)))

    def test_a_list_of_days(self):
        data = {**fixture(LESCE), 'valid': {'from': None, 'to': None, 'dates': ['2026-10-10', '2026-10-17']}}
        self.assertTrue(sztimetables.runs_on(data, column(data, '318/1'), date(2026, 10, 17)))
        self.assertFalse(sztimetables.runs_on(data, column(data, '318/1'), date(2026, 10, 16)))


class ColumnTests(SimpleTestCase):
    def test_a_column_with_problems_is_not_used(self):
        logatec = fixture(LOGATEC)
        self.assertIsNotNone(sztimetables.unusable(logatec, column(logatec, '26639')))
        self.assertIsNone(sztimetables.unusable(logatec, column(logatec, '26638')))

    def test_footnotes_the_reader_could_not_read_make_a_column_unusable(self):
        lesce = fixture(LESCE)
        unknown = {**lesce, 'footnotes': {**lesce['footnotes'], '2': {'text': 'Vozi ob polni luni.', 'rule': None}}}
        self.assertIsNotNone(sztimetables.unusable(unknown, column(unknown, '2400')))
        strange = {**lesce, 'footnotes': {**lesce['footnotes'], '2': {'text': '?', 'rule': 'full_moon'}}}
        self.assertIsNotNone(sztimetables.unusable(strange, column(strange, '2400')))
        undefined = {**column(lesce, '2400'), 'footnotes': ['44']}
        self.assertIsNotNone(sztimetables.unusable(lesce, undefined))
        self.assertIsNone(sztimetables.unusable(lesce, column(lesce, '318/2')))

    def test_a_starred_extra_bus_runs_on_workdays(self):
        gorenjska = fixture(GORENJSKA)
        starred = column(gorenjska, '2403', additional=True)
        self.assertEqual((starred.get('mark'), starred['footnotes']), ('*', ['98', '*']))
        self.assertIsNone(sztimetables.unusable(gorenjska, starred))
        self.assertTrue(sztimetables.runs_on(gorenjska, starred, date(2026, 10, 20)))
        self.assertFalse(sztimetables.runs_on(gorenjska, starred, date(2026, 10, 19)))  # its footnote 98 still holds
        self.assertFalse(sztimetables.runs_on(gorenjska, starred, date(2026, 10, 24)))
        # Without its own "*" footnote, the legend line "*Vozi le ob delovnikih" says the same.
        legend = {**starred, 'footnotes': ['98']}
        self.assertIsNone(sztimetables.unusable(gorenjska, legend))
        self.assertFalse(sztimetables.runs_on({**gorenjska, 'valid': {'from': '2026-10-19', 'to': '2026-10-31'}}, legend, date(2026, 10, 24)))
        self.assertIsNotNone(sztimetables.unusable({**gorenjska, 'notes': []}, legend))

    def test_sunday_and_information_footnotes(self):
        data = {**fixture(LESCE), 'footnotes': {'7': {'text': 'Vozi ob nedeljah', 'rule': 'sundays'},
                                                '1': {'text': 'Prevoz se opravi preko mejnega prehoda Sočerga', 'rule': 'info'}}}
        sunday = {**column(data, '318/1'), 'footnotes': ['7']}
        told = {**column(data, '318/1'), 'footnotes': ['1']}
        self.assertTrue(sztimetables.runs_on(data, sunday, date(2026, 10, 18)))
        self.assertFalse(sztimetables.runs_on(data, sunday, date(2026, 10, 17)))
        self.assertTrue(all(sztimetables.runs_on(data, told, date(2026, 10, d)) for d in range(12, 19)))

    def test_train_numbers_of_a_column(self):
        lesce, logatec = fixture(LESCE), fixture(LOGATEC)
        self.assertEqual(sztimetables.numbers(column(lesce, '318/2')), ['318'])
        # Ljubljana - Logatec prints the bus numbers: BUS 26729 is train 2672's.
        self.assertEqual(sztimetables.numbers(column(logatec, '26729'))[:2], ['26729', '2672'])


def stop(id_, name, lat, lon, modes=('rail',)):
    return {'id': id_, 'name': name, 'latitude': lat, 'longitude': lon, 'modes': list(modes)}


# Feed stops around the Gorenjska line (positions as in the feed, rounded).
RAIL = [stop('IJPP:lj', 'Ljubljana', 46.0585, 14.5103), stop('IJPP:siska', 'Ljubljana Šiška', 46.0697, 14.4996),
        stop('IJPP:kranj', 'Kranj', 46.2393, 14.3497), stop('IJPP:lesce', 'Lesce-Bled', 46.3605, 14.1572),
        stop('IJPP:zir', 'Žirovnica', 46.4044, 14.1366), stop('IJPP:sj', 'Slovenski Javornik', 46.4296, 14.0868),
        stop('IJPP:jes', 'Jesenice', 46.4363, 14.0526), stop('IJPP:kocna', 'Kočna', 46.4219, 14.0845),
        stop('IJPP:vintgar', 'Vintgar', 46.4105, 14.0995)]
BUS = [stop('LPP:litostrojska', 'Litostrojska', 46.0771, 14.4889, ['bus']), stop('LPP:litostroj', 'Litostroj', 46.0806, 14.4840, ['bus']),
       stop('IJPP:podkocna', 'Podkočna', 46.4224, 14.0829, ['bus']), stop('IJPP:gobavci', 'Gobavci', 46.2895, 14.2610, ['bus']),
       stop('IJPP:far', 'Gobavci', 46.20, 14.10, ['bus'])]


class StationTests(SimpleTestCase):
    def stations(self, stops=RAIL + BUS, sz_rows=(), overrides=None):
        return sztimetables.Stations(stops, sz_rows=list(sz_rows), replacement_overrides=overrides or {})

    def test_printed_names_are_the_feeds_railway_stations(self):
        lesce = fixture(LESCE)
        calls, why = self.stations().resolve(lesce, column(lesce, '2400'))
        self.assertIsNone(why)
        self.assertEqual([c['stop']['gtfsId'] for c in calls], ['IJPP:lesce', 'IJPP:zir', 'IJPP:sj', 'IJPP:jes'])
        self.assertEqual(calls[0]['stop']['name'], 'Lesce-Bled')
        self.assertEqual((calls[0].get('arr'), calls[0]['dep'], calls[-1]['arr']), (None, '05:40', '05:57'))

    def test_stations_abroad_are_text_only(self):
        lesce = fixture(LESCE)
        stations = self.stations(RAIL + [stop('IJPP:lit', 'Litostroj', 46.0768, 14.4886)])
        calls, _ = stations.resolve(lesce, column(lesce, '318/1'))
        # Ljubljana → Litostroj → Jesenice → Beljak: the bus ends at Jesenice, its last stop in Slovenia, and goes to Villach.
        self.assertEqual([c['stop']['name'] for c in calls], ['Ljubljana', 'Litostroj', 'Jesenice'])
        self.assertEqual((calls[-1]['arr'], calls[-1].get('dep'), calls[-1]['goesTo']), ('08:32', None, 'Beljak / Villach'))
        calls, _ = stations.resolve(lesce, column(lesce, '415'))  # Beljak → Jesenice → ...: starts at Jesenice
        self.assertEqual((calls[0]['stop']['name'], calls[0].get('arr'), calls[0]['dep'], calls[0]['comesFrom']),
                         ('Jesenice', None, '07:00', 'Beljak / Villach'))

    def test_sezana_opcine_keeps_its_call_in_slovenia(self):
        data = {'title': 'Vozni red nadomestnega prevoza: Sežana - Opčine (I) in obratno', 'stops': [], 'tables': []}
        stations = self.stations([stop('IJPP:sezana', 'Sežana', 45.7066, 13.8692)])
        calls, why = stations.resolve(data, {'calls': [{'station': 'SEŽANA', 'dep': '06:10'}, {'station': 'OPČINE', 'arr': '06:30'}]})
        self.assertIsNone(why)
        self.assertEqual([(c['stop']['name'], c.get('dep'), c.get('arr'), c.get('goesTo')) for c in calls], [('Sežana', '06:10', None, 'Opčine')])
        calls, why = stations.resolve(data, {'calls': [{'station': 'OPČINE', 'dep': '07:00'}, {'station': 'SEŽANA', 'arr': '07:20'}]})
        self.assertEqual([(c['stop']['name'], c.get('dep'), c.get('arr'), c.get('comesFrom')) for c in calls], [('Sežana', None, '07:20', 'Opčine')])

    def test_other_stations_abroad_are_left_out(self):
        data = {'title': 'x', 'stops': [], 'tables': []}
        col = {'calls': [{'station': 'KRANJ', 'dep': '05:38'}, {'station': 'LESCE BLED', 'arr': '06:10', 'dep': '06:12'},
                         {'station': 'SPIELFELD', 'arr': '07:00'}]}
        calls, why = self.stations().resolve(data, col)
        self.assertIsNone(why)
        self.assertEqual([c['stop']['name'] for c in calls], ['Kranj', 'Lesce-Bled'])
        self.assertEqual((calls[-1]['arr'], calls[-1].get('dep'), calls[-1]['goesTo']), ('06:10', None, 'Špilje / Spielfeld'))
        # Only stations abroad: no bus in Slovenia.
        calls, why = self.stations().resolve(data, {'calls': [{'station': 'BELJAK', 'dep': '06:00'}, {'station': 'TRST', 'arr': '08:00'}]})
        self.assertIsNone(calls)
        self.assertIn('Slovenia', why)

    def test_a_stop_that_is_no_railway_station(self):
        data = {'title': 'x', 'stops': [{'station': 'LITOSTROJ', 'text': 'AP mestnega prometa Litostrojska (ob Litostrojski - NE obračališče)'}],
                'tables': []}
        col = {'calls': [{'station': 'LJUBLJANA', 'dep': '07:42'}, {'station': 'Litostroj', 'arr': '07:51', 'dep': '07:51'},
                         {'station': 'JESENICE', 'arr': '08:32'}]}
        # SŽ's own list of replacement stops first, at the feed stop beside it.
        listed = [{'route': 'Ljubljana – Kranj – Jesenice', 'station': 'Litostroj', 'lat': 46.07681, 'lon': 14.488618,
                   'label': 'Avtobusno postajališče mestnega prometa Litostrojska', 'source': 'place_pin'},
                  {'route': 'Ljubljana – Kranj – Jesenice', 'station': 'Jesenice', 'lat': 46.4364, 'lon': 14.0550, 'label': '', 'source': 'place_pin'}]
        calls, why = self.stations(sz_rows=listed).resolve(data, col)
        self.assertIsNone(why)
        self.assertEqual(calls[1]['stop']['gtfsId'], 'LPP:litostrojska')
        self.assertEqual((calls[1]['stop']['lat'], calls[1]['stop']['replacementLabel']),
                         (46.07681, 'Avtobusno postajališče mestnega prometa Litostrojska'))
        # Else the bus stop the timetable's stop list names ("Litostrojska", not the "Litostroj" turning loop).
        calls, why = self.stations().resolve(data, col)
        self.assertEqual(calls[1]['stop']['gtfsId'], 'LPP:litostrojska')
        self.assertEqual(calls[1]['stop']['replacementLabel'], 'AP mestnega prometa Litostrojska (ob Litostrojski - NE obračališče)')
        # Else a bus stop of that name near the line.
        calls, why = self.stations().resolve({**data, 'stops': []}, col)
        self.assertEqual(calls[1]['stop']['gtfsId'], 'LPP:litostroj')

    def test_sz_lists_stops_off_the_railway_for_its_own_line(self):
        # Divača - Koper: the bus serves Rodik, Prešnica and Črnotiče, kilometres off the railway, which only buses serve.
        stops = [stop('IJPP:divaca', 'Divača', 45.6830, 13.9706), stop('IJPP:kozina', 'Hrpelje-Kozina', 45.6037, 13.9353),
                 stop('IJPP:koper', 'Koper', 45.5476, 13.7470), stop('IJPP:1129439', 'Rodik', 45.628354, 13.976047, ['bus']),
                 stop('IJPP:1123008', 'Prešnica', 45.570471, 13.941199, ['bus']), stop('IJPP:1123013', 'Črnotiče', 45.551934, 13.891554, ['bus'])]
        line = 'Divača – Koper'
        listed = [{'route': line, 'station': n, 'lat': lat, 'lon': lon, 'label': f'AP {n}', 'source': 'place_pin'}
                  for n, lat, lon in (('Divača', 45.683, 13.9706), ('Rodik', 45.628354, 13.976047), ('Prešnica', 45.571247, 13.938932),
                                      ('Črnotiče', 45.552255, 13.891773), ('Koper', 45.5476, 13.747))]
        listed.append({'route': 'Elsewhere', 'station': 'Rodik', 'lat': 46.5, 'lon': 15.0, 'label': 'not this one', 'source': 'place_pin'})
        col = {'calls': [{'station': 'DIVAČA', 'dep': '05:00'}, {'station': 'Rodik', 'arr': '05:10', 'dep': '05:10'},
                         {'station': 'Hrpelje Kozina', 'arr': '05:15', 'dep': '05:15'}, {'station': 'Prešnica', 'arr': '05:22', 'dep': '05:22'},
                         {'station': 'Črnotiče', 'arr': '05:30', 'dep': '05:30'}, {'station': 'KOPER', 'arr': '05:55'}]}
        calls, why = self.stations(stops, sz_rows=listed).resolve({'title': 'x', 'stops': [], 'tables': []}, col)
        self.assertIsNone(why)
        self.assertEqual([c['stop']['gtfsId'] for c in calls],
                         ['IJPP:divaca', 'IJPP:1129439', 'IJPP:kozina', 'IJPP:1123008', 'IJPP:1123013', 'IJPP:koper'])
        self.assertEqual(calls[1]['stop']['replacementLabel'], 'AP Rodik')

    def test_a_hand_checked_replacement_stop_comes_first(self):
        data = {'title': 'x', 'stops': [], 'tables': []}
        col = {'calls': [{'station': 'KRANJ', 'dep': '05:38'}, {'station': 'Gobavci', 'arr': '05:54', 'dep': '05:54'},
                         {'station': 'LESCE BLED', 'arr': '06:12'}]}
        checked = {'IJPP:gobavci': [{'lat': 46.2899, 'lon': 14.2615, 'label': 'Gobavci, ob cesti'}]}
        calls, _ = self.stations(overrides=checked).resolve(data, col)
        self.assertEqual((calls[1]['stop']['gtfsId'], calls[1]['stop']['lat'], calls[1]['stop']['replacementLabel']),
                         ('IJPP:gobavci', 46.2899, 'Gobavci, ob cesti'))
        calls, _ = self.stations().resolve(data, col)  # the namesake 12 km away is not it
        self.assertEqual(calls[1]['stop']['gtfsId'], 'IJPP:gobavci')

    def test_an_unknown_stop_makes_the_column_unusable(self):
        data = {'title': 'x', 'stops': [], 'tables': []}
        col = {'calls': [{'station': 'KRANJ', 'dep': '05:38'}, {'station': 'Nikjer', 'arr': '05:54', 'dep': '05:54'},
                         {'station': 'LESCE BLED', 'arr': '06:12'}]}
        calls, why = self.stations().resolve(data, col)
        self.assertIsNone(calls)
        self.assertIn('Nikjer', why)

    def test_vintgar_and_kocna_are_stations(self):
        vintgar = fixture(VINTGAR)
        calls, why = self.stations().resolve(vintgar, column(vintgar, '4292'))
        self.assertEqual([c['stop']['gtfsId'] for c in calls], ['IJPP:vintgar', 'IJPP:kocna', 'IJPP:jes'])

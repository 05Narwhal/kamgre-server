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
        self.assertEqual(starred.get('mark'), '*')
        self.assertIsNone(sztimetables.unusable(gorenjska, starred))
        self.assertTrue(sztimetables.runs_on(gorenjska, starred, date(2026, 10, 20)))
        self.assertFalse(sztimetables.runs_on(gorenjska, starred, date(2026, 10, 19)))  # its footnote 98 still holds
        unexplained = {**gorenjska, 'notes': []}
        self.assertIsNotNone(sztimetables.unusable(unexplained, starred))

    def test_train_numbers_of_a_column(self):
        lesce, logatec = fixture(LESCE), fixture(LOGATEC)
        self.assertEqual(sztimetables.numbers(column(lesce, '318/2')), ['318'])
        # Ljubljana - Logatec prints the bus numbers: BUS 26729 is train 2672's.
        self.assertEqual(sztimetables.numbers(column(logatec, '26729'))[:2], ['26729', '2672'])

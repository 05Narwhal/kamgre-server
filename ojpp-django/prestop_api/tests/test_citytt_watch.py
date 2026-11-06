"""Spec 2026-11-05 N15: the cheap look at the hand-kept city timetables: expired, near, changed, unreachable."""
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import supplement
from prestop_api.citytt import CITIES, watch

TODAY = date(2026, 11, 6)
PIRAN, JESENICE, MARPROM = CITIES['Piran'], CITIES['Jesenice'], CITIES['MARPROM']
BASE = 'https://arriva.si/wp-content/uploads/2026/09/'


def piran_status(end='2027-03-31', **extra):
    names = list(PIRAN.files)
    return {'status': 'ok', 'version': 'v1', 'end': end, 'files': [{'file': n, 'url': BASE + n, 'sha256': 'x'} for n in names], **extra}


def page(names):
    return ' '.join(f'<a href="{BASE}{n}">{n}</a>' for n in names)


def unreachable(url):
    raise watch.Unreachable('ConnectTimeout')


class LookTests(SimpleTestCase):
    def look(self, status, names=None, heads=None, seen=None, city=PIRAN):
        names = list(PIRAN.files) if names is None else names
        fetch = lambda url: page(names)
        head = lambda url: (heads or {}).get(url.rsplit('/', 1)[-1], ('Mon', '10'))
        return watch.look(city, status, fetch, head, seen or {})

    def test_the_same_files_are_ok(self):
        r = self.look(piran_status())
        self.assertEqual((r['network'], r['detail']), ('ok', []))
        self.assertEqual(len(r['headers']), 4)

    def test_a_file_the_build_did_not_read_is_a_new_timetable(self):
        r = self.look(piran_status(), names=[*PIRAN.files, 'Linija-1.1.1_NOVO.pdf'])
        self.assertEqual(r['network'], 'new')
        self.assertIn('Linija-1.1.1_NOVO.pdf is new on the page', r['detail'])

    def test_a_known_old_file_still_linked_is_not_new(self):
        r = self.look(piran_status(), names=[*PIRAN.files, PIRAN.stale[0]])
        self.assertEqual(r['network'], 'ok')

    def test_a_file_that_vanished_from_the_page(self):
        r = self.look(piran_status(), names=list(PIRAN.files)[:3])
        self.assertEqual(r['network'], 'new')
        self.assertIn(f'{PIRAN.files[3]} is no longer on the page', r['detail'])

    def test_a_file_replaced_under_the_same_name(self):
        seen = {BASE + n: ['Mon', '10'] for n in PIRAN.files}
        r = self.look(piran_status(), heads={PIRAN.files[1]: ('Tue', '12')}, seen=seen)
        self.assertEqual((r['network'], r['detail']), ('new', [f'{PIRAN.files[1]} changed']))

    def test_no_baseline_no_alarm(self):
        self.assertEqual(self.look(piran_status(), heads={PIRAN.files[1]: ('Tue', '12')})['network'], 'ok')

    def test_a_head_that_gives_nothing_is_no_signal(self):
        r = watch.look(PIRAN, piran_status(), lambda u: page(PIRAN.files), lambda u: None, {})
        self.assertEqual((r['network'], r['headers']), ('ok', {}))

    def test_the_page_down_is_unreachable_not_new(self):
        r = watch.look(PIRAN, piran_status(), unreachable, lambda u: None, {})
        self.assertEqual(r['network'], 'unreachable')

    def test_marprom_has_no_line_pages_to_scan_only_its_published_feed(self):
        status = {'status': 'ok', 'version': 'v1', 'end': '2027-08-31', 'files': [
            {'file': 'gtfs.zip', 'url': 'https://vozniredi.marprom.si/GTFS/gtfs.zip', 'sha256': 'x'},
            {'file': 'PVRG5-20260901_plus.pdf', 'url': 'https://www.marprom.si/dokumentacija/a/PVRG5-20260901_plus.pdf', 'sha256': 'y'}]}
        asked = []
        r = watch.look(MARPROM, status, unreachable, lambda u: asked.append(u) or ('Mon', '1'), {})
        self.assertEqual((r['network'], asked), ('ok', ['https://vozniredi.marprom.si/GTFS/gtfs.zip']))


class SummaryTests(SimpleTestCase):
    def say(self, status, entry=None, today=TODAY, city=PIRAN):
        return watch.summarize(city, status, entry, today)

    def test_ok_far_from_the_end(self):
        r = self.say(piran_status())
        self.assertEqual((r['state'], r['level'], r['daysLeft']), ('ok', 'ok', 145))

    def test_near_the_end(self):
        r = self.say(piran_status(end='2026-11-18'))
        self.assertEqual((r['state'], r['level'], r['text']), ('expires', 'warn', 'Piran expires in 12 days'))

    def test_fourteen_days_counts_fifteen_does_not(self):
        self.assertEqual(self.say(piran_status(end='2026-11-20'))['state'], 'expires')
        self.assertEqual(self.say(piran_status(end='2026-11-21'))['state'], 'ok')

    def test_expired(self):
        self.assertEqual(self.say(piran_status(end='2026-11-03'))['text'], 'Piran timetable ended 3 days ago')

    def test_a_new_timetable_beats_a_near_end(self):
        entry = {'version': 'v1', 'network': 'new', 'detail': ['x is new on the page']}
        r = self.say(piran_status(end='2026-11-18'), entry)
        self.assertEqual((r['state'], r['text'], r['detail']), ('new', 'Piran has a new timetable', ['x is new on the page']))

    def test_expired_beats_new(self):
        entry = {'version': 'v1', 'network': 'new', 'detail': []}
        self.assertEqual(self.say(piran_status(end='2026-11-01'), entry)['state'], 'expired')

    def test_a_folder_uploaded_since_the_check_is_no_longer_new(self):
        entry = {'version': 'old', 'network': 'new', 'detail': ['x']}
        self.assertEqual(self.say(piran_status(), entry)['state'], 'ok')

    def test_a_failed_build(self):
        r = self.say({**piran_status(), 'status': 'failed', 'problems': ['a', 'b']})
        self.assertEqual((r['state'], r['level'], r['detail']), ('failed', 'warn', ['a', 'b']))

    def test_unreachable_is_only_information(self):
        r = self.say(piran_status(), {'version': 'v1', 'network': 'unreachable', 'detail': ['x']})
        self.assertEqual((r['state'], r['level']), ('unreachable', 'info'))

    def test_a_missing_folder(self):
        self.assertEqual(self.say({})['state'], 'unavailable')


class RunTests(SimpleTestCase):
    def folders(self, tmp, **statuses):
        for feed, status in statuses.items():
            (Path(tmp) / feed).mkdir(exist_ok=True)
            (Path(tmp) / feed / 'status.json').write_text(json.dumps(status), encoding='utf-8')

    def run_check(self, tmp, fetch, head, path, cities=(PIRAN, JESENICE)):
        with mock.patch.object(supplement, 'LOCAL_GTFS', Path(tmp)):
            return watch.run(TODAY, fetch=fetch, head=head, path=path, cities=cities)

    def test_two_runs_the_second_sees_a_file_replaced_in_place(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            self.folders(tmp, Piran=piran_status(), Jesenice={'status': 'ok', 'version': 'j', 'end': '2026-11-10', 'files': []})
            path = str(Path(out) / 'check.json')
            same = lambda u: page(PIRAN.files) if 'piran' in u else ''
            first = self.run_check(tmp, same, lambda u: ('Mon', '10'), path)
            self.assertEqual({f['feed']: f['state'] for f in first['feeds']}, {'Piran': 'ok', 'Jesenice': 'expires'})
            second = self.run_check(tmp, same, lambda u: ('Tue', '99'), path)
            self.assertEqual(second['feeds'][0]['state'], 'new')
            saved = json.loads(Path(path).read_text(encoding='utf-8'))
            self.assertEqual(saved['feeds']['Piran']['network'], 'new')

    def test_latest_serves_the_state_and_forgets_a_folder_uploaded_since(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            self.folders(tmp, Piran=piran_status())
            path = str(Path(out) / 'check.json')
            self.run_check(tmp, lambda u: page([*PIRAN.files, 'Linija-1.1.2_NOVO.pdf']), lambda u: ('Mon', '1'), path, cities=(PIRAN,))
            with mock.patch.object(supplement, 'LOCAL_GTFS', Path(tmp)), mock.patch.object(watch, 'state_file', return_value=path),                     mock.patch.object(watch, 'CITIES', {'Piran': PIRAN}):
                watch._memo.clear()
                self.assertEqual(watch.latest(TODAY)['feeds'][0]['state'], 'new')
                self.folders(tmp, Piran=piran_status(version='v2'))
                watch._memo.clear()
                self.assertEqual(watch.latest(TODAY)['feeds'][0]['state'], 'ok')

    def test_no_state_file_no_answer(self):
        with mock.patch.object(watch, 'state_file', return_value=''):
            watch._memo.clear()
            self.assertIsNone(watch.latest(TODAY))

    def test_lines_are_the_urgent_feeds_new_first(self):
        result = {'feeds': [
            {'state': 'expires', 'level': 'warn', 'text': 'Piran expires in 12 days', 'detail': []},
            {'state': 'unreachable', 'level': 'info', 'text': 'Ptuj site not reachable', 'detail': []},
            {'state': 'new', 'level': 'warn', 'text': 'Celje has a new timetable', 'detail': ['x is new on the page']}]}
        self.assertEqual(watch.lines(result), ['Celje has a new timetable (x is new on the page)', 'Piran expires in 12 days'])

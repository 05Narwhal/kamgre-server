"""manage.py szpdf_sync: notices → their PDFs → one JSON file per PDF and index.json (prestop_api/szpdf/sync.py)."""
import hashlib
import io
import json
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from prestop_api import szpdf
from prestop_api.szpdf import sync

FIXTURES = Path(__file__).parent / 'fixtures' / 'szpdf'
NOTICES = json.loads((FIXTURES / 'notices-2026-10-14.json').read_text(encoding='utf-8'))
NOW = datetime(2026, 10, 14, 10, 30, tzinfo=timezone.utc)
FETCH_FIELDS = ('notices', 'title', 'url', 'sha256', 'fetched')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NoticeTests(SimpleTestCase):
    def test_every_pdf_link_of_every_notice(self):
        # A record of the feed groups several notices: ID_ovire[i] goes with Naslov[i] and Opis[i].
        found = sync.notice_pdfs(NOTICES)
        self.assertEqual(len(found), 30)
        self.assertTrue({p.stem for p in FIXTURES.glob('*.pdf')} <= set(found))
        self.assertEqual({len(n['urls']) for n in found.values()}, {1})
        self.assertEqual(len({n['urls'][0] for n in found.values()}), 28)
        self.assertEqual(found['11147']['urls'], found['11248']['urls'])
        self.assertNotEqual(found['11251']['urls'], found['11248']['urls'])
        self.assertTrue(found['11248']['title'].startswith('Vozni red nadomestnega prevoza: Lesce Bled - Jesenice'))
        self.assertTrue(found['11058']['title'].startswith('DODATNO: Avtobusni prevoz za vezo'))
        self.assertNotIn('10223', found)

    def test_a_link_is_a_pdf_by_its_ending_in_any_case(self):
        notice = {'ID_ovire': ['1'], 'Naslov': ['X'],
                  'Opis': ['<a href="https://potniski.sz.si/a.PDF">a</a> <a href="https://potniski.sz.si/b.html">b</a> '
                           '<a href="https://potniski.sz.si/a.PDF">again</a> <a href=\'https://x.si/c.pdf\'>c</a>']}
        self.assertEqual(sync.notice_pdfs([notice])['1']['urls'], ['https://potniski.sz.si/a.PDF', 'https://x.si/c.pdf'])


class FixtureSyncTests(SimpleTestCase):
    """The whole snapshot, read from the fixtures instead of downloaded."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = Path(tempfile.mkdtemp(prefix='szpdf-test-'))
        cls.fetch = staticmethod(sync.fixture_fetcher(NOTICES, FIXTURES))
        started = time.monotonic()
        cls.rows = sync.run(cls.dir, NOTICES, cls.fetch, NOW)
        cls.seconds = time.monotonic() - started
        cls.index = json.loads((cls.dir / 'index.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def test_it_takes_under_a_minute(self):
        self.assertLess(self.seconds, 60)

    def test_index_names_each_notices_first_pdf_and_every_file(self):
        self.assertEqual(self.index['schema'], 1)
        self.assertEqual(self.index['updated'], NOW.isoformat())
        self.assertEqual(len(self.index['notices']), 25)
        self.assertEqual(self.index['notices'].pop('11147'), sha(FIXTURES / '11248.pdf'))
        for pid, digest in self.index['notices'].items():
            self.assertEqual(digest, sha(FIXTURES / f'{pid}.pdf'), pid)
        self.assertEqual(sorted(self.index['files']), sorted({sha(p) for p in FIXTURES.glob('*.pdf')}))
        for digest in self.index['files']:
            self.assertEqual(sha(self.dir / f'{digest}.pdf'), digest)

    def test_each_file_is_its_golden_plus_where_it_came_from(self):
        for pid in (p.stem for p in FIXTURES.glob('*.pdf')):
            with self.subTest(pid=pid):
                doc = json.loads((self.dir / f'{self.index["notices"][pid]}.json').read_text(encoding='utf-8'))
                golden = json.loads((FIXTURES / f'{pid}.expected.json').read_text(encoding='utf-8'))
                self.assertEqual({k: v for k, v in doc.items() if k not in FETCH_FIELDS}, golden)
                self.assertEqual(doc['sha256'], self.index['notices'][pid])
                self.assertEqual(doc['fetched'], NOW.isoformat())
                self.assertIn(pid, doc['notices'])

    def test_a_pdf_two_notices_link_lists_both_with_its_own_notices_title(self):
        doc = json.loads((self.dir / f'{self.index["notices"]["11248"]}.json').read_text(encoding='utf-8'))
        self.assertEqual(doc['notices'], ['11147', '11248'])
        self.assertEqual(doc['title'], sync.notice_pdfs(NOTICES)['11147']['title'])
        self.assertEqual(doc['url'], sync.notice_pdfs(NOTICES)['11248']['urls'][0])

    def test_no_temporary_files_are_left(self):
        self.assertEqual([p.name for p in self.dir.iterdir() if p.suffix not in ('.json', '.pdf')], [])

    def test_pdfs_missing_from_the_snapshot_are_reported_not_failed(self):
        rows = {r['id']: r for r in self.rows}
        self.assertEqual(len(rows), 30)
        self.assertEqual(sorted(i for i, r in rows.items() if r['status'] == 'ok'),
                         sorted([p.stem for p in FIXTURES.glob('*.pdf')] + ['11147']))
        absent = {i: r for i, r in rows.items() if r['status'] != 'ok'}
        self.assertEqual(sorted(absent), ['11214', '11216', '11220', '11224', '11251'])
        self.assertTrue(all(r['status'] == 'missing' and r['missing'] == 1 and 'not in the snapshot' in r['errors'][0]
                            for r in absent.values()))
        self.assertEqual(rows['11248']['columns'], 63)

    def test_nothing_is_parsed_or_rewritten_when_nothing_changed(self):
        before = {p.name: p.stat().st_mtime_ns for p in self.dir.iterdir()}
        with mock.patch.object(szpdf, 'parse', side_effect=AssertionError('parsed again')):
            sync.run(self.dir, NOTICES, self.fetch, NOW + timedelta(minutes=30))
        after = {p.name: p.stat().st_mtime_ns for p in self.dir.iterdir()}
        self.assertEqual({k: v for k, v in after.items() if k != 'state.json'},
                         {k: v for k, v in before.items() if k != 'state.json'})


class LifecycleTests(SimpleTestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='szpdf-test-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.notices = [n for n in NOTICES if n['ID_ovire'][0] in ('11125', '11157')]
        self.fetch = sync.fixture_fetcher(self.notices, FIXTURES)

    def test_a_new_parser_version_parses_every_cached_pdf_again(self):
        sync.run(self.dir, self.notices, self.fetch, NOW)
        with mock.patch.object(szpdf, 'PARSER', szpdf.PARSER + 1), \
                mock.patch.object(szpdf, 'parse', wraps=szpdf.parse) as parse:
            sync.run(self.dir, self.notices, self.fetch, NOW + timedelta(hours=1))
        self.assertEqual(parse.call_count, 2)
        digest = sha(FIXTURES / '11125.pdf')
        self.assertEqual(json.loads((self.dir / f'{digest}.json').read_text(encoding='utf-8'))['parser'], szpdf.PARSER + 1)

    def test_files_of_a_notice_gone_for_seven_days_are_pruned(self):
        sync.run(self.dir, self.notices, self.fetch, NOW)
        gone = sha(FIXTURES / '11125.pdf')
        kept = [n for n in self.notices if n['ID_ovire'][0] == '11157']
        sync.run(self.dir, kept, self.fetch, NOW + timedelta(days=1))
        index = json.loads((self.dir / 'index.json').read_text(encoding='utf-8'))
        self.assertEqual(list(index['notices']), ['11157'])
        self.assertNotIn(gone, index['files'])
        self.assertTrue((self.dir / f'{gone}.pdf').exists())
        sync.run(self.dir, kept, self.fetch, NOW + timedelta(days=8, minutes=1))
        self.assertFalse((self.dir / f'{gone}.pdf').exists())
        self.assertFalse((self.dir / f'{gone}.json').exists())
        self.assertTrue((self.dir / f'{sha(FIXTURES / "11157.pdf")}.json').exists())

    def test_a_pdf_that_cannot_be_parsed_is_a_failed_file(self):
        with mock.patch.object(szpdf, 'parse', side_effect=ValueError('broken')):
            rows = sync.run(self.dir, self.notices, self.fetch, NOW)
        self.assertEqual({r['status'] for r in rows}, {'failed'})
        doc = json.loads((self.dir / f'{sha(FIXTURES / "11125.pdf")}.json').read_text(encoding='utf-8'))
        self.assertEqual((doc['status'], doc['tables']), ('failed', []))
        self.assertIn('broken', doc['problems'][0])


class FakeResponse:
    def __init__(self, body: bytes, status=200, headers=None):
        self.raw = io.BytesIO(body)
        self.status_code = status
        self.headers = headers or {}

    def iter_content(self, size):
        while chunk := self.raw.read(size):
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DownloadTests(SimpleTestCase):
    def test_a_pdf_is_downloaded_with_our_user_agent_and_a_timeout(self):
        body = (FIXTURES / '11125.pdf').read_bytes()
        with mock.patch.object(sync.requests, 'get', return_value=FakeResponse(body, headers={'ETag': '"x"'})) as get:
            got = sync.download('https://potniski.sz.si/a.pdf', None)
        self.assertEqual((got.body, got.etag), (body, '"x"'))
        kwargs = get.call_args.kwargs
        self.assertIn('KamGre', kwargs['headers']['User-Agent'])
        self.assertEqual(kwargs['timeout'], 30)

    def test_too_big_or_not_a_pdf_is_refused(self):
        with mock.patch.object(sync.requests, 'get', return_value=FakeResponse(b'%PDF' + b'0' * (15 * 1024 * 1024))):
            with self.assertRaisesRegex(sync.SyncError, 'larger than'):
                sync.download('https://potniski.sz.si/a.pdf', None)
        with mock.patch.object(sync.requests, 'get', return_value=FakeResponse(b'<html>bot check</html>')):
            with self.assertRaisesRegex(sync.SyncError, 'not a PDF'):
                sync.download('https://potniski.sz.si/a.pdf', None)

    def test_an_unchanged_pdf_is_not_downloaded_again(self):
        with mock.patch.object(sync.requests, 'get', return_value=FakeResponse(b'', status=304)) as get:
            got = sync.download('https://potniski.sz.si/a.pdf', {'etag': '"x"', 'lastModified': 'Tue, 13 Oct 2026 08:00:00 GMT'})
        self.assertIsNone(got.body)
        self.assertEqual(get.call_args.kwargs['headers']['If-None-Match'], '"x"')

    def test_a_known_url_is_checked_again_after_a_day_only(self):
        d = Path(tempfile.mkdtemp(prefix='szpdf-test-'))
        self.addCleanup(shutil.rmtree, d, True)
        notices = [n for n in NOTICES if n['ID_ovire'][0] == '11125']
        fetch = mock.Mock(wraps=sync.fixture_fetcher(notices, FIXTURES))
        sync.run(d, notices, fetch, NOW)
        sync.run(d, notices, fetch, NOW + timedelta(hours=23))
        self.assertEqual(fetch.call_count, 1)
        sync.run(d, notices, fetch, NOW + timedelta(hours=25))
        self.assertEqual(fetch.call_count, 2)


class CommandTests(SimpleTestCase):
    def test_report_on_the_snapshot(self):
        d = tempfile.mkdtemp(prefix='szpdf-test-')
        self.addCleanup(shutil.rmtree, d, True)
        out = io.StringIO()
        with override_settings(PRESTOP_SZ_TIMETABLES_DIR=d):
            call_command('szpdf_sync', '--from', str(FIXTURES / 'notices-2026-10-14.json'), '--fixtures', str(FIXTURES),
                         '--report', stdout=out)
        rows = [l.split() for l in out.getvalue().splitlines() if l.split()[1:2] in (['ok'], ['unsure'], ['failed'], ['missing'])]
        self.assertEqual([r[1] for r in rows].count('ok'), 25, out.getvalue())
        self.assertEqual(len([r for r in rows if r[1] == 'missing' and 'snapshot)' in r]), 5, out.getvalue())
        self.assertTrue((Path(d) / 'index.json').exists())

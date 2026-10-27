"""zamudil.si client (spec 2026-10-27 G1): fixtures parse, a failing or changed API keeps the last copy."""
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import upstream, zamudil
from prestop_api.upstream import UpstreamError

FIXTURES = Path(__file__).parent / 'fixtures' / 'sz'
DAY = date(2026, 10, 27)
NOON = datetime(2026, 10, 27, 12, 0, tzinfo=zamudil.LOCAL).timestamp()
NIGHT = datetime(2026, 10, 27, 2, 0, tzinfo=zamudil.LOCAL).timestamp()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f'zamudil-{name}.json').read_text(encoding='utf-8'))


class ZamudilCase(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.settings_ = override_settings(PRESTOP_ZAMUDIL_URL=['https://zamudil.example/api'], PRESTOP_ZAMUDIL_DIR=self.dir.name)
        self.settings_.enable()
        self.today = mock.patch.object(zamudil, 'today', return_value=DAY)
        self.today.start()
        self.forget()

    def tearDown(self):
        self.today.stop()
        self.settings_.disable()
        self.dir.cleanup()
        self.forget()

    def forget(self):
        zamudil._copies.clear()
        zamudil._looked.clear()
        zamudil._records.update(version=None, value=None)
        zamudil.urls.good = None

    def answer(self, by_path: dict):
        """upstream.get_json answering each endpoint with by_path[path] (an exception is raised)."""
        asked = []

        def get(url, params=None, **kwargs):
            path = url.split('/api', 1)[1]
            asked.append((path, (params or {}).get('date')))
            value = by_path[path]
            if isinstance(value, Exception):
                raise value
            return value
        return mock.patch.object(upstream, 'get_json', side_effect=get), asked


class FixtureTests(ZamudilCase):
    def test_fixtures_parse(self):
        patch, asked = self.answer({'/notices': fixture('notices'), '/rollingstock/assignments': fixture('assignments'),
                                    '/map/maintenance': fixture('maintenance')})
        with patch:
            notices = zamudil.fetch(zamudil.NOTICES, DAY, NOON)
            classes = zamudil.fetch(zamudil.CLASSES, DAY, NOON)
            works = zamudil.fetch(zamudil.WORKS, None, NOON)
        self.assertEqual(len(notices['data']['notices']), 21)
        self.assertEqual(len(classes['data']['rollingStock']), 9)
        self.assertEqual(len(works['data']['works']), 7)
        self.assertEqual(asked, [('/notices', '2026-10-27'), ('/rollingstock/assignments', '2026-10-27'), ('/map/maintenance', None)])
        self.assertIsNone(notices['error'])

    def test_user_agent_names_the_app(self):
        self.assertIn('KamGre', upstream.session().headers['User-Agent'])


class KeepsTheLastCopyTests(ZamudilCase):
    def fetched(self):
        patch, _ = self.answer({'/notices': fixture('notices')})
        with patch:
            zamudil.fetch(zamudil.NOTICES, DAY, NOON)

    def test_failures_keep_the_previous_data_and_mark_it_stale(self):
        for broken in (UpstreamError('HTTP 500'), UpstreamError('returned invalid JSON'), {}, {'notices': 'x'},
                       {'notices': []}, {'notices': [{'summary': ''}]}, {'serviceDate': '2026-10-28', 'notices': []}):
            with self.subTest(broken=broken):
                self.forget()
                self.fetched()
                patch, _ = self.answer({'/notices': broken})
                with patch:
                    kept = zamudil.fetch(zamudil.NOTICES, DAY, NOON + 700)
                self.assertEqual(len(kept['data']['notices']), 21)
                self.assertTrue(kept['error'])
                self.assertEqual(kept['fetchedAt'], NOON)
                [health] = [s for s in zamudil.health(NOON + 700) if s['id'] == 'sz:zamudil-notices']
                self.assertEqual(health['status'], 'stale')
                self.assertEqual(health['since'], '2026-10-27T11:00:00Z')

    def test_a_restart_reads_the_disk_copy(self):
        self.fetched()
        self.forget()  # a new process
        found = zamudil.copy(zamudil.NOTICES, DAY, NOON + 5)
        self.assertEqual(len(found['data']['notices']), 21)
        self.assertEqual([d for d, _ in zamudil.copies(zamudil.NOTICES, NOON + 5)], [DAY])

    def test_another_process_copy_is_not_asked_again(self):
        self.fetched()
        self.forget()
        patch, asked = self.answer({'/notices': UpstreamError('must not be asked')})
        with patch:
            self.assertFalse(zamudil._due(zamudil.NOTICES, DAY, 600, NOON + 300))
        self.assertEqual(asked, [])

    def test_first_failure_without_a_copy(self):
        patch, _ = self.answer({'/notices': UpstreamError('HTTP 500')})
        with patch:
            self.assertIsNone(zamudil.fetch(zamudil.NOTICES, DAY, NOON))
        self.assertEqual(zamudil.copies(zamudil.NOTICES, NOON), [])
        self.assertFalse(zamudil._due(zamudil.NOTICES, DAY, 600, NOON + 60))  # retried after RETRY, not every tick
        self.assertTrue(zamudil._due(zamudil.NOTICES, DAY, 600, NOON + zamudil.RETRY))
        [health] = [s for s in zamudil.health(NOON) if s['id'] == 'sz:zamudil-notices']
        self.assertEqual(health['status'], 'unavailable')

    def test_past_dates_are_pruned(self):
        zamudil._write(Path(self.dir.name) / 'notices-2026-10-26.json', {'data': {'notices': []}, 'fetchedAt': 1, 'checkedAt': 1})
        self.fetched()
        zamudil.prune()
        self.assertEqual(sorted(p.name for p in Path(self.dir.name).glob('*.json')), ['notices-2026-10-27.json'])

    def test_off_without_urls(self):
        with override_settings(PRESTOP_ZAMUDIL_URL=[]):
            self.assertIsNone(zamudil.fetch(zamudil.NOTICES, DAY, NOON))
            self.assertEqual(zamudil.poll(NOON), 0)
            self.assertEqual(zamudil.health(NOON), [])
            self.assertIsNone(zamudil.notice_records())


class ScheduleTests(ZamudilCase):
    def test_a_day_of_polls_stays_light(self):
        """Every copy the schedule keeps, asked for whenever due, over one day: about 200 requests."""
        patch, asked = self.answer({'/notices': fixture('notices') | {'serviceDate': None}, '/rollingstock/assignments': fixture('assignments') | {'serviceDate': None},
                                    '/map/maintenance': fixture('maintenance')})
        start = datetime(2026, 10, 27, 0, 0, tzinfo=zamudil.LOCAL).timestamp()
        with patch:
            for minute in range(0, 24 * 60, 1):
                zamudil.poll(start + minute * 60)
        per = {}
        for path, _ in asked:
            per[path] = per.get(path, 0) + 1
        self.assertLessEqual(len(asked), 230, per)
        self.assertGreaterEqual(per['/notices'], 140)  # today every 10 min by day, tomorrow hourly, the others nightly
        self.assertEqual({d for p, d in asked if p == '/notices'}, {f'2026-{m}' for m in ['10-27', '10-28', '10-29', '10-30', '10-31', '11-01', '11-02',
                                                                                         '11-03', '11-04', '11-05', '11-06', '11-07', '11-08', '11-09']})

    def test_intervals(self):
        self.assertEqual(zamudil.interval(zamudil.NOTICES, DAY, DAY, NOON), 600)
        self.assertEqual(zamudil.interval(zamudil.NOTICES, DAY, DAY, NIGHT), 3600)
        self.assertEqual(zamudil.interval(zamudil.NOTICES, date(2026, 10, 28), DAY, NOON), 3600)
        self.assertIsNone(zamudil.interval(zamudil.NOTICES, date(2026, 10, 30), DAY, NOON))  # on demand by day
        self.assertIsNotNone(zamudil.interval(zamudil.NOTICES, date(2026, 10, 30), DAY, NIGHT))
        self.assertEqual(zamudil.interval(zamudil.CLASSES, DAY, DAY, NOON), 1800)
        self.assertEqual(zamudil.interval(zamudil.WORKS, None, DAY, NOON), 3600)

    def test_on_demand(self):
        later = date(2026, 11, 3)
        patch, asked = self.answer({'/notices': fixture('notices') | {'serviceDate': '2026-11-03'}})
        with patch:
            self.assertTrue(zamudil.ensure(zamudil.NOTICES, later, now=NOON))
            self.assertFalse(zamudil.ensure(zamudil.NOTICES, later, now=NOON + 3600))  # younger than 6 h
            self.assertTrue(zamudil.ensure(zamudil.NOTICES, later, now=NOON + 7 * 3600))
            self.assertFalse(zamudil.ensure(zamudil.NOTICES, date(2026, 11, 20), now=NOON))  # past the 14 days
        self.assertEqual(asked, [('/notices', '2026-11-03')] * 2)

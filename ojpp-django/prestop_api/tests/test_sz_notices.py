"""F4: SŽ's closure notices survive an outage of every notices URL and a restart (the last good ones are kept on disk),
and SŽ's own RSS keeps the app from going silent meanwhile (text alerts, no replacement buses)."""
import json
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import closures, operator_notices, sources, sztimetables
from prestop_api.upstream import Snapshot, UpstreamError

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
NOTICES = json.loads((FIXTURES / 'szpdf' / 'notices-2026-10-14.json').read_text(encoding='utf-8'))
RSS = (FIXTURES / 'sz' / 'feed-2026-10-26.xml').read_bytes()
EVENING = datetime(2026, 10, 26, 20, 0, tzinfo=closures.LOCAL).timestamp()


def ids(raw):
    return [str(n) for item in raw for n in item.get('ID_ovire') or []]


class SavedNoticesTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.file = str(Path(self.dir.name) / 'sz-notices.json')

    def test_a_notice_is_dropped_once_its_last_day_has_passed(self):
        # one record groups three notices: until 25 Oct, until 18 Oct, until 1 Nov
        record = next(r for r in NOTICES if len(r.get('ID_ovire') or []) == 3)
        [kept] = closures.current_notices([record], date(2026, 10, 27))
        self.assertEqual((kept['ID_ovire'], kept['Cas']), ([record['ID_ovire'][2]], ['24.10.2026-01.11.2026']))
        self.assertEqual(kept['Lokacija'], record['Lokacija'])  # fields that aren't per notice stay as they were
        self.assertEqual(closures.current_notices([record], date(2026, 11, 2)), [])

    def test_saved_atomically_and_read_back(self):
        with self.settings(PRESTOP_SZ_NOTICES_FILE=self.file):
            closures.save_notices(NOTICES, now=EVENING)
            saved, at = closures.saved_notices(date(2026, 10, 14))
        self.assertEqual((len(saved), at), (len(NOTICES), EVENING))
        self.assertEqual([p.name for p in Path(self.dir.name).iterdir()], ['sz-notices.json'])  # no .tmp left behind
        with self.settings(PRESTOP_SZ_NOTICES_FILE=str(Path(self.dir.name) / 'none.json')):
            self.assertEqual(closures.saved_notices(), ([], None))

    def test_a_restart_while_every_notices_url_fails_keeps_yesterdays_closures(self):
        running = closures.current_notices(NOTICES, date(2026, 10, 27))
        number = next(n for n in ids(running) if n in ids(NOTICES))
        tables = sztimetables.Timetables({number: 'sha'}, {'sha': {'status': 'ok', 'notices': [number]}})
        real = closures.saved_notices
        with self.settings(PRESTOP_SZ_NOTICES_FILE=self.file, PRESTOP_SZ_NOTICES_URL=['http://dead.example/ovire', 'http://gone.example/ovire']):
            closures.save_notices(NOTICES, now=EVENING)  # yesterday, while a notices URL still worked
            # the server restarts the next day: nothing in memory, every URL fails
            with mock.patch.dict(closures._notices, raw=None, since=None, saved=None), \
                    mock.patch.object(closures.points, '_snap', None), mock.patch.object(closures.points, '_retry_at', 0), \
                    mock.patch.object(closures.points, '_last_error', ''), \
                    mock.patch.object(sources.alerts_raw, '_snap', Snapshot([], time.time())), \
                    mock.patch.object(closures, 'saved_notices', lambda today=None: real(date(2026, 10, 27))), \
                    mock.patch('prestop_api.upstream.get_json', side_effect=UpstreamError('HTTP 500')), \
                    self.assertLogs('prestop_api.closures', 'WARNING'):
                with self.assertRaises(UpstreamError):
                    closures.points.get()
                self.assertEqual(ids(closures._notices['raw']), ids(running))
                snap = closures.points.peek()
                self.assertTrue(snap and snap.error and snap.age >= closures.points.ttl)  # retried, not trusted for 6 h
                health = closures.notices_source()
                self.assertEqual((health['status'], health['since']), ('stale', '2026-10-26T19:00:00Z'))
                # the notice's alert, which runs its replacement timetable's buses, is back
                alerts = closures.sz_notice_alerts(closures._notices['raw'], [], tables)
                self.assertEqual([a['id'] for a in alerts], [closures.notice_alert_id(number)])

    def test_a_working_url_is_saved_and_wins_over_the_file(self):
        with self.settings(PRESTOP_SZ_NOTICES_FILE=self.file, PRESTOP_SZ_NOTICES_URL=['http://ok.example/ovire']), \
                mock.patch.dict(closures._notices, raw=None, since=None, saved=None), \
                mock.patch('prestop_api.upstream.get_json', return_value=NOTICES[:2]):
            closures._load_points()
            self.assertEqual((ids(closures._notices['raw']), closures._notices['saved']), (ids(NOTICES[:2]), None))
        self.assertEqual(ids(json.loads(Path(self.file).read_text(encoding='utf-8'))['notices']), ids(NOTICES[:2]))


class Response:
    def __init__(self, status, body=b'', headers=None):
        self.status_code, self.headers = status, headers or {}
        self.raw = mock.Mock(read=lambda n, decode_content=True: body[:n])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SzRssTests(SimpleTestCase):
    def test_passenger_notices_become_text_alerts_for_the_days_they_name(self):
        items = operator_notices.rss_items(RSS)
        self.assertEqual(len(items), 10)
        alerts = operator_notices.sz_news_alerts(items, EVENING)
        titles = [a['title'] for a in alerts]
        self.assertTrue(any(t.startswith('Spremenjena dostopna pot do peronov') for t in titles))  # from 22 Oct, two weeks
        self.assertFalse(any('Zalaegerszeg' in t for t in titles))  # 16-22 Oct: over
        self.assertFalse(any('solidarnosti' in t for t in titles))  # news, not a passenger notice
        a = alerts[0]
        self.assertEqual((a['operatorId'], a['source'], a['routeIds']), ('IJPP:1161', 'operator-site', []))
        self.assertTrue(a['sourceUrl'].startswith('https://potniski.sz.si/') and a['id'].startswith('sz-news:'))

    def test_a_feed_with_entities_is_refused(self):
        with self.assertRaises(ValueError):
            operator_notices.rss_items(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel></channel></rss>')

    def test_unchanged_since_the_last_read_keeps_the_items(self):
        got = []

        def get(url, headers, **kwargs):
            got.append(headers)
            return Response(200, RSS, {'ETag': 'W/"1"', 'Last-Modified': 'Mon, 26 Oct 2026 13:34:59 GMT'}) if len(got) == 1 else Response(304)
        cache = operator_notices.sz_news
        with self.settings(PRESTOP_SZ_NEWS_URL=['https://sz.example/feed/']), mock.patch.object(cache, '_snap', None), \
                mock.patch.dict(operator_notices._rss, url=None, etag=None, modified=None), \
                mock.patch('prestop_api.operator_notices.session', return_value=mock.Mock(get=get)):
            first = operator_notices._load_sz_news()
            cache._snap = Snapshot(first, time.time())
            self.assertIs(operator_notices._load_sz_news(), first)
        self.assertNotIn('If-None-Match', got[0])
        self.assertEqual((got[1]['If-None-Match'], got[1]['If-Modified-Since']), ('W/"1"', 'Mon, 26 Oct 2026 13:34:59 GMT'))

    def test_shown_only_while_the_closure_notices_do_not_reach_us(self):
        items = operator_notices.rss_items(RSS)
        with mock.patch.object(operator_notices.sz_news, '_snap', Snapshot(items, time.time())), \
                mock.patch.object(operator_notices, 'sz_news_alerts', return_value=[{'id': 'sz-news:x'}]):
            with mock.patch.object(closures, 'notices_source', return_value={'status': 'unavailable'}):
                self.assertEqual(operator_notices.sz_alerts(), [{'id': 'sz-news:x'}])
            with mock.patch.object(closures, 'notices_source', return_value={'status': 'live'}):
                self.assertEqual(operator_notices.sz_alerts(), [])

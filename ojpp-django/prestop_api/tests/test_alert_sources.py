"""A3: a failed or empty read of an alert source keeps the last good alerts until they really end, and is logged."""
import time
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import closures, operator_notices as notices, sources
from prestop_api.tests.test_operator_notices import POSTS
from prestop_api.upstream import Cached, Snapshot, UpstreamError


class ArrivaReadTests(SimpleTestCase):
    def setUp(self):
        self.cache = Cached(notices._load_arriva, ttl=0, max_stale=notices.arriva.max_stale)
        self.cache._snap = Snapshot(POSTS, time.time() - 7 * 3600)  # read 7 h ago: past the old 6 h limit
        patcher = mock.patch.object(notices, 'arriva', self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, answer):
        with mock.patch.object(notices, 'get_json', side_effect=answer if isinstance(answer, Exception) else None,
                               return_value=None if isinstance(answer, Exception) else answer):
            return self.cache.get().value

    def test_a_failed_read_keeps_the_arriva_posts(self):
        with self.assertLogs('prestop_api.upstream', 'WARNING'):
            self.assertEqual(self.read(UpstreamError('arriva.si: ReadTimeout')), POSTS)

    def test_an_empty_or_odd_answer_keeps_them_and_is_logged(self):
        for answer in ([], {'code': 'rest_no_route'}):
            self.cache._retry_at = 0
            with self.assertLogs('prestop_api.operator_notices', 'WARNING') as log:
                self.assertEqual(self.read(answer), POSTS)
            self.assertIn('keeping the last ones', log.output[0])

    def test_new_posts_replace_them(self):
        self.assertEqual(self.read(POSTS[:2]), POSTS[:2])


def otp_alert(id_, feed, end=None):
    return {'id': id_, 'feed': feed, 'effectiveStartDate': 0, 'effectiveEndDate': end,
            'alertHeaderTextTranslations': [{'language': 'sl', 'text': id_}]}


class OtpAlertTests(SimpleTestCase):
    def setUp(self):
        sources._vanished.clear()
        self.addCleanup(sources._vanished.clear)

    def test_a_feed_missing_from_one_answer_keeps_its_alerts(self):
        now = 1_800_000_000
        before = Snapshot([otp_alert('a1', 'IJPP'), otp_alert('m1', 'MARPROM'), otp_alert('old', 'MARPROM', end=now - 60)], now - 60)
        with self.assertLogs('prestop_api.sources', 'WARNING') as log:
            kept = sources.keep_vanished([otp_alert('l1', 'LPP'), otp_alert('a1', 'IJPP')], before, now)
        self.assertEqual(sorted(a['id'] for a in kept), ['a1', 'l1', 'm1'])  # the ended one is not brought back
        self.assertIn('no alerts of feed MARPROM', log.output[0])
        # Still missing a while later: kept (logged once); after FEED_GRACE they go.
        fresh = [otp_alert('l1', 'LPP'), otp_alert('a1', 'IJPP')]
        again = sources.keep_vanished(fresh, Snapshot(kept, now), now + 600)
        self.assertEqual(sorted(a['id'] for a in again), ['a1', 'l1', 'm1'])
        gone = sources.keep_vanished(fresh, Snapshot(again, now), now + sources.FEED_GRACE)
        self.assertEqual(sorted(a['id'] for a in gone), ['a1', 'l1'])

    def test_an_empty_answer_keeps_everything(self):
        before = Snapshot([otp_alert('a1', 'IJPP'), otp_alert('l1', 'LPP')], 0)
        with self.assertLogs('prestop_api.sources', 'WARNING'):
            self.assertEqual(len(sources.keep_vanished([], before, 100)), 2)

    def test_a_feed_that_is_back_is_taken_as_it_is(self):
        before = Snapshot([otp_alert('a1', 'IJPP')], 0)
        with self.assertLogs('prestop_api.sources', 'WARNING'):
            sources.keep_vanished([], before, 100)
        self.assertEqual(sources.keep_vanished([otp_alert('a2', 'IJPP')], before, 200), [otp_alert('a2', 'IJPP')])
        self.assertNotIn('IJPP', sources._vanished)


class SzNoticeTests(SimpleTestCase):
    def test_an_empty_notices_feed_keeps_the_last_notices(self):
        last = [{'ID_ovire': ['11049'], 'Opis': ['x']}]
        with mock.patch.dict(closures._notices, raw=last), self.settings(PRESTOP_SZ_NOTICES_URL='https://example/ovire'), \
                mock.patch.object(closures, 'get_json', return_value=[]), self.assertLogs('prestop_api.closures', 'WARNING'):
            with self.assertRaises(UpstreamError):
                closures._load_points()
            self.assertIs(closures._notices['raw'], last)

"""A1: what every board, alert list and vehicle update shares is built once, not per request (sources.py, supplement.py)."""
import time
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import sources, supplement
from prestop_api.upstream import Snapshot


@override_settings(PRESTOP_SHORT_CACHE=True)
class ShortCacheTests(SimpleTestCase):
    def setUp(self):
        sources._built_alerts.clear()
        sources._boards.clear()

    def test_the_alert_list_is_built_once_per_snapshot(self):
        snap = Snapshot([], time.time())
        with mock.patch.object(sources, 'alerts_raw', mock.Mock(get=lambda: snap, peek=lambda: snap)), \
                mock.patch.object(sources, '_build_alerts', side_effect=lambda raw, lang: [{'id': lang}]) as build:
            self.assertEqual(sources.alerts('sl'), [{'id': 'sl'}])
            sources.alerts('sl').append({'id': 'mine'})  # a caller's list is its own
            self.assertEqual(sources.alerts('sl'), [{'id': 'sl'}])
            self.assertEqual(build.call_count, 1)
            sources.alerts('en')
            self.assertEqual(build.call_count, 2)
            # A new OTP snapshot, or an old list, is built again.
            newer = Snapshot([], time.time())
            with mock.patch.object(sources, 'alerts_raw', mock.Mock(get=lambda: newer, peek=lambda: newer)):
                sources.alerts('sl')
            self.assertEqual(build.call_count, 3)
            sources._built_alerts['sl'] = (time.time() - sources.ALERTS_TTL - 1, snap, [])
            sources.alerts('sl')
            self.assertEqual(build.call_count, 4)

    def test_warming_rebuilds_lists_before_they_expire(self):
        snap = Snapshot([], time.time())
        with mock.patch.object(sources, 'alerts_raw', mock.Mock(get=lambda: snap, peek=lambda: snap)), \
                mock.patch.object(sources, '_build_alerts', return_value=[]) as build:
            sources.alerts('sl')
            sources.warm_alerts()
            self.assertEqual(build.call_count, 1)  # still fresh
            sources._built_alerts['sl'] = (time.time() - sources.ALERTS_TTL * 0.7, snap, [])
            sources.warm_alerts()
            self.assertEqual(build.call_count, 2)

    def test_a_board_is_reused_for_a_few_seconds(self):
        with mock.patch.object(sources, '_board', side_effect=lambda *a: [{'id': str(a)}]) as build:
            first = sources.board('LPP:1', 'departure', 1000, 'sl')
            self.assertIs(sources.board('LPP:1', 'departure', 1030, 'sl'), first)
            self.assertEqual(build.call_count, 1)
            sources.board('LPP:1', 'arrival', 1030, 'sl')     # another kind,
            sources.board('LPP:1', 'departure', 1030, 'en')   # language,
            sources.board('LPP:1', 'departure', 1000 + sources.BOARD_REUSE, 'sl')  # or a later start
            sources.board('LPP:1', 'departure', 900, 'sl')    # or an earlier one is another board
            self.assertEqual(build.call_count, 5)
            key = ('LPP:2', 'departure', 'sl')
            sources._boards[key] = (time.time() - sources.BOARD_TTL - 1, 1000, [])
            sources.board('LPP:2', 'departure', 1000, 'sl')
            self.assertEqual(build.call_count, 6)

    @override_settings(PRESTOP_SHORT_CACHE=False)
    def test_off_means_built_every_time(self):
        with mock.patch.object(sources, '_board', return_value=[]) as build:
            sources.board('LPP:1', 'departure', 1000, 'sl')
            sources.board('LPP:1', 'departure', 1000, 'sl')
        self.assertEqual(build.call_count, 2)


class HandKeptFeedTests(SimpleTestCase):
    def test_the_folder_is_read_once_in_a_while(self):
        """owns() runs for every vehicle of every update: it used to list LOCAL_GTFS each time (8 s per update on WSL)."""
        supplement._folder.update(at=float('-inf'))
        with self.settings(PRESTOP_LOCAL_GTFS=True, PRESTOP_KRANJ_GTFS_URL=''), \
                mock.patch.object(supplement, 'LOCAL_GTFS', wraps=supplement.LOCAL_GTFS) as folder:
            for _ in range(50):
                self.assertIn('Sevnica', supplement.feeds())
            self.assertEqual(folder.iterdir.call_count, 1)


class BackoffTests(SimpleTestCase):
    def test_a_source_that_never_loaded_is_not_asked_by_every_request(self):
        """A6: Arriva unreachable from the server was tried on every request (~600 five-second connects an hour)."""
        from prestop_api.upstream import Cached, UpstreamError
        tries = []

        def load():
            tries.append(1)
            raise UpstreamError('ConnectTimeout')
        cache = Cached(load, ttl=900, max_stale=3600)
        for _ in range(5):
            with self.assertRaises(UpstreamError):
                cache.get()
        self.assertEqual(len(tries), 1)
        cache._retry_at = 0  # the back-off is over: asked again
        with self.assertRaises(UpstreamError):
            cache.get()
        self.assertEqual(len(tries), 2)

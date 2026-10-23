import threading
import time
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import mapping, scheduled, sources, stopservice, warm
from prestop_api.upstream import Cached, Snapshot


def slow_cache(value, ttl=120, delay=0.5):
    started = threading.Event()

    def load():
        started.set()
        time.sleep(delay)
        return value
    cache = Cached(load, ttl=ttl, max_stale=3600, revalidate=600)
    return cache, started


class GetNowaitTests(SimpleTestCase):
    def test_a_fresh_value_comes_back_at_once(self):
        cache, started = slow_cache('new')
        cache._snap = Snapshot('fresh', time.time())
        self.assertEqual(cache.get_nowait().value, 'fresh')
        self.assertFalse(started.is_set())

    def test_an_expired_value_comes_back_at_once_and_refreshes_behind(self):
        cache, started = slow_cache('new')
        cache._snap = Snapshot('old', time.time() - 1000)  # past ttl + revalidate: get() would block
        t = time.time()
        self.assertEqual(cache.get_nowait().value, 'old')
        self.assertLess(time.time() - t, 0.1)
        self.assertTrue(started.wait(2))

    def test_with_nothing_loaded_it_starts_the_load_and_returns_none(self):
        cache, started = slow_cache('new')
        t = time.time()
        self.assertIsNone(cache.get_nowait())
        self.assertLess(time.time() - t, 0.1)
        self.assertTrue(started.wait(2))


class WarmerTests(SimpleTestCase):
    def test_refreshes_what_is_about_to_expire_while_the_app_is_in_use(self):
        old = mock.Mock()
        with mock.patch.object(warm, 'caches', return_value=[old]), mock.patch.object(warm, 'plans') as plans,                 mock.patch.object(stopservice, 'warm') as served:
            warm._last_request = time.time()
            warm.tick(time.time())
            old.warm.assert_called_once()
            plans.assert_called_once()
            served.assert_called_once()

    def test_an_idle_server_leaves_the_upstreams_alone(self):
        old = mock.Mock()
        with mock.patch.object(warm, 'caches', return_value=[old]), mock.patch.object(warm, 'plans') as plans:
            warm._last_request = time.time() - warm.ACTIVE - 1
            warm.tick(time.time())
            old.warm.assert_not_called()
            plans.assert_not_called()

    def test_warm_refreshes_only_near_expiry(self):
        loads = []
        cache = Cached(lambda: loads.append(1) or len(loads), ttl=100, max_stale=1000)
        cache._snap = Snapshot(0, time.time() - 10)
        cache.warm()
        self.assertEqual(loads, [])
        cache._snap = Snapshot(0, time.time() - 85)
        cache.warm()
        self.assertEqual(loads, [1])


class BoardTests(SimpleTestCase):
    def test_a_board_never_waits_for_the_days_timetable(self):
        cold, _ = slow_cache([], delay=3)
        entry = {'id': 'x', 'tripId': 'LPP:t1', 'stopId': 'LPP:1', 'mode': 'rail', 'routeName': 'LPV 1', 'scheduledAt': mapping.iso(time.time() + 600), 'destination': 'Kranj'}
        with mock.patch.object(scheduled, 'timetable', cold), \
                mock.patch.object(sources, 'stop_group', return_value=['LPP:1']), \
                mock.patch.object(sources, 'alerts', return_value=[]), \
                mock.patch.object(sources, '_member_board', return_value=[entry]), \
                mock.patch.object(sources, 'stop_names', return_value={}):
            t = time.time()
            self.assertEqual(sources.board('LPP:1', 'departure', int(t), 'sl'), [entry])
            self.assertLess(time.time() - t, 0.5)

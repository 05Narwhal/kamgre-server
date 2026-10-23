"""Spec 2026-10-23 E7: stops with no trip in the next days leave the map and search; their board and links stay."""
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from prestop_api import sources, stopfix, stopservice
from prestop_api.tests.test_kamgre import stop
from prestop_api.tests.test_views import fixed

# Vršič's summer stop (no trip until next season), a merged stop with one served member, a plain served one.
VRSIC = stop('IJPP:1', 'Vršič', 46.4330, 13.7430)
MERGED = {**stop('IJPP:2', 'Kranjska Gora', 46.4850, 13.7850), 'memberIds': ['IJPP:2', 'IJPP:3']}
PLAIN = stop('IJPP:4', 'Kranjska Gora AP', 46.4860, 13.7860)
INDEX = {'list': [VRSIC, MERGED, PLAIN], 'all': [VRSIC, PLAIN], 'routes': {}}
CHECK = {'served': {'IJPP:3', 'IJPP:4'}, 'unserved': {'IJPP:1', 'IJPP:2'}}


class EmptyStopTests(SimpleTestCase):
    def setUp(self):
        for name, value in (('stops', fixed(INDEX)),):
            p = mock.patch.object(sources, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(stopservice, 'served', fixed(CHECK))
        p.start()
        self.addCleanup(p.stop)
        stopservice._memo.update(of=None)

    def test_a_marker_none_of_whose_stops_has_a_trip_leaves_the_map(self):
        self.assertEqual(stopservice.hidden(), {'IJPP:1'})
        self.assertEqual([m['id'] for m in stopservice.markers()], ['IJPP:2', 'IJPP:4'])
        # A link to it still finds it, also by a member's id.
        self.assertEqual([m['id'] for m in stopservice.markers('IJPP:1')], ['IJPP:1'])
        self.assertEqual([m['id'] for m in stopservice.markers('IJPP:3')], ['IJPP:2'])

    def test_stops_the_check_has_not_seen_and_kept_stops_stay(self):
        self.assertEqual(stopservice.empty_markers(INDEX['list'], {'IJPP:2'}, set()), set())  # IJPP:1 not checked: shown
        self.assertEqual(stopservice.empty_markers(INDEX['list'], {'IJPP:1'}, {'IJPP:1'}), set())  # a keep row
        # Prešnica: a railway stop SŽ's replacement buses serve with no OTP trip.
        self.assertEqual(stopservice.empty_markers([stop('IJPP:1123008', 'Prešnica', 45.57, 13.94, modes=('rail',))], {'IJPP:1123008'}, set()), set())
        with mock.patch.object(stopservice, 'served', fixed(None)) as unloaded:
            unloaded._snap = None
            self.assertEqual(stopservice.hidden(), frozenset())

    def test_service_coming_back_brings_the_stop_back_with_the_next_check(self):
        self.assertIn('IJPP:1', stopservice.hidden())
        with mock.patch.object(stopservice, 'served', fixed({'served': {'IJPP:1'}, 'unserved': set()})):
            self.assertEqual(stopservice.hidden(), frozenset())

    def test_search_leaves_it_out(self):
        self.assertEqual([p['id'] for p in sources.search_stations('vrsic', 10)], [])
        self.assertEqual([p['id'] for p in sources.search_stations('kranjska', 10)][:1], ['IJPP:2'])

    def test_the_warmer_starts_a_due_check_in_its_own_thread(self):
        with mock.patch.object(stopservice.served, '_refresh_in_background') as start:
            stopservice.warm()
            start.assert_not_called()  # fresh
        stale = fixed(CHECK, age=stopservice.served.ttl)
        with mock.patch.object(stopservice, 'served', stale), mock.patch.object(stale, '_refresh_in_background') as start:
            stopservice.warm()
            start.assert_called_once()


class KeepOverrideTests(SimpleTestCase):
    def test_keep_rows_are_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'stop_overrides.csv'
            path.write_text('stop_id,type,lat,lon,merge_into,label,note\nIJPP:1,keep,,,,,summer line\n', encoding='utf-8')
            self.assertEqual(stopfix.read_overrides(path)['keep'], {'IJPP:1'})


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class StopsEndpointTests(TestCase):
    def setUp(self):
        for target, name, value in ((sources, 'stops', fixed(INDEX)), (stopservice, 'served', fixed(CHECK))):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        stopservice._memo.update(of=None)

    def test_stops_leave_out_empty_markers_but_find_one_by_id(self):
        items = self.client.get('/api/v1/stops', {'bbox': '13,45,17,47'}).json()['data']['items']
        self.assertEqual([s['id'] for s in items], ['IJPP:2', 'IJPP:4'])
        held = self.client.get('/api/v1/stops', {'bbox': '13,45,17,47', 'stopId': 'IJPP:1'}).json()['data']['items']
        self.assertEqual([s['id'] for s in held], ['IJPP:1'])

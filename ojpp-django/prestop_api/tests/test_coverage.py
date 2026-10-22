"""The coverage audit (spec 2026-10-22 D2): drop notes name the line that left an item out, and the checks tell a
shown run, a copy under another feed's id, and a dropped one apart. D6: the collector's sample of it for /health."""
import io
import json
import threading
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from prestop_api import coverage, mapping, replacement

NOW = 1_761_130_000


def entity(trip_id, vehicle='V1', stamp=NOW - 20, lat=46.05, lon=14.5, route_id=None):
    trip = {'tripId': trip_id} if trip_id else {}
    if route_id:
        trip['routeId'] = route_id
    return {'id': vehicle, 'vehicle': {'trip': trip, 'vehicle': {'id': vehicle}, 'timestamp': stamp,
                                       'position': {'latitude': lat, 'longitude': lon}}}


def stoptime(trip_id, departure, last='Z:9', pickup='SCHEDULED', day=NOW - NOW % 86400):
    return {'serviceDay': day, 'scheduledArrival': departure, 'scheduledDeparture': departure, 'realtimeArrival': departure,
            'realtimeDeparture': departure, 'realtime': False, 'pickupType': pickup, 'dropoffType': 'SCHEDULED',
            'trip': {'gtfsId': trip_id, 'route': {'gtfsId': 'Z:R', 'shortName': '51'},
                     'departureStoptime': {'stop': {'gtfsId': 'Z:0'}, 'scheduledDeparture': departure - 600},
                     'arrivalStoptime': {'stop': {'gtfsId': last}}}}


class NoteTests(SimpleTestCase):
    def test_a_note_names_the_reason_and_the_calling_line(self):
        drops = []
        coverage.note(drops, 'stale', {'id': 'a'}, {'id': 'b'})
        self.assertEqual([d['reason'] for d in drops], ['stale', 'stale'])
        self.assertRegex(drops[0]['at'], r'^test_coverage\.py:\d+$')

    def test_without_a_list_nothing_is_recorded(self):
        coverage.note(None, 'stale', {'id': 'a'})  # the API's own path: no cost, no error

    def test_build_vehicles_notes_every_entity_it_leaves_out(self):
        routes = {'IJPP:R': {'gtfsId': 'IJPP:R', 'shortName': '51', 'mode': 'BUS', 'agencyId': 'IJPP:A'}}
        feed = [entity('IJPP:1', 'V1', route_id='IJPP:R'), entity(None, 'V2'), entity('IJPP:3', 'V3', stamp=NOW - 3600, route_id='IJPP:R'),
                entity('IJPP:4', 'V4'), entity('IJPP:5', 'V1', route_id='IJPP:R')]
        drops = []
        out = mapping.build_vehicles(feed, {}, {}, routes, {}, now=NOW, drops=drops)
        self.assertEqual([v['id'] for v in out], ['IJPP:V1'])
        self.assertEqual({d['item']['id']: d['reason'] for d in drops},
                         {'V2': 'no trip id', 'V3': 'stale', 'V4': 'unknown trip, no line', 'V1': 'same vehicle twice'})
        self.assertTrue(all(d['at'].startswith('mapping.py:') for d in drops))
        self.assertEqual(mapping.build_vehicles(feed, {}, {}, routes, {}, now=NOW), out)

    def test_build_board_notes_runs_that_end_here_or_take_nobody(self):
        drops = []
        rows = mapping.build_board('Z:5', [stoptime('Z:t1', 36000), stoptime('Z:t2', 36060, last='Z:5'), stoptime('Z:t3', 36120, pickup='NONE')],
                                   'departure', [], drops=drops)
        self.assertEqual([r['tripId'] for r in rows], ['Z:t1'])
        self.assertEqual({coverage.trip_of(d['item']): d['reason'] for d in drops}, {'Z:t2': 'ends here', 'Z:t3': 'no picking up'})

    def test_a_feed_bus_a_replacement_timetable_runs_instead_of_is_noted(self):
        plan = {'suppressed': {'IJPP:b1': 'IJPP:timetable-1'}, 'sections': {}, 'synthetic': [], 'by_id': {}}
        row = {'id': 'IJPP:b1@0/1', 'tripId': 'IJPP:b1', 'stopId': 'IJPP:s', 'mode': 'bus', 'replacement': True, 'scheduledAt': mapping.iso(NOW)}
        drops = []
        self.assertEqual(replacement.board_rows([row], 'departure', {}, lambda when: plan, drops=drops), [])
        self.assertEqual([(d['reason'], d['item']['tripId']) for d in drops], [('run by a replacement timetable', 'IJPP:b1')])
        self.assertTrue(drops[0]['at'].startswith('replacement.py:'))


class MapRowsTests(SimpleTestCase):
    def test_shown_dropped_and_missing_on_the_target(self):
        a, b, c = entity('IJPP:1', 'A'), entity('IJPP:2', 'B'), entity(None, 'C')
        drops = [{'reason': 'no trip id', 'at': 'mapping.py:1', 'item': c}]
        rows = coverage.map_rows([a, b, c], drops, kept={'IJPP:A', 'IJPP:B'}, target={'IJPP:A'}, key=mapping.entity_vehicle_id)
        self.assertEqual([(r['feed'], r['status']) for r in rows], [('IJPP', 'shown'), ('IJPP', 'missing on target'), ('?', 'no trip id')])

    def test_a_bus_without_a_trip_the_target_draws_is_shown(self):
        """D4: the target matched its run from the path it followed (mapping.LooseVehicles); the audit's own process
        has followed it for a minute only."""
        loose = entity(None, 'IJPP:1302152')
        drops = [{'reason': 'no trip id, no run fits', 'at': 'mapping.py:1', 'item': loose}]
        rows = coverage.map_rows([loose], drops, kept=set(), target={'IJPP:1302152'}, key=mapping.entity_vehicle_id)
        self.assertEqual([(r['feed'], r['status']) for r in rows], [('IJPP', 'shown')])


class BoardTests(SimpleTestCase):
    ROWS = [{'tripId': 'LPP:9', 'routeName': '51', 'scheduledAt': mapping.iso(NOW + 600), 'id': 'LPP:9@0/3', 'destination': 'Polhov Gradec'}]

    def test_a_run_under_another_feeds_trip_id_counts_as_a_copy(self):
        self.assertEqual(coverage.find_on_board(self.ROWS, 'LPP:9', '51', NOW + 600), 'shown')
        self.assertEqual(coverage.find_on_board(self.ROWS, 'IJPP:77', '51', NOW + 630), 'shown as copy')
        self.assertIsNone(coverage.find_on_board(self.ROWS, 'IJPP:77', '51', NOW + 900))
        self.assertIsNone(coverage.find_on_board(self.ROWS, 'IJPP:77', '6', NOW + 600))
        # D3: a second trip of the same feed is another bus (A6196 twice at 13:10), never the first one's copy
        self.assertIsNone(coverage.find_on_board(self.ROWS, 'LPP:10', '51', NOW + 600))

    def test_the_status_of_a_miss_is_the_first_note_about_it(self):
        drops = [{'reason': 'beyond the board row cap', 'at': 'sources.py:1', 'item': {'tripId': 'IJPP:1'}}]
        want = {'tripId': 'IJPP:1', 'routeName': '6', 'scheduled': NOW}
        self.assertEqual(coverage.board_status(want, [], [], drops), ('beyond the board row cap', 'sources.py:1'))
        self.assertEqual(coverage.board_status(want, None, [], []), ('stop has no board', 'target API'))
        here = [{'tripId': 'IJPP:1', 'routeName': '6', 'scheduledAt': mapping.iso(NOW)}]
        self.assertEqual(coverage.board_status(want, [], here, []), ('missing on target', 'target API'))
        self.assertEqual(coverage.board_status(want, [], [], [])[0], 'not returned by OTP for the board')
        # A loop (N6172 Idrija 18:00 – Idrija 18:24): our board lists its first call, the note is about its last.
        loop_end = [{'reason': 'ends here', 'at': 'mapping.py:420', 'item': {'tripId': 'IJPP:1'}}]
        self.assertEqual(coverage.board_status(want, [], here, loop_end), ('missing on target', 'target API'))

    def test_timetable_departures_keep_runs_in_the_window_that_pick_up_and_go_on(self):
        day = NOW - NOW % 86400
        patterns = [{'pattern': {'route': {'gtfsId': 'Z:R', 'shortName': '51'}},
                     'stoptimes': [stoptime('Z:a', NOW - day + 60), stoptime('Z:b', NOW - day + 120, last='Z:5'),
                                   stoptime('Z:c', NOW - day + 180, pickup='NONE'), stoptime('Z:d', NOW - day + 7200)]}]
        self.assertEqual([r['tripId'] for r in coverage.timetable_departures(patterns, 'Z:5', NOW, NOW + 3600)], ['Z:a'])

    def test_a_run_that_starts_and_ends_at_the_stop_leaves_from_its_first_call(self):
        day = NOW - NOW % 86400
        calls = [stoptime('Z:loop', NOW - day + 60, last='Z:5'), stoptime('Z:loop', NOW - day + 1800, last='Z:5')]
        for st, position in zip(calls, (1, 9)):
            st['stopPosition'] = position
            st['trip']['departureStoptime'].update(stop={'gtfsId': 'Z:5'}, stopPosition=1)
            st['trip']['arrivalStoptime']['stopPosition'] = 9
        patterns = [{'pattern': {'route': {'gtfsId': 'Z:R', 'shortName': '51'}}, 'stoptimes': calls}]
        self.assertEqual([r['at'] for r in coverage.timetable_departures(patterns, 'Z:5', NOW, NOW + 3600)], [NOW + 60])
        self.assertEqual([r['at'] for r in coverage.timetable_departures(patterns, 'Z:5', NOW, NOW + 3600, 'arrival')], [NOW + 1800])

    def test_the_same_run_twice_is_found(self):
        at = mapping.iso(NOW)
        rows = [{'id': 'IJPP:1@1/1', 'tripId': 'IJPP:1', 'routeName': '51', 'scheduledAt': at, 'destination': 'Polhov Gradec'},
                {'id': 'LPP:1@1/1', 'tripId': 'LPP:1', 'routeName': '51', 'scheduledAt': at, 'destination': 'POLHOV GRADEC'},
                {'id': 'IJPP:2@1/1', 'tripId': 'IJPP:2', 'routeName': '51', 'scheduledAt': at, 'destination': 'Ljubljana'},
                {'id': 'LPP:2@1/1', 'tripId': 'LPP:2', 'routeName': '51', 'scheduledAt': at, 'destination': 'Polhov Gradec'}]  # a second bus
        self.assertEqual([(a['tripId'], b['tripId']) for a, b in coverage.duplicates(rows)], [('IJPP:1', 'LPP:1')])

    def test_the_app_pages_on_from_a_full_board_only(self):
        rows = [{'scheduledAt': mapping.iso(NOW + 60 * i), 'effectiveAt': None} for i in range(3)]
        rows[0]['effectiveAt'] = mapping.iso(NOW + 600)  # late: the board's last row by time
        self.assertEqual(coverage.next_page(rows, 3, NOW), NOW + 600)
        self.assertEqual(coverage.next_page(rows, 3, NOW + 600), NOW + 660)  # no later than asked: a minute on
        self.assertIsNone(coverage.next_page(rows, 4, NOW))
        self.assertIsNone(coverage.next_page([], 3, NOW))

    def test_upcoming_stops_of_a_trip_update(self):
        update = {'updates': [{'stopId': 'S1', 'departure': {'time': str(NOW - 60), 'delay': 60}},
                              {'stopId': 'S2', 'scheduleRelationship': 'SKIPPED', 'departure': {'time': NOW + 60}},
                              {'stopId': 'S3', 'arrival': {'time': NOW + 120, 'delay': 120}},
                              {'stopId': 'S4', 'departure': {'time': NOW + 240}},
                              {'stopId': 'S5', 'departure': {'time': NOW + 300}}]}
        self.assertEqual(coverage.upcoming(update, NOW, 3600), [('S3', NOW + 120, 120), ('S4', NOW + 240, None)])

    def test_a_runs_latest_time_at_a_stop(self):
        """D3: the audit's last word on whether a bus had passed when the board was read (Kranj 4 passed 2.5 min early)."""
        update = {'updates': [{'stopId': 'S1', 'departure': {'time': str(NOW - 152)}}, {'stopId': 'S2', 'arrival': {'time': NOW + 60}}]}
        self.assertEqual(coverage.time_at(update, 'S1'), NOW - 152)
        self.assertEqual(coverage.time_at(update, 'S2'), NOW + 60)
        self.assertIsNone(coverage.time_at(update, 'S9'))
        self.assertIsNone(coverage.time_at(None, 'S1'))


class TableTests(SimpleTestCase):
    def test_tally_by_reason_and_feed_with_examples(self):
        rows = [{'feed': 'IJPP', 'status': 'shown', 'at': '', 'example': 'a'},
                {'feed': 'LPP', 'status': 'stale', 'at': 'mapping.py:9', 'example': 'b'},
                {'feed': 'LPP', 'status': 'stale', 'at': 'mapping.py:9', 'example': 'c'}]
        lines = coverage.table('Map', rows)
        self.assertEqual(lines[0], '== Map: 3 checked, 2 not shown')
        self.assertIn('   - stale (mapping.py:9): b, c', lines)


def row(status):
    return {'feed': 'IJPP', 'status': status, 'at': 'mapping.py:444', 'example': 'IJPP:478070@IJPP:1165083'}


class HealthTests(SimpleTestCase):
    """D6: /health's coverage block from the collector's sample. Counts only; a bus left out for a reason that is
    neither by design nor upstream's counts as unexplained, and so does a run listed twice."""

    def test_counts_by_reason_and_what_is_unexplained(self):
        map_rows = [row('shown')] * 3 + [row('stale'), row('no trip id, no run fits'), row('failed contract')]
        boards = [row('shown'), row('shown as copy'), row('shown as its replacement bus'), row(coverage.GONE),
                  row('trip not in OTP (upstream)'), row('not returned by OTP for the board')]
        block = coverage.health_block(map_rows, boards, [row('listed twice')], stops=7, minutes=60, now=NOW)
        self.assertEqual(block['map'], {'inFeed': 6, 'drawn': 3, 'unexplained': 1,
                                        'dropped': {'stale': 1, 'no trip id, no run fits': 1, 'failed contract': 1}})
        self.assertEqual(block['boards'], {'stops': 7, 'minutes': 60, 'checked': 6, 'shown': 3, 'twice': 1, 'unexplained': 2,
                                           'notShown': {coverage.GONE: 1, 'trip not in OTP (upstream)': 1, 'not returned by OTP for the board': 1}})
        self.assertEqual((block['unexplained'], block['sampledAt']), (3, mapping.iso(NOW)))
        self.assertNotIn('IJPP:', json.dumps(block))
        self.assertEqual(coverage.health_line(block), 'map 3/6 drawn · boards 3/6 shown at 7 stops, 60 min · 3 unexplained')

    def test_a_check_left_out_has_no_counts(self):
        block = coverage.health_block([row('shown')], None, None, stops=0, minutes=60, now=NOW)
        self.assertEqual((block['boards'], block['unexplained']), (None, 0))
        self.assertEqual(coverage.health_line(block), 'map 1/1 drawn · 0 unexplained')

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'coverage-test'}})
    def test_the_last_sample_is_kept_for_health(self):
        self.assertIsNone(coverage.latest())
        coverage.save({'unexplained': 0})
        self.assertEqual(coverage.latest(), {'unexplained': 0})

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': 'redis://127.0.0.1:1/0'}})
    def test_health_answers_while_the_cache_is_down(self):
        self.assertIsNone(coverage.latest())

    def test_only_this_servers_own_sample_is_saved(self):
        with self.assertRaises(CommandError):
            call_command('coverage_audit', against='prod', save=True, stdout=io.StringIO())


@override_settings(PRESTOP_SZ_LIVE_URL='')
class MapCheckTests(SimpleTestCase):
    """The audit's map check run soon after another (the collector's samples): the feed cache answers with its old
    copy while it refreshes in the background, and the target serves its vehicles up to a minute old."""
    FEEDS = [[entity('IJPP:1', 'V1')], [entity('IJPP:1', 'V1'), entity('IJPP:2', 'V2')],
             [entity('IJPP:1', 'V1'), entity('IJPP:2', 'V2'), entity('IJPP:3', 'V3')]]

    def run_map(self, target_reads):
        import time as clock
        from prestop_api import sources
        from prestop_api.management.commands.coverage_audit import Command
        from prestop_api.upstream import Cached, Snapshot
        positions = Cached(lambda: self.FEEDS[1], ttl=5, max_stale=120, revalidate=30)
        positions._snap = Snapshot(self.FEEDS[0], clock.time() - 20)  # inside the serve-old-and-refresh window
        positions._refresh_in_background = lambda: None

        def build(drops):
            return [{'id': mapping.entity_vehicle_id(e), 'quality': 'observed', 'latitude': 46.05, 'longitude': 14.5, 'mode': 'bus'}
                    for e in positions.get().value]

        def background_refresh_lands(_seconds):
            positions._snap = Snapshot(self.FEEDS[2], clock.time())
        command = Command(stdout=io.StringIO())
        command.results = {}
        reads = [[{'id': mapping.entity_vehicle_id(e), 'mode': 'bus'} for e in feed] for feed in target_reads]
        with mock.patch.object(sources, 'positions', positions), mock.patch.object(sources, '_load_vehicles', build), \
                mock.patch.object(command, '_get', side_effect=reads + [reads[-1]] * 9) as get, \
                mock.patch('prestop_api.management.commands.coverage_audit.time.sleep', background_refresh_lands):
            command._map()
        return [r['status'] for r in command.results['map']], get.call_count

    def test_rows_come_from_the_feed_the_vehicles_were_built_from(self):
        """A refresh landing while the target was read made the new vehicles look lost ('other')."""
        self.assertEqual(self.run_map([self.FEEDS[0], self.FEEDS[2]]), (['shown', 'shown'], 2))

    def test_the_target_is_read_again_until_it_has_caught_up(self):
        self.assertEqual(self.run_map([self.FEEDS[1]]), (['shown', 'shown'], 1))
        from prestop_api.management.commands.coverage_audit import TARGET_READS
        self.assertEqual(self.run_map([self.FEEDS[0]]), (['shown', 'missing on target'], TARGET_READS))


class SamplerTests(SimpleTestCase):
    def test_samples_on_its_schedule_one_at_a_time(self):
        started, gate = [], threading.Event()

        def run():
            started.append(1)
            gate.wait(5)
        sampler = coverage.Sampler(first=120, every=900, run=run, now=0)
        self.assertFalse(sampler.poll(now=60))  # the API warms up first
        self.assertTrue(sampler.poll(now=120))
        self.assertFalse(sampler.poll(now=1200))  # still running: never two at once
        gate.set()
        sampler.thread.join(5)
        self.assertTrue(sampler.poll(now=1200))
        sampler.thread.join(5)
        self.assertFalse(sampler.poll(now=1300))  # the next one `every` s after this one
        self.assertEqual(len(started), 2)

    def test_a_sample_audits_this_server_and_logs_counts_only(self):
        block = coverage.health_block([row('shown'), row('stale')], [row('shown')], [], stops=7, minutes=60, now=NOW)
        with mock.patch('django.core.management.call_command') as call, mock.patch.object(coverage, 'latest', return_value=block), \
                self.assertLogs('prestop_api.coverage', 'INFO') as logs:
            coverage.run_sample()
        name, options = call.call_args.args[0], call.call_args.kwargs
        self.assertEqual((name, options['against'], options['save'], options['sample']), ('coverage_audit', 'local', True, 0))
        self.assertEqual(options['stops'], coverage.SAMPLE_STOPS)
        self.assertEqual(options['checks'], 'map,live,timetable')
        self.assertEqual(logs.output, ['INFO:prestop_api.coverage:coverage: map 1/2 drawn · boards 1/1 shown at 7 stops, 60 min · 0 unexplained'])

    def test_a_failed_sample_is_logged_not_raised(self):
        with mock.patch('django.core.management.call_command', side_effect=CommandError('does not answer')), \
                self.assertLogs('prestop_api.coverage', 'WARNING'):
            coverage.run_sample()

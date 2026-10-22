"""The coverage audit (spec 2026-10-22 D2): drop notes name the line that left an item out, and the checks tell a
shown run, a copy under another feed's id, and a dropped one apart."""
from django.test import SimpleTestCase

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

    def test_upcoming_stops_of_a_trip_update(self):
        update = {'updates': [{'stopId': 'S1', 'departure': {'time': str(NOW - 60), 'delay': 60}},
                              {'stopId': 'S2', 'scheduleRelationship': 'SKIPPED', 'departure': {'time': NOW + 60}},
                              {'stopId': 'S3', 'arrival': {'time': NOW + 120, 'delay': 120}},
                              {'stopId': 'S4', 'departure': {'time': NOW + 240}},
                              {'stopId': 'S5', 'departure': {'time': NOW + 300}}]}
        self.assertEqual(coverage.upcoming(update, NOW, 3600), [('S3', NOW + 120, 120), ('S4', NOW + 240, None)])


class TableTests(SimpleTestCase):
    def test_tally_by_reason_and_feed_with_examples(self):
        rows = [{'feed': 'IJPP', 'status': 'shown', 'at': '', 'example': 'a'},
                {'feed': 'LPP', 'status': 'stale', 'at': 'mapping.py:9', 'example': 'b'},
                {'feed': 'LPP', 'status': 'stale', 'at': 'mapping.py:9', 'example': 'c'}]
        lines = coverage.table('Map', rows)
        self.assertEqual(lines[0], '== Map: 3 checked, 2 not shown')
        self.assertIn('   - stale (mapping.py:9): b, c', lines)

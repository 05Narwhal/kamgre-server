from unittest import mock

from django.test import SimpleTestCase

from prestop_api import journeys, mapping, sources

NOW = 1791557200  # 2026-10-09 15:26:40 UTC

ROUTES = {
    'LPP:r6': {'gtfsId': 'LPP:r6', 'shortName': '6', 'mode': 'BUS', 'agencyId': 'LPP:lpp'},
    'MARPROM:73': {'gtfsId': 'MARPROM:73', 'shortName': '6', 'mode': 'BUS', 'agencyId': 'MARPROM:3'},
}


def position(trip, vehicle_id, stamp=NOW - 20, **extra):
    return {'id': vehicle_id, 'vehicle': {'trip': {'tripId': trip, 'routeId': extra.pop('route', None)}, 'timestamp': str(stamp),
                                          'position': {'latitude': 46.05, 'longitude': 14.5, 'bearing': 370},
                                          'vehicle': {'id': vehicle_id, 'label': 'LJ 301'}, **extra}}


class VehicleTests(SimpleTestCase):
    def test_vehicle_gets_route_destination_and_delay_at_its_stop(self):
        updates = mapping.trip_update_index([{'tripUpdate': {'trip': {'tripId': 'LPP:t1'}, 'stopTimeUpdate': [
            {'stopSequence': 3, 'stopId': 'LPP:s3', 'arrival': {'delay': 60}},
            {'stopSequence': 4, 'stopId': 'LPP:s4', 'arrival': {'delay': 120}}]}}])
        [v] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1', stopId='LPP:s4')], updates,
                                     {'LPP:t1': {'routeId': 'LPP:r6', 'destination': 'Črnuče'}}, ROUTES, {'LPP:s4': 'Bavarski dvor'}, NOW)
        self.assertEqual((v['routeName'], v['destination'], v['nextStop'], v['delaySeconds']), ('6', 'Črnuče', 'Bavarski dvor', 120))
        self.assertEqual((v['operatorId'], v['mode'], v['bearing'], v['delaySource']), ('LPP:lpp', 'bus', 10.0, 'gtfs-rt'))

    def test_unknown_delay_stays_null(self):
        [v] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1')], {}, {'LPP:t1': {'routeId': 'LPP:r6'}}, ROUTES, {}, NOW)
        self.assertIsNone(v['delaySeconds'])
        self.assertNotIn('delaySource', v)

    def test_stale_positions_are_dropped_and_bare_ids_qualified(self):
        stale = position('LPP:t1', 'LPP:old', stamp=NOW - 3600)
        bare = position('MARPROM:101750', '472', route='MARPROM:73')
        result = mapping.build_vehicles([stale, bare], {}, {}, ROUTES, {}, NOW)
        self.assertEqual([v['id'] for v in result], ['MARPROM:472'])
        self.assertEqual(result[0]['routeId'], 'MARPROM:73')

    def test_a_vehicle_sent_twice_keeps_the_report_naming_its_trip(self):
        """D4: Marprom sends bus 489 twice, first with a bare trip id ("MARPROM:"): the copy with its run wins."""
        bare = position('MARPROM:', '489', route='MARPROM:73')
        named = position('MARPROM:113450', '489', stamp=NOW - 25, route='MARPROM:73')
        [v] = mapping.build_vehicles([bare, named], {}, {'MARPROM:113450': {'routeId': 'MARPROM:73', 'destination': 'Tezno'}}, ROUTES, {}, NOW)
        self.assertEqual((v['tripId'], v['destination']), ('MARPROM:113450', 'Tezno'))
        # A copy with no position or an old report never wins over one that can be drawn.
        stale = position('MARPROM:113450', '489', stamp=NOW - 3600, route='MARPROM:73')
        [v] = mapping.build_vehicles([stale, bare], {}, {}, ROUTES, {}, NOW)
        self.assertEqual(v['updatedAt'], mapping.iso(NOW - 20))

    def test_a_vehicle_named_by_an_older_timetables_trip_id_is_on_otps_run(self):
        """D4: LPP 12D buses report IJPP:479040, which OTP knows as another id; sources._with_old_ids found the run."""
        updates = mapping.trip_update_index([{'tripUpdate': {'trip': {'tripId': 'LPP:old'}, 'stopTimeUpdate': [
            {'stopSequence': 4, 'stopId': 'LPP:s4', 'arrival': {'delay': 400}}]}}])
        updates['LPP:t1'] = {**updates['LPP:old'], 'trip': {'tripId': 'LPP:t1'}, 'oldId': 'LPP:old',
                             'updates': [{'stopSequence': 4, 'stopId': 'LPP:s4', 'arrival': {'delay': 90}}]}
        updates['LPP:old']['runId'] = 'LPP:t1'
        [v] = mapping.build_vehicles([position('LPP:old', 'LPP:bus-1', stopId='LPP:s4')], updates,
                                     {'LPP:t1': {'routeId': 'LPP:r6', 'destination': 'Železna'}}, ROUTES, {}, NOW)
        self.assertEqual((v['tripId'], v['destination'], v['delaySeconds']), ('LPP:t1', 'Železna', 90))

    def test_a_vehicle_breaking_the_contract_is_left_out_alone(self):
        """D4: the app rejected a whole answer for one bad field; the server leaves out only that vehicle."""
        bad = position('MARPROM:101750', 'MARPROM:', route='MARPROM:73')  # no vehicle number after the feed prefix
        drops = []
        result = mapping.build_vehicles([bad, position('LPP:t1', 'LPP:bus-1')], {}, {'LPP:t1': {'routeId': 'LPP:r6'}}, ROUTES, {}, NOW, drops=drops)
        self.assertEqual([v['id'] for v in result], ['LPP:bus-1'])
        self.assertEqual([d['reason'] for d in drops], ['failed contract'])
        self.assertTrue(mapping.fits_contract(result[0]))
        for field, value in [('latitude', float('nan')), ('bearing', 361.0), ('routeId', 'LPP:'), ('mode', 'tram'), ('tripId', 'x'), ('name', None)]:
            self.assertFalse(mapping.fits_contract({**result[0], field: value}), field)


def run(run_id, start, stops=6, step=120, lat=46.20, back=False):
    """A run north along a street, a stop every ~550 m and `step` s (`back`: the same stops south again after)."""
    calls = [(lat + 0.005 * i, 14.36, start + step * i) for i in range(stops)]
    if back:
        calls += [(la, lo, calls[-1][2] + step * (i + 1)) for i, (la, lo, _) in enumerate(reversed(calls[:-1]))]
    return {'id': run_id, 'stops': calls}


def path(r, delay, since, until, every=30):
    """Reports every `every` s of a bus driving run `r` `delay` s late (straight between its stops)."""
    out = []
    for t in range(since, until + 1, every):
        at = t - delay
        calls = r['stops']
        if at <= calls[0][2]:
            out.append((t, calls[0][0], calls[0][1]))
            continue
        for a, b in zip(calls, calls[1:]):
            if a[2] <= at <= b[2]:
                f = (at - a[2]) / (b[2] - a[2])
                out.append((t, a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
                break
        else:
            out.append((t, calls[-1][0], calls[-1][1]))
    return out


class RunMatchTests(SimpleTestCase):
    """D4: buses the feed sends without a trip (Kranj city line 5, IJPP:1302152, 22 Oct 18:31-18:46) are matched to the
    run of the operator's timetable whose stops they pass in order with one delay."""
    T = NOW - NOW % 3600

    def test_a_bus_passing_a_runs_stops_with_one_delay_is_on_that_run(self):
        a, b = run('K:a', self.T), run('K:b', self.T + 1800)  # the same line half an hour later
        track = path(a, 200, self.T + 300, self.T + 700)
        self.assertEqual(mapping.match_run(track, [b, a], self.T + 700), ('K:a', 200, 5))  # passed stops 1-4: next is 5

    def test_a_loop_matches_by_its_second_pass(self):
        """Line 5 starts and ends at Kranj Globus: a bus seen only on the way back is still on that run."""
        loop = run('K:loop', self.T, back=True)
        track = path(loop, 240, self.T + 900, self.T + 1300)
        self.assertEqual(mapping.match_run(track, [loop], self.T + 1300), ('K:loop', 240, 9))  # the way back's stop 1, not the first pass's

    def test_a_standing_or_unclear_bus_stays_unmatched(self):
        a = run('K:a', self.T)
        standing = [(self.T + i * 30, a['stops'][2][0], a['stops'][2][1]) for i in range(20)]
        self.assertIsNone(mapping.match_run(standing, [a], self.T + 600))  # one stop is no run
        # Two runs four minutes apart on the same stops: either could be it.
        twin = run('K:twin', self.T + 240)
        self.assertIsNone(mapping.match_run(path(a, 120, self.T + 300, self.T + 700), [a, twin], self.T + 700))
        # Far behind its timetable, or long past the run's end: not on it.
        self.assertIsNone(mapping.match_run(path(a, 900, self.T + 900, self.T + 1500), [a], self.T + 1500))
        self.assertIsNone(mapping.match_run(path(a, 0, self.T, self.T + 600), [a], self.T + 600 + mapping.RUN_AFTER_END + 60))


class LooseVehicleTests(SimpleTestCase):
    """D4: a bus without a trip is drawn on the run it is seen to run, never as a second copy of a drawn bus."""
    T = NOW - NOW % 3600

    def feed(self, loose, vehicle_id, at):
        t, lat, lon = next(p for p in reversed(loose) if p[0] <= at)
        return {'id': vehicle_id, 'vehicle': {'trip': {}, 'vehicle': {'id': vehicle_id}, 'timestamp': str(t), 'position': {'latitude': lat, 'longitude': lon}}}

    def replay(self, runs, buses, drawn_buses=(), taken=()):
        """Feeds every 30 s; `buses` {id: path} without a trip, `drawn_buses` {id: path} drawn with one. Placed runs per bus."""
        loose, drawn, placed = mapping.LooseVehicles(), mapping.MotionHistory(), {}
        for at in range(self.T + 300, self.T + 900, 30):
            for vid, track in dict(drawn_buses).items():
                t, lat, lon = next(p for p in reversed(track) if p[0] <= at)
                drawn.observe(vid, t, lat, lon, at)
            entities = [self.feed(track, vid, at) for vid, track in buses.items()]
            drops = [{'reason': 'no trip id', 'at': 'mapping.py:1', 'item': e} for e in entities]
            for e, run_id, *_ in loose.assign(entities, taken, drawn, lambda: runs, at, drops):
                placed.setdefault(e['id'], set()).add(run_id)
            self.assertTrue(all(d['reason'].startswith('no trip id, ') for d in drops))
        return placed

    def test_a_bus_on_a_run_nobody_reports_is_placed_on_it(self):
        a = run('K:a', self.T)
        self.assertEqual(self.replay([a], {'IJPP:1': path(a, 60, self.T, self.T + 900)}), {'IJPP:1': {'K:a'}})

    def test_a_copy_of_a_drawn_bus_is_never_placed(self):
        """IJPP:1302158 followed MOKranj:KRJN601: when that one's run changed, the copy fitted the other run."""
        a, b = run('K:a', self.T), run('K:b', self.T + 30)
        bus = path(b, 0, self.T, self.T + 900)
        twin = [(t + 7, lat + 0.0004, lon) for t, lat, lon in bus]  # the same bus through the other feed: 45 m off, 7 s later
        self.assertEqual(self.replay([a, b], {'IJPP:copy': twin}, drawn_buses={'MOKranj:bus': bus}, taken=['K:a']), {})

    def test_a_run_another_vehicle_reports_or_two_buses_fit_is_left_alone(self):
        a = run('K:a', self.T)
        self.assertEqual(self.replay([a], {'IJPP:1': path(a, 60, self.T, self.T + 900)}, taken=['K:a']), {})
        other = [(t, lat, lon + 0.0004) for t, lat, lon in path(a, 60, self.T, self.T + 900)]  # 30 m beside it: which one?
        self.assertEqual(self.replay([a], {'IJPP:1': path(a, 60, self.T, self.T + 900), 'IJPP:2': other}), {})


def stoptime(trip, first, last, dep=36000, rt=None, state='SCHEDULED'):
    return {'serviceDay': 1791496800, 'scheduledArrival': dep, 'scheduledDeparture': dep,
            'realtimeArrival': rt or dep, 'realtimeDeparture': rt or dep, 'realtime': rt is not None, 'realtimeState': state,
            'stopPosition': 2, 'pickupType': 'SCHEDULED', 'dropoffType': 'SCHEDULED', 'stop': {'platformCode': '3'},
            'trip': {'gtfsId': trip, 'route': {'gtfsId': 'IJPP:r1', 'shortName': 'RG 310', 'mode': 'RAIL', 'agency': {'gtfsId': 'IJPP:1161'}},
                     'departureStoptime': {'stop': {'gtfsId': first, 'name': 'Ljubljana'}},
                     'arrivalStoptime': {'stop': {'gtfsId': last, 'name': 'Jesenice'}}}}


class BoardTests(SimpleTestCase):
    def test_each_row_says_when_its_trip_starts(self):
        """A5: a row's "usually" is its own departure's, learned under the trip's start (aggregation.departure_delays)."""
        morning, evening = stoptime('IJPP:m', 'IJPP:x', 'IJPP:y'), stoptime('IJPP:e', 'IJPP:x', 'IJPP:y', dep=66000)
        morning['trip']['departureStoptime']['scheduledDeparture'] = 7 * 3600 + 600
        evening['trip']['departureStoptime']['scheduledDeparture'] = 18 * 3600 + 600
        rows = mapping.build_board('IJPP:s', [morning, evening, stoptime('IJPP:n', 'IJPP:x', 'IJPP:y')], 'departure', [])
        self.assertEqual([r.get('tripStart') for r in rows], ['07:10', '18:10', None])

    def test_a_bus_predicted_early_at_its_first_stop_leaves_at_its_time(self):
        """D3: buses predicted early at their first stop left on time or later (EARLY_START); further on early is early."""
        here = 'IJPP:here'
        starts, through = stoptime('IJPP:starts', here, 'IJPP:y', rt=36000 - 180), stoptime('IJPP:through', 'IJPP:x', 'IJPP:y', rt=36000 - 180)
        late = stoptime('IJPP:late', here, 'IJPP:y', rt=36000 + 120)
        rows = {r['tripId']: r for r in mapping.build_board(here, [starts, through, late], 'departure', [])}
        self.assertEqual(rows['IJPP:starts']['effectiveAt'], rows['IJPP:starts']['scheduledAt'])
        self.assertEqual(rows['IJPP:starts']['quality'], 'predicted')
        self.assertEqual(rows['IJPP:through']['effectiveAt'], mapping.iso(1791496800 + 36000 - 180))
        self.assertEqual(rows['IJPP:late']['effectiveAt'], mapping.iso(1791496800 + 36000 + 120))

    def test_departures_skip_terminating_trips_and_arrivals_skip_originating(self):
        here = 'IJPP:here'
        rows = [stoptime('IJPP:a', 'IJPP:x', 'IJPP:y'), stoptime('IJPP:ends', 'IJPP:x', here), stoptime('IJPP:starts', here, 'IJPP:y')]
        self.assertEqual([e['tripId'] for e in mapping.build_board(here, rows, 'departure', [])], ['IJPP:a', 'IJPP:starts'])
        arrivals = mapping.build_board(here, rows, 'arrival', [])
        self.assertEqual([e['tripId'] for e in arrivals], ['IJPP:a', 'IJPP:ends'])
        self.assertEqual(arrivals[0]['destination'], 'Ljubljana')  # arrivals show where the trip comes from

    def test_an_update_otp_left_out_gives_its_run_the_live_time(self):
        """D3: OTP had A6295 (IJPP:463770, Kranj AP 13:30) with no live time, though the feed's update for that day said
        +19 min; the board showed it by timetable (and dropped it at 13:30, sources._member_board)."""
        st = stoptime('IJPP:463770', 'IJPP:1121238', 'IJPP:y', dep=13 * 3600 + 30 * 60)
        st['trip']['departureStoptime'].update(scheduledDeparture=13 * 3600 + 30 * 60, stopPosition=1)
        update = {'trip': {'tripId': 'IJPP:463770', 'startDate': '20261009'},
                  'stopTimeUpdate': [{'stopSequence': 1, 'stopId': 'IJPP:1121238', 'departure': {'delay': 1149}}]}
        [row] = mapping.build_board('IJPP:1121238', [st], 'departure', [], updates=mapping.trip_update_index([{'tripUpdate': update}]))
        self.assertEqual((row['effectiveAt'], row['quality'], row['delaySource']), ('2026-10-09T11:49:09Z', 'predicted', 'gtfs-rt'))
        # An update about another day's run says nothing of this one
        update['trip']['startDate'] = '20261008'
        [row] = mapping.build_board('IJPP:1121238', [st], 'departure', [], updates=mapping.trip_update_index([{'tripUpdate': update}]))
        self.assertIsNone(row['effectiveAt'])
        # OTP's own live time stands when it has one
        update['trip']['startDate'] = '20261009'
        [row] = mapping.build_board('IJPP:1121238', [stoptime('IJPP:463770', 'IJPP:1121238', 'IJPP:y', dep=48600, rt=48660)], 'departure', [],
                                    updates=mapping.trip_update_index([{'tripUpdate': update}]))
        self.assertEqual(row['effectiveAt'], '2026-10-09T11:31:00Z')

    def test_an_update_naming_a_start_date_is_about_that_service_day_s_run(self):
        day = 1791496800  # 2026-10-09 00:00 in Ljubljana
        self.assertEqual(mapping.update_day({'trip': {'startDate': '20261009'}}, day + 48600, day + 52200, day), 0)
        self.assertIsNone(mapping.update_day({'trip': {'startDate': '20261008'}}, day + 48600, day + 52200, day))
        # A run that leaves after midnight still belongs to the day it is timetabled under
        self.assertEqual(mapping.update_day({'trip': {'startDate': '20261009'}}, day + 88200, day + 90000, day), 0)

    def test_late_updates_are_indexed_by_stop(self):
        updates = mapping.trip_update_index([{'tripUpdate': {'trip': {'tripId': 'IJPP:1'}, 'stopTimeUpdate': [
            {'stopId': 'IJPP:a', 'departure': {'delay': 1149, 'time': '1792669749'}},
            {'stopId': 'IJPP:b', 'arrival': {'delay': 900}}, {'stopId': 'IJPP:c', 'departure': {'delay': -60, 'time': '1792669800'}}]}}])
        self.assertEqual(mapping.late_by_stop(updates), {'IJPP:a': [(1792669749, 1149)], 'IJPP:b': [(None, 900)]})

    def test_a_trip_that_starts_and_ends_here_leaves_from_its_first_call_and_arrives_at_its_last(self):
        """D3: A6385 (IJPP:457777) leaves Radovljica as call 1 and is back as call 16; both boards there left it out."""
        here = 'IJPP:1129160'
        calls = [stoptime('IJPP:457777', here, here, dep=34800), stoptime('IJPP:457777', here, here, dep=37740)]
        for st, position in zip(calls, (1, 16)):
            st.update(stopPosition=position, headsign='Radovljica - Sebenje/Bledu - Radovljica')
            st['trip']['departureStoptime'].update(stopPosition=1, stop={'gtfsId': here, 'name': 'Radovljica'})
            st['trip']['arrivalStoptime'].update(stopPosition=16, stop={'gtfsId': here, 'name': 'Radovljica'})
        [out] = mapping.build_board(here, calls, 'departure', [])
        [back] = mapping.build_board(here, calls, 'arrival', [])
        self.assertEqual((out['scheduledAt'], back['scheduledAt']), ('2026-10-09T07:40:00Z', '2026-10-09T08:29:00Z'))
        # Its own stop as destination says nothing: the headsign does
        self.assertEqual(out['destination'], 'Radovljica - Sebenje/Bledu - Radovljica')

    def test_realtime_scheduled_and_canceled_entries(self):
        live, planned, canceled = mapping.build_board('IJPP:s', [
            stoptime('IJPP:1', 'IJPP:x', 'IJPP:y', rt=36300), stoptime('IJPP:2', 'IJPP:x', 'IJPP:y'),
            stoptime('IJPP:3', 'IJPP:x', 'IJPP:y', rt=36000, state='CANCELED')], 'departure', [])
        self.assertEqual((live['scheduledAt'], live['effectiveAt'], live['quality']), ('2026-10-09T08:00:00Z', '2026-10-09T08:05:00Z', 'predicted'))
        self.assertEqual((planned['effectiveAt'], planned['quality'], planned['platform']), (None, None, '3'))
        self.assertEqual((live['delaySource'], 'delaySource' in planned, 'delaySource' in canceled), ('gtfs-rt', False, False))
        self.assertTrue(canceled['canceled'])
        self.assertIsNone(canceled['effectiveAt'])

    def test_an_update_without_start_date_moves_the_run_on_its_way(self):
        """C8 (20 Oct 2026, 00:30): OTP put the delay of last night's 604, still out after midnight, on tonight's run
        of it; the board showed the running train by timetable and tonight's with +2 min."""
        yesterday = stoptime('IJPP:604', 'IJPP:x', 'IJPP:y', dep=24 * 3600 + 44 * 60)
        tonight = stoptime('IJPP:604', 'IJPP:x', 'IJPP:y', dep=24 * 3600 + 44 * 60, rt=24 * 3600 + 46 * 60)
        tonight['serviceDay'] += 86400
        for st in (yesterday, tonight):
            st['trip']['departureStoptime']['scheduledDeparture'] = 22 * 3600 + 50 * 60
        sent = yesterday['serviceDay'] + 24 * 3600 + 32 * 60
        updates = mapping.trip_update_index([{'tripUpdate': {'trip': {'tripId': 'IJPP:604'}, 'timestamp': sent, 'stopTimeUpdate': [
            {'stopSequence': 9, 'stopId': 'IJPP:s', 'departure': {'delay': 120}}]}}])
        out, later = mapping.build_board('IJPP:s', [yesterday, tonight], 'departure', [], updates=updates)
        self.assertEqual((out['effectiveAt'], out['quality'], out['delaySource']), ('2026-10-09T22:46:00Z', 'predicted', 'gtfs-rt'))
        self.assertEqual((later['effectiveAt'], later['quality'], 'delaySource' in later), (None, None, False))
        # One sent long before the run (a feed that publishes ahead) is OTP's to place
        updates['IJPP:604']['timestamp'] = tonight['serviceDay'] + 12 * 3600
        out, later = mapping.build_board('IJPP:s', [yesterday, tonight], 'departure', [], updates=updates)
        self.assertEqual((out['effectiveAt'], later['effectiveAt']), (None, '2026-10-10T22:46:00Z'))
        # One naming its start date is about that day's run, which takes it where OTP has no live time (D3);
        # OTP's own live times stand
        updates['IJPP:604']['timestamp'] = sent
        updates['IJPP:604']['trip']['startDate'] = '20261009'
        out, later = mapping.build_board('IJPP:s', [yesterday, tonight], 'departure', [], updates=updates)
        self.assertEqual((out['effectiveAt'], later['effectiveAt']), ('2026-10-09T22:46:00Z', '2026-10-10T22:46:00Z'))
        updates['IJPP:604']['trip']['startDate'] = '20261008'
        out, later = mapping.build_board('IJPP:s', [yesterday, tonight], 'departure', [], updates=updates)
        self.assertEqual((out['effectiveAt'], later['effectiveAt']), (None, '2026-10-10T22:46:00Z'))

    def test_route_alerts_flag_entries_inside_their_validity(self):
        departs = 1791496800 + 36000
        current = {'id': 'alert:now', 'stopIds': [], 'routeIds': ['IJPP:r1'], '_from': departs - 60, '_to': None}
        later = {'id': 'alert:later', 'stopIds': [], 'routeIds': ['IJPP:r1'], '_from': departs + 86400, '_to': departs + 2 * 86400}
        [entry] = mapping.build_board('IJPP:s', [stoptime('IJPP:1', 'IJPP:x', 'IJPP:y')], 'departure', [current, later])
        self.assertEqual(entry['alertIds'], ['alert:now'])


def otp_alert(id_, translations, start=NOW - 100, end=NOW + 100, entities=None):
    return {'id': id_, 'feed': 'IJPP', 'alertUrl': 'https://potniski.sz.si/inf', 'effectiveStartDate': start, 'effectiveEndDate': end,
            'alertHeaderTextTranslations': translations, 'alertDescriptionTextTranslations': [], 'agency': None,
            'entities': entities if entities is not None else [{'__typename': 'Route', 'gtfsId': 'IJPP:r1', 'agency': {'gtfsId': 'IJPP:1161'}}]}


class AlertTests(SimpleTestCase):
    def test_language_twins_keep_requested_language_and_single_language_alerts_stay(self):
        raw = [otp_alert('en', [{'language': 'en', 'text': 'Buses replace trains'}]),
               otp_alert('sl', [{'language': 'sl', 'text': 'Nadomestni avtobusi'}]),
               otp_alert('only-sl', [{'language': 'sl', 'text': 'Dela na progi'}], start=NOW - 50),
               otp_alert('both', [{'language': 'sl', 'text': 'Obvoz'}, {'language': 'en', 'text': 'Detour'}], start=NOW - 10)]
        self.assertEqual([a['title'] for a in mapping.build_alerts(raw, 'en', NOW)], ['Buses replace trains', 'Dela na progi', 'Detour'])
        self.assertEqual([a['title'] for a in mapping.build_alerts(raw, 'sl', NOW)], ['Nadomestni avtobusi', 'Dela na progi', 'Obvoz'])

    def test_expired_alerts_drop_and_entities_resolve(self):
        raw = [otp_alert('old', [{'language': 'en', 'text': 'x'}], end=NOW - 1),
               otp_alert('stop', [{'language': 'en', 'text': 'y'}], entities=[
                   {'__typename': 'StopOnRoute', 'stop': {'gtfsId': 'LPP:s'}, 'route': {'gtfsId': 'LPP:r', 'agency': {'gtfsId': 'LPP:lpp'}}}])]
        [alert] = mapping.build_alerts(raw, 'en', NOW)
        # A stop-on-route entity concerns that stop only, not every stop of the route.
        self.assertEqual((alert['id'], alert['stopIds'], alert['routeIds'], alert['operatorId']), ('alert:stop', ['LPP:s'], [], 'LPP:lpp'))
        self.assertNotIn('_aliases', mapping.public_alert(alert))

    def test_the_same_notice_per_stop_becomes_one_alert(self):
        detour = lambda id_, stop: otp_alert(id_, [{'language': 'en', 'text': 'Stop on detour'}], entities=[
            {'__typename': 'StopOnRoute', 'stop': {'gtfsId': stop}, 'route': {'gtfsId': 'LPP:r', 'agency': {'gtfsId': 'LPP:lpp'}}}])
        [alert] = mapping.build_alerts([detour('1', 'LPP:a'), detour('2', 'LPP:b')], 'en', NOW)
        self.assertEqual((alert['id'], alert['stopIds'], alert['_aliases']), ('alert:1', ['LPP:a', 'LPP:b'], ['alert:1', 'alert:2']))


    def test_sz_notices_on_lines_without_a_feed_route_are_szs(self):
        # Sežana - Opčine, Ljubljana - Villach: OTP ties the notice to no route or agency; it is SŽ's all the same.
        import base64
        sz_id = base64.b64encode(b'Alert:IJPP:SZ-OVIRA-11300').decode().rstrip('=')
        other = base64.b64encode(b'Alert:IJPP:OTHER-1').decode().rstrip('=')
        raw = [otp_alert(sz_id, [{'language': 'sl', 'text': 'Sežana - Opčine'}], entities=[]),
               otp_alert(other, [{'language': 'sl', 'text': 'Nekaj'}], start=NOW - 50, entities=[])]
        sz, unknown = mapping.build_alerts(raw, 'sl', NOW)
        self.assertEqual(sz['operatorId'], 'IJPP:1161')
        self.assertEqual(unknown['operatorId'], 'IJPP:unknown')

class RentalTests(SimpleTestCase):
    def test_car_sharing_is_not_a_bike(self):
        stations = [{'stationId': 'sharengo:1', 'network': 'sharengo', 'name': 'Car', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 2},
                    {'stationId': '17', 'network': 'jcdecaux_ljubljana', 'name': 'Prešernov trg', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 4,
                     'allowPickupNow': True, 'allowDropoffNow': True, 'availableVehicles': {'byType': [{'count': 4, 'vehicleType': {'formFactor': 'BICYCLE'}}]}}]
        scooters = [{'vehicleId': 'kvik:9', 'lat': 46, 'lon': 14, 'vehicleType': {'formFactor': 'SCOOTER_STANDING'}, 'rentalNetwork': {'networkId': 'kvik'}}]
        result = mapping.build_rentals(stations, scooters, NOW)
        self.assertEqual([(r['id'], r['mode'], r['providerId']) for r in result],
                         [('jcdecaux_ljubljana:17', 'bike', 'jcdecaux_ljubljana:bike'), ('kvik:9', 'scooter', 'kvik:scooter')])
        self.assertEqual(mapping.provider_name('jcdecaux_ljubljana:bike'), 'BicikeLJ')

    def test_a_network_without_e_bikes_has_no_e_bike_count_and_one_with_keeps_it_even_at_0(self):
        def rack(station_id, network, types, free):
            return {'stationId': station_id, 'network': network, 'name': station_id, 'lat': 46, 'lon': 14, 'vehiclesAvailable': free,
                    'allowPickupNow': True, 'allowDropoffNow': True,
                    'availableVehicles': {'byType': [{'count': n, 'vehicleType': {'formFactor': 'BICYCLE', 'propulsionType': p}} for p, n in types]}}
        stations = [rack('1', 'jcdecaux_ljubljana', [('HUMAN', 4)], 4), rack('2', 'jcdecaux_ljubljana', [('HUMAN', 0)], 0),
                    rack('3', 'jcdecaux_ljubljana', [], 0),
                    rack('a', 'nextbike_cc', [('HUMAN', 2), ('ELECTRIC_ASSIST', 3)], 5), rack('b', 'nextbike_cc', [('HUMAN', 2)], 2),
                    rack('c', 'nextbike_cc', [], 0)]
        result = {r['id']: r for r in mapping.build_rentals(stations, [], NOW)}
        for id_ in ('jcdecaux_ljubljana:1', 'jcdecaux_ljubljana:2', 'jcdecaux_ljubljana:3'):
            self.assertNotIn('ebikesAvailable', result[id_])
        self.assertEqual([result[f'nextbike_cc:{i}']['ebikesAvailable'] for i in 'abc'], [3, 0, 0])

    def test_a_free_floating_systems_stations_are_parking_zones(self):
        # Bolt: e-bikes and scooters left in zones, scooters also anywhere; a dock system's racks stay docks.
        stations = [{'stationId': 'bolt_359:z1', 'network': 'bolt_359', 'name': 'MOL - Situla', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 0,
                     'allowPickupNow': True, 'allowDropoffNow': True, 'availableSpaces': {'byType': [{'count': 5, 'vehicleType': {'formFactor': 'BICYCLE'}}]}},
                    {'stationId': '17', 'network': 'jcdecaux_ljubljana', 'name': 'Prešernov trg', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 4,
                     'spacesAvailable': 3, 'capacity': 7, 'allowPickupNow': True, 'allowDropoffNow': True}]
        scooter = lambda id_, lat: {'vehicleId': id_, 'lat': lat, 'lon': 14, 'vehicleType': {'formFactor': 'SCOOTER_STANDING'}, 'rentalNetwork': {'networkId': 'bolt_359'}}
        # One scooter stands in the zone (already in its count), one out on the street.
        zone, dock, street = mapping.build_rentals(stations, [scooter('bolt_359:in', 46.0002), scooter('bolt_359:out', 46.01)], NOW)
        self.assertEqual((zone.get('zone'), zone['canReturn'], zone['canPickup']), (True, True, False))
        self.assertNotIn('zone', dock)
        self.assertEqual(street['id'], 'bolt_359:out')

    @staticmethod
    def dock(station_id, network, north_m, east_m=0.0):
        # A dock `north_m` / `east_m` metres from 46°N 14.5°E.
        return {'stationId': station_id, 'network': network, 'name': station_id, 'lat': 46 + north_m / 111_320,
                'lon': 14.5 + east_m / (111_320 * 0.69466), 'vehiclesAvailable': 3, 'spacesAvailable': 2, 'capacity': 5,
                'allowPickupNow': True, 'allowDropoffNow': True}

    def test_stations_of_different_networks_at_one_place_share_a_group(self):
        # Kino Šiška: BicikeLJ, nextbike and a Bolt zone within 15 m of each other; each keeps its own numbers.
        zone = {**self.dock('bolt_359:z1', 'bolt_359', 11.7), 'spacesAvailable': None, 'capacity': None, 'vehiclesAvailable': 0,
                'availableSpaces': {'byType': [{'count': 5, 'vehicleType': {'formFactor': 'SCOOTER_STANDING'}}]}}
        stations = [self.dock('21', 'jcdecaux_ljubljana', 0), self.dock('89891670', 'nextbike_cc', 0.3, 8.8), zone,
                    self.dock('22', 'jcdecaux_ljubljana', 400)]
        scooter = {'vehicleId': 'bolt_359:s1', 'lat': 46.01, 'lon': 14.5, 'vehicleType': {'formFactor': 'SCOOTER_STANDING'},
                   'rentalNetwork': {'networkId': 'bolt_359'}}
        bicikelj, nextbike, bolt, alone, street = mapping.build_rentals(stations, [scooter], NOW)
        self.assertTrue(bolt.get('zone'))
        self.assertEqual({bicikelj.get('groupId'), nextbike.get('groupId'), bolt.get('groupId')}, {'stand:bolt_359:z1'})
        self.assertEqual((bicikelj['availableCount'], nextbike['docksAvailable']), (3, 2))
        self.assertNotIn('groupId', alone)
        self.assertNotIn('groupId', street)  # a free-floating vehicle is no stand

    def test_one_networks_stations_alone_are_not_a_group(self):
        a, b = mapping.build_rentals([self.dock('1', 'nextbike_cn', 0), self.dock('2', 'nextbike_cn', 6)], [], NOW)
        self.assertNotIn('groupId', a)
        self.assertNotIn('groupId', b)

    def test_nothing_is_grouped_across_more_than_15_m(self):
        # Linhartova: Bolt 9.5 m from nextbike, nextbike 10.5 m from BicikeLJ, but Bolt and BicikeLJ 20 m apart:
        # the closest pair is one place, BicikeLJ stays on its own.
        bolt, nextbike, bicikelj, far = mapping.build_rentals(
            [self.dock('bolt_359:z', 'bolt_359', 0), self.dock('89889365', 'nextbike_cc', 9.5),
             self.dock('44', 'jcdecaux_ljubljana', 20), self.dock('7', 'jcdecaux_ljubljana', 34.9)], [], NOW)
        self.assertEqual(bolt['groupId'], nextbike['groupId'])
        self.assertNotIn('groupId', bicikelj)
        self.assertNotIn('groupId', far)
        self.assertEqual(mapping.build_rentals([self.dock('a', 'nextbike_cc', 0), self.dock('b', 'jcdecaux_ljubljana', 15.5)], [], NOW)[0].get('groupId'), None)

    def test_neighbours_east_and_west_are_found_wherever_they_stand(self):
        for start in range(0, 30, 2):  # a degree of longitude is shorter than one of latitude
            west, east = mapping.build_rentals([self.dock('a', 'nextbike_cc', 0, start), self.dock('b', 'jcdecaux_ljubljana', 0, start + 14.5)], [], NOW)
            self.assertEqual((start, west.get('groupId')), (start, 'stand:jcdecaux_ljubljana:b'))


class GeometryTests(SimpleTestCase):
    def test_polyline_decodes_to_lon_lat(self):
        self.assertEqual(mapping.decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@'), [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]])

    def test_thin_keeps_ends(self):
        line = [[i, i] for i in range(1000)]
        thinned = mapping.thin(line, 100)
        self.assertEqual((len(thinned), thinned[0], thinned[-1]), (100, [0, 0], [999, 999]))


def leg(mode, start, end, transit=True, trip=None, interline=False, est=None, state='SCHEDULED', duration=None, headsign=None):
    when = lambda t: f'2026-10-09T{t}+02:00'
    return {'mode': mode, 'transitLeg': transit, 'interlineWithPreviousLeg': interline, 'realtimeState': state if transit else None,
            'duration': duration, 'start': {'scheduledTime': when(start), 'estimated': {'time': when(est)} if est else None},
            'end': {'scheduledTime': when(end), 'estimated': None},
            'from': {'name': 'A', 'lat': 46.0, 'lon': 14.5, 'stop': {'gtfsId': 'IJPP:a', 'platformCode': '2'} if transit else None},
            'to': {'name': 'B', 'lat': 46.1, 'lon': 14.4, 'stop': {'gtfsId': 'IJPP:b', 'platformCode': None} if transit else None},
            'route': {'gtfsId': 'IJPP:r', 'shortName': 'RG 1', 'mode': mode, 'agency': {'gtfsId': 'IJPP:bus' if mode == 'BUS' else 'IJPP:1161'}} if transit else None,
            'headsign': headsign, 'trip': {'gtfsId': trip, 'tripHeadsign': headsign} if trip else None, 'intermediatePlaces': [{'name': 'M'}] if transit else None, 'legGeometry': {'points': '_p~iF~ps|U_ulLnnqC'}, 'alerts': [{'id': 'X'}] if transit else []}


PLACE = {'name': 'Home', 'latitude': 46.0, 'longitude': 14.5, 'kind': 'address'}


class JourneyTests(SimpleTestCase):
    def request(self, **overrides):
        body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-09T10:00:00Z',
                'timeMode': 'departAt', 'minTransferSeconds': 180, 'modes': ['walk', 'bus', 'rail'], 'searchScope': 'all', 'riskMode': 'normal', **overrides}
        return journeys.parse_request(body, insane_enabled=False)

    def test_a_town_starts_and_ends_at_the_station_used_without_the_walk_from_between(self):
        town = {'name': 'Kranj', 'latitude': 46.05, 'longitude': 14.45, 'kind': 'station', 'stopId': 'IJPP:a', 'stopIds': ['IJPP:a', 'IJPP:ap']}
        walk_in, walk_out = leg('WALK', '09:55:00', '10:00:00', transit=False, duration=300), leg('WALK', '10:30:00', '10:36:00', transit=False, duration=360)
        walk_in['to']['stop'] = {'gtfsId': 'IJPP:a'}
        walk_out['from']['stop'] = {'gtfsId': 'IJPP:b'}
        data = {'planConnection': {'edges': [{'node': {'walkTime': 660, 'legs': [walk_in, leg('BUS', '10:00:00', '10:30:00', trip='IJPP:1'), walk_out]}}]}}
        req = self.request(origin=town, destination={**town, 'name': 'Bled', 'stopId': 'IJPP:b', 'stopIds': ['IJPP:b', 'IJPP:bap']})
        with mock.patch.object(sources, 'stop_group', side_effect=lambda s: [s]):
            self.assertEqual(journeys.otp_variables(req)['origin']['location'], {'coordinate': {'latitude': 46.05, 'longitude': 14.45}})
            [j] = journeys.build_journeys(data, req, [])
        self.assertEqual([l['mode'] for l in j['legs']], ['bus'])
        self.assertEqual((j['legs'][0]['origin']['name'], j['legs'][0]['destination']['name'], j['walkSeconds']), ('A', 'B', 0))
        self.assertEqual(j['effectiveDeparture'], '2026-10-09T10:00:00+02:00')
        with self.assertRaises(journeys.RequestError):
            self.request(origin={**town, 'stopIds': 'IJPP:a'})

    def test_a_town_keeps_journeys_through_another_stop_only_when_none_uses_its_stations(self):
        town = {'name': 'Kranj', 'latitude': 46.05, 'longitude': 14.45, 'kind': 'station', 'stopId': 'IJPP:a', 'stopIds': ['IJPP:a', 'IJPP:ap']}
        def walk_to(stop_id, start='09:55:00'):
            walk = leg('WALK', start, '10:00:00', transit=False, duration=300)
            walk['to']['stop'] = {'gtfsId': stop_id}
            return walk
        station = {'node': {'walkTime': 300, 'legs': [walk_to('IJPP:ap'), leg('BUS', '10:00:00', '10:30:00', trip='IJPP:1')]}}
        elsewhere = {'node': {'walkTime': 300, 'legs': [walk_to('IJPP:globus', '09:50:00'), leg('BUS', '10:00:00', '10:20:00', trip='IJPP:2')]}}
        req = self.request(origin=town)
        with mock.patch.object(sources, 'stop_group', side_effect=lambda s: [s]):
            kept = journeys.build_journeys({'planConnection': {'edges': [elsewhere, station]}}, req, [])
            alone = journeys.build_journeys({'planConnection': {'edges': [elsewhere]}}, req, [])
        self.assertEqual([j['legs'][0]['tripId'] for j in kept], ['IJPP:1'])
        self.assertEqual([j['legs'][0]['mode'] for j in alone], ['walk'])

    def test_transfer_statuses_use_walking_plus_safety(self):
        data = {'planConnection': {'edges': [{'node': {'walkTime': 300, 'legs': [
            leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1'),
            leg('WALK', '10:30:00', '10:32:00', transit=False, duration=120),
            leg('BUS', '10:34:00', '10:50:00', trip='IJPP:2', est='10:34:00'),  # 240 s available, 120 walk + 180 safety
            leg('BUS', '10:50:00', '11:10:00', trip='IJPP:2', interline=True),   # OTP's interline alone: still a change
        ]}}]}}
        merged = [{'id': 'alert:W', 'title': 'Replacement buses', 'routeIds': [], 'stopIds': [], 'operatorId': 'IJPP:1161',
                   '_from': 0, '_to': None, '_aliases': ['alert:W', 'alert:X']}]
        [j] = journeys.build_journeys(data, self.request(), merged)
        self.assertEqual(j['legs'][0]['alertIds'], ['alert:W'])
        self.assertEqual(j['transferCount'], 2)
        self.assertEqual(j['transfers'][0], {'requiredSeconds': 120, 'safetySeconds': 180, 'availableSeconds': 240, 'platform': '2', 'meetsSafetyMargin': False, 'status': 'tight',
                                             'legId': j['legs'][2]['id'],  # the leg boarded
                                             'walkSeconds': 120, 'walkKind': 'walk', 'rating': 'tight'})
        # Staying seated counts only once the vehicles were seen to do it (stays.py), so the through-run is timed.
        self.assertEqual((j['transfers'][1]['status'], j['transfers'][1]['legId'], j['legs'][3]['stayLevel']), ('tight', j['legs'][3]['id'], None))
        self.assertEqual((j['freshness'], j['notices'], j['legs'][0]['origin']['name'], j['legs'][-1]['destination']['name']), ('live', ['Replacement buses'], 'Home', 'Bled'))
        self.assertEqual((j['legs'][2]['delaySeconds'], j['legs'][0]['delaySeconds']), (0, None))
        self.assertEqual(j['legs'][0]['stopCount'], 2)
        self.assertNotIn('stopCount', j['legs'][1])  # walking

    def test_missed_and_canceled_transfers(self):
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [
            leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1'), leg('WALK', '10:30:00', '10:33:00', transit=False, duration=180),
            leg('BUS', '10:32:00', '10:50:00', trip='IJPP:2'), leg('BUS', '10:55:00', '11:10:00', trip='IJPP:3', state='CANCELED')]}}]}}
        [j] = journeys.build_journeys(data, self.request(), [])
        self.assertEqual([t['status'] for t in j['transfers']], ['missed', 'unknown'])

    def test_request_validation_and_otp_variables(self):
        with self.assertRaises(journeys.RequestError) as e:
            self.request(modes=['walk'])
        self.assertEqual(e.exception.code, 'NO_MODES')
        # Shared bikes alone: a street-only search (OTP refuses an empty transit list).
        self.assertEqual(journeys.otp_variables(self.request(modes=['walk', 'bike']))['modes'], {'direct': ['WALK', 'BICYCLE_RENTAL'], 'directOnly': True})
        with self.assertRaises(journeys.RequestError) as e:
            self.request(riskMode='insane')
        self.assertEqual(e.exception.code, 'FEATURE_UNAVAILABLE')
        with self.assertRaises(journeys.RequestError):
            self.request(dateTime='2026-10-09T10:00:00')
        via = {'name': 'Kranj', 'latitude': 46.24, 'longitude': 14.35, 'kind': 'station', 'stopId': 'IJPP:1122811'}
        v = journeys.otp_variables(self.request(via=[via], timeMode='arriveBy', minTransferSeconds=300, modes=['rail', 'bike']))
        self.assertEqual(v['via'], [{'visit': {'label': 'Kranj', 'minimumWaitTime': 'PT0S', 'stopLocationIds': ['IJPP:1122811']}}])
        self.assertEqual((v['preferences']['transit']['transfer'], list(v['dateTime'])), ({'slack': 'PT300S'}, ['latestArrival']))
        self.assertEqual(v['modes']['transit']['access'], ['WALK', 'BICYCLE_RENTAL'])
        # Rail only also takes SŽ's replacement buses (see test_replacement).
        self.assertEqual({m['mode'] for m in v['modes']['transit']['transit']}, {'RAIL', 'TRAM', 'SUBWAY', 'MONORAIL', 'FUNICULAR', 'BUS', 'COACH'})

    def test_operator_filter_and_insane_preferences(self):
        with self.assertRaises(journeys.RequestError):
            self.request(operators=['LPP'])
        body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-09T10:00:00Z', 'timeMode': 'departAt',
                'minTransferSeconds': 300, 'modes': ['walk', 'bus'], 'riskMode': 'insane', 'operators': ['IJPP:1118', 'IJPP:1118']}
        v = journeys.otp_variables(journeys.parse_request(body, insane_enabled=True))
        self.assertEqual(v['preferences']['transit'], {'transfer': {'slack': 'PT0S', 'cost': 0, 'maximumTransfers': 29, 'maximumAdditionalTransfers': 30}, 'filters': [{'include': [{'agencies': ['IJPP:1118', 'LPP:lpp']}]}]})  # every feed's id of LPP (operator_aliases.csv)
        self.assertEqual(v['preferences']['street']['walk'], {'speed': journeys.INSANE_WALK_SPEED})

    def test_leg_carries_the_line_headsign(self):
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [leg('BUS', '10:00:00', '10:20:00', trip='LPP:1', headsign='Ljubljana Vižmarje')]}}]}}
        [j] = journeys.build_journeys(data, self.request(), [])
        self.assertEqual(j['legs'][0]['headsign'], 'Ljubljana Vižmarje')

    def test_after_midnight_a_leg_takes_the_update_about_its_run(self):
        """IC 350, 20 Oct 2026: OTP put the feed's +36 min (no start date) on tonight's run of the train instead of last
        night's, still on its way."""
        from datetime import datetime

        def train(start, end, est=None):
            raw = leg('RAIL', start, end, trip='IJPP:350', est=est)
            raw['trip']['departureStoptime'] = {'scheduledDeparture': 22 * 3600 + 30 * 60}
            return {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [raw]}}]}}
        sent = int(datetime.fromisoformat('2026-10-09T00:40:00+02:00').timestamp())
        updates = {'IJPP:350': {'trip': {'tripId': 'IJPP:350'}, 'timestamp': sent, 'updates': [
            {'stopId': 'IJPP:a', 'departure': {'delay': 2160}}, {'stopId': 'IJPP:b', 'arrival': {'delay': 2100}}]}}
        with mock.patch('prestop_api.trainlive.trip_updates', return_value=updates):
            [last_night] = journeys.build_journeys(train('00:50:00', '01:04:00'), self.request(), [])
            [tonight] = journeys.build_journeys(train('22:40:00', '23:00:00', est='23:16:00'), self.request(), [])
        ride = last_night['legs'][0]
        self.assertEqual((ride['effectiveDeparture'], ride['effectiveArrival'], ride['delaySeconds']),
                         ('2026-10-09T01:26:00+02:00', '2026-10-09T01:39:00+02:00', 2160))
        ride = tonight['legs'][0]
        self.assertEqual((ride['effectiveDeparture'], ride['delaySeconds']), ('2026-10-09T22:40:00+02:00', None))
        self.assertNotEqual(ride['predictionBasis'], 'live')

    def test_headsign_falls_back_to_trip_headsign_then_none(self):
        raw = leg('BUS', '10:00:00', '10:20:00', trip='LPP:1')
        raw['trip']['tripHeadsign'] = 'Črnuče'
        [j] = journeys.build_journeys({'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [raw]}}]}}, self.request(), [])
        self.assertEqual(j['legs'][0]['headsign'], 'Črnuče')
        raw['trip']['tripHeadsign'] = '  '
        [j] = journeys.build_journeys({'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [raw]}}]}}, self.request(), [])
        self.assertIsNone(j['legs'][0]['headsign'])

    def test_bikes_and_scooters_are_routed_along_cycle_paths(self):
        street = journeys.otp_variables(self.request(modes=['walk', 'bus', 'bike', 'scooter']))['preferences']['street']
        self.assertEqual(street['bicycle'], {'optimization': {'type': 'SAFE_STREETS'}})
        self.assertEqual(street['scooter'], {'optimization': {'type': 'SAFE_STREETS'}})

    def test_price_fields_are_accepted_and_every_plan_is_priced(self):
        profile = {'cards': ['urbana-monthly', 'urbana-monthly'], 'bikeMemberships': ['jcdecaux_ljubljana'], 'scooterPasses': [],
                   'car': {'fuel': 'diesel', 'litresPer100km': 5.5, 'vignette': False}}
        req = self.request(modes=['walk', 'bus', 'car', 'carPark'], showPrices=True, costPreset='balanced', priceProfile=profile)
        self.assertEqual((req['showPrices'], req['costPreset']), (True, 'balanced'))
        self.assertEqual(req['priceProfile'], {**profile, 'cards': ['urbana-monthly']})
        # Every plan is priced (2026-10-19): without showPrices, or with it false, the profile and preset still count.
        for overrides in ({}, {'showPrices': False}):
            req = self.request(costPreset='cheapest', priceProfile=profile, **overrides)
            self.assertEqual((req['showPrices'], req['costPreset'], req['priceProfile']['cards']), (True, 'cheapest', ['urbana-monthly']))
        self.assertEqual((self.request()['costPreset'], self.request()['priceProfile']['cards']), ('fastest', []))
        # Car modes are accepted; until they are planned (A7) OTP is asked exactly as before.
        self.assertEqual(journeys.otp_variables(self.request(modes=['walk', 'bus', 'car', 'carPark'])), journeys.otp_variables(self.request(modes=['walk', 'bus'])))

    def test_bad_price_fields_are_refused(self):
        for overrides in ({'showPrices': 'yes'}, {'costPreset': 'free'}, {'priceProfile': []}, {'priceProfile': {'cards': ['a b']}},
                          {'priceProfile': {'cards': ['x'] * 13}}, {'priceProfile': {'car': {'fuel': 'coal', 'litresPer100km': 6, 'vignette': True}}},
                          {'priceProfile': {'car': {'fuel': 'petrol', 'litresPer100km': 90, 'vignette': True}}},
                          {'priceProfile': {'car': {'fuel': 'petrol', 'litresPer100km': True, 'vignette': True}}}):
            with self.subTest(overrides=overrides), self.assertRaises(journeys.RequestError):
                self.request(**overrides)


class MotionStateTests(SimpleTestCase):
    def test_same_place_for_twenty_seconds_is_stopped(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (120, 46.05001, 14.50001)], None, None), (True, 100))

    def test_duplicate_timestamp_is_not_evidence(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (100, 46.05, 14.5)], None, None), (False, None))

    def test_moving_clears(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (120, 46.05, 14.5), (140, 46.0505, 14.5)], None, None), (False, None))

    def test_feed_status_and_speed_win(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5)], None, 'STOPPED_AT')[0], True)
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5)], 0.2, None)[0], True)

    def test_too_short_a_span_is_not_evidence(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (110, 46.05, 14.5)], None, None), (False, None))

    def test_standing_since_the_first_report_in_place(self):
        history = [(60, 46.04, 14.5), (100, 46.05, 14.5), (120, 46.05, 14.5), (140, 46.05001, 14.5)]
        self.assertEqual(mapping.motion_state(history, None, None), (True, 100))


class VehicleHistoryTests(SimpleTestCase):
    def test_vehicles_carry_stopped_since_from_consecutive_reports(self):
        history = mapping.MotionHistory()
        infos = {'LPP:t1': {'routeId': 'LPP:r6'}}
        [first] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1', stamp=NOW - 40)], {}, infos, ROUTES, {}, NOW - 30, history=history)
        self.assertEqual((first['stopped'], first.get('stoppedSince')), (False, None))
        [v] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1', stamp=NOW - 20)], {}, infos, ROUTES, {}, NOW, history=history)
        self.assertEqual((v['stopped'], v['stoppedSince']), (True, mapping.iso(NOW - 40)))

    def test_history_forgets_old_reports(self):
        history = mapping.MotionHistory()
        history.observe('v', 100, 46.05, 14.5, now=100)
        self.assertEqual(history.observe('v', 500, 46.05, 14.5, now=500), [(500, 46.05, 14.5)])


class ImplausibleDelayTests(SimpleTestCase):
    """Spec 2026-10-19 A4: N0127 (IJPP:425272, its 07:05 run) still reported that trip at 10:39 on 19 Oct, and the
    feed's delay grew with the clock to +208 min at its last stops; its reports named no stop."""

    UPDATE = {'tripUpdate': {'trip': {'tripId': 'IJPP:425272', 'startDate': '20261019', 'scheduleRelationship': 'SCHEDULED'}, 'stopTimeUpdate': [
        {'stopSequence': 1, 'arrival': {'delay': 3840}, 'departure': {'delay': 3840}},
        {'stopSequence': 4, 'arrival': {'delay': 3780}, 'departure': {'delay': 3780}},
        {'stopSequence': 15, 'stopId': 'IJPP:15', 'arrival': {'delay': 12480}, 'departure': {'delay': 12480}},
        {'stopSequence': 16, 'stopId': 'IJPP:16', 'arrival': {'delay': 12480}, 'departure': {'delay': 12480}}]}}
    ROUTES = {'IJPP:n0127': {'gtfsId': 'IJPP:n0127', 'shortName': 'N0127', 'mode': 'BUS', 'agencyId': 'IJPP:1119'}}

    def vehicle(self, **report):
        updates = mapping.trip_update_index([self.UPDATE])
        [v] = mapping.build_vehicles([position('IJPP:425272', 'IJPP:1301363', **report)], updates,
                                     {'IJPP:425272': {'routeId': 'IJPP:n0127'}}, self.ROUTES, {}, NOW)
        return v

    def test_a_delay_over_two_hours_without_a_confirming_report_is_no_live_data(self):
        self.assertIsNone(self.vehicle()['delaySeconds'])

    def test_the_vehicle_naming_its_stop_on_the_trip_confirms_it(self):
        self.assertEqual(self.vehicle(stopId='IJPP:16')['delaySeconds'], 12480)
        self.assertEqual(self.vehicle(currentStopSequence=15)['delaySeconds'], 12480)

    def test_ordinary_delays_need_no_confirmation(self):
        self.assertEqual(mapping.believable(3840, confirmed=False), 3840)
        self.assertIsNone(mapping.believable(-7300, confirmed=False))  # 2 hours early: another run of the line

    def test_a_board_row_two_hours_late_needs_its_vehicle_to_show_it(self):
        row = stoptime('IJPP:425272', 'IJPP:x', 'IJPP:y', dep=26880, rt=26880 + 12480)
        [alone] = mapping.build_board('IJPP:s', [row], 'departure', [])
        self.assertEqual((alone['effectiveAt'], alone['quality']), (None, None))
        [shown] = mapping.build_board('IJPP:s', [row], 'departure', [], live={'IJPP:425272': 12400})
        self.assertEqual(shown['quality'], 'predicted')
        late = stoptime('IJPP:a', 'IJPP:x', 'IJPP:y', dep=26880, rt=26880 + 1800)
        self.assertEqual(mapping.build_board('IJPP:s', [late], 'departure', [])[0]['quality'], 'predicted')

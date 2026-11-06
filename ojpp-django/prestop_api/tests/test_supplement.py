"""Kranj's city buses from the operator's own GTFS (supplement.py), in the shapes OTP returns."""
import io
import zipfile
from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import supplement

FILES = {
    'agency.txt': 'agency_id,agency_name,agency_url,agency_timezone\nMP_Kranj,MP_Kranj,MP_Kranj,Europe/Ljubljana\n',
    'routes.txt': ('route_id,agency_id,route_short_name,route_long_name,route_type,route_color\n'
                   '4015,MP_Kranj,4015,PROGA 1: Prebačevo-Kranj kolodvor,3,063938\n'
                   '4153,MP_Kranj,4153,PROGA 15: Kolodvor-Planina-Kolodvor,3,46001A\n'),
    'stops.txt': ('stop_id,stop_name,stop_lat,stop_lon\n'
                  '27,Prebačevo,46.27,14.36\n22,Hrastje,46.26,14.36\n31,Kranj Pokopališče,46.237,14.369\n150,Kranj AP,46.24,14.35\n'),
    'trips.txt': ('route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n'
                  '4015,1,xfp_155095,PROGA 1: Prebačevo-Kranj kolodvor,0,S1\n'
                  '4015,2,sat_155095,PROGA 1: Prebačevo-Kranj kolodvor,0,S1\n'),
    'stop_times.txt': ('trip_id,arrival_time,departure_time,stop_id,stop_sequence\n'
                       'xfp_155095,12:07:00,12:07:00,27,1\nxfp_155095,12:08:00,12:08:00,22,2\n'
                       'xfp_155095,12:19:00,12:19:00,31,3\nxfp_155095,12:31:00,12:31:00,150,4\n'
                       'sat_155095,08:00:00,08:00:00,27,1\nsat_155095,08:20:00,08:20:00,150,2\n'),
    'shapes.txt': 'shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nS1,46.27,14.36,1\nS1,46.24,14.35,2\n',
    'calendar.txt': ('service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n'
                     '1,1,1,1,1,1,0,0,20261012,20261023\n2,0,0,0,0,0,1,0,20261017,20261024\n'),
    'calendar_dates.txt': 'service_id,date,exception_type\n1,20261014,2\n',
}
MONDAY = date(2026, 10, 12)


def feed():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, text in FILES.items():
            z.writestr(name, '﻿' + text)
    return supplement.parse('MOKranj', buf.getvalue())


class SupplementTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(supplement, '_feeds', return_value={'MOKranj': feed()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_names_and_colours_as_the_kranj_generator_makes_them(self):
        self.assertEqual(supplement.short_name('4153', 'Kolodvor-Planina'), '15')
        self.assertEqual(supplement.short_name('4010', 'Kranj kolodvor - Plinarna'), '1')
        self.assertEqual(supplement.short_name('4015', 'PROGA 1: Prebačevo-Kranj'), '1')
        routes = supplement.routes()
        self.assertEqual(routes['MOKranj:4015']['shortName'], '1')
        self.assertEqual(routes['MOKranj:4015']['longName'], 'Prebačevo - Kranj kolodvor')
        self.assertEqual(routes['MOKranj:4015']['color'], '00AEEF')
        self.assertEqual(routes['MOKranj:4015']['agencyId'], 'MOKranj:MP_Kranj')

    def test_a_live_bus_gets_its_line_and_destination(self):
        self.assertEqual(supplement.trip_info('MOKranj:xfp_155095'),
                         {'routeId': 'MOKranj:4015', 'directionId': 0, 'headsign': 'Prebačevo - Kranj kolodvor', 'destination': 'Kranj AP'})
        self.assertEqual(supplement.trip_info('MOKranj:nope'), {})
        self.assertFalse(supplement.owns('IJPP:123'))

    def test_trips_run_on_their_service_days_only(self):
        self.assertIsNotNone(supplement.otp_trip('MOKranj:xfp_155095', MONDAY))
        self.assertIsNone(supplement.otp_trip('MOKranj:xfp_155095', date(2026, 10, 14)))  # removed that day
        self.assertIsNone(supplement.otp_trip('MOKranj:xfp_155095', date(2026, 10, 17)))  # Saturday
        self.assertIsNotNone(supplement.otp_trip('MOKranj:sat_155095', date(2026, 10, 17)))

    def test_trip_in_otp_shape_with_delays_carried_forward(self):
        update = {'trip': {'startDate': '20261012'}, 'updates': [{'stopSequence': 2, 'arrival': {'delay': 120}, 'departure': {'delay': 150}, 'stopId': 'MOKranj:22'}]}
        t = supplement.otp_trip('MOKranj:xfp_155095', MONDAY, update)
        self.assertEqual([s['stop']['gtfsId'] for s in t['stoptimes']], ['MOKranj:27', 'MOKranj:22', 'MOKranj:31', 'MOKranj:150'])
        self.assertEqual(t['shapeCoordinates'], [[14.36, 46.27], [14.35, 46.24]])
        first, second, third, _ = t['stoptimesForDate']
        self.assertFalse(first['realtime'])
        self.assertEqual(first['realtimeDeparture'], 12 * 3600 + 7 * 60)
        self.assertEqual((second['realtimeArrival'] - second['scheduledArrival'], second['realtimeDeparture'] - second['scheduledDeparture']), (120, 150))
        self.assertTrue(third['realtime'])
        self.assertEqual(third['realtimeArrival'] - third['scheduledArrival'], 150)
        # Yesterday's update does not move today's trip.
        stale = supplement.otp_trip('MOKranj:xfp_155095', MONDAY, {**update, 'trip': {'startDate': '20261009'}})
        self.assertFalse(any(s['realtime'] for s in stale['stoptimesForDate']))

    def test_line_lists_the_days_trips_per_variant(self):
        route = supplement.otp_route('MOKranj:4015', MONDAY)
        self.assertEqual(len(route['patterns']), 2)
        busy = next(p for p in route['patterns'] if len(p['stops']) == 4)
        self.assertEqual([t['gtfsId'] for t in busy['tripsForDate']], ['MOKranj:xfp_155095'])
        self.assertEqual(len({p['code'] for p in route['patterns']}), 2)

    def test_board_at_a_stop(self):
        start = supplement.day_start(MONDAY) + 12 * 3600
        rows = supplement.stoptimes('MOKranj:31', start, 3600, 10, {})
        self.assertEqual([(r['trip']['gtfsId'], r['scheduledDeparture']) for r in rows], [('MOKranj:xfp_155095', 12 * 3600 + 19 * 60)])
        self.assertEqual(rows[0]['trip']['arrivalStoptime']['stop']['name'], 'Kranj AP')
        self.assertIsNone(supplement.stoptimes('IJPP:1', start, 3600, 10, {}))

    def test_a_bus_predicted_early_at_its_first_stop_stays_until_its_time(self):
        """D3: a bus waits at its first stop for its time (mapping.EARLY_START); further on an early bus has gone."""
        update = {'trip': {'startDate': '20261012'}, 'updates': [{'stopSequence': 1, 'departure': {'delay': -180}, 'stopId': 'MOKranj:27'},
                                                                  {'stopSequence': 3, 'departure': {'delay': -180}, 'stopId': 'MOKranj:31'}]}
        base = supplement.day_start(MONDAY)
        first = supplement.stoptimes('MOKranj:27', base + 12 * 3600 + 5 * 60, 3600, 10, {'MOKranj:xfp_155095': update})
        self.assertEqual([r['realtimeDeparture'] - r['scheduledDeparture'] for r in first], [-180])
        self.assertEqual(supplement.stoptimes('MOKranj:31', base + 12 * 3600 + 17 * 60, 3600, 10, {'MOKranj:xfp_155095': update}), [])

    def test_a_run_named_by_otps_version_prefixed_id(self):
        # OTP's copy merges versions of the file and prefixes a shared trip id ('3_xfpW3oZOcB_155115', 19 Oct 2026);
        # the realtime feed names the run so, the file by its plain id.
        self.assertEqual(supplement.trip_info('MOKranj:3_xfp_155095')['routeId'], 'MOKranj:4015')
        self.assertEqual(supplement.otp_trip('MOKranj:3_xfp_155095', MONDAY)['gtfsId'], 'MOKranj:3_xfp_155095')
        self.assertEqual(supplement.trip_info('MOKranj:3_nope'), {})
        self.assertEqual(supplement.trip_info('MOKranj:x_xfp_155095'), {})
        update = {'trip': {'tripId': 'MOKranj:3_xfp_155095', 'startDate': '20261012'},
                  'updates': [{'stopSequence': 2, 'departure': {'delay': 300}, 'stopId': 'MOKranj:22'}]}
        index = supplement.with_own_ids({'MOKranj:3_xfp_155095': update, 'IJPP:1': {'trip': {'tripId': 'IJPP:1'}, 'updates': []}})
        filed = index['MOKranj:xfp_155095']
        self.assertEqual((filed['trip']['tripId'], filed['oldId']), ('MOKranj:xfp_155095', 'MOKranj:3_xfp_155095'))
        self.assertIn('MOKranj:3_xfp_155095', index)
        start = supplement.day_start(MONDAY) + 12 * 3600
        row = supplement.stoptimes('MOKranj:31', start, 3600, 10, index)[0]
        self.assertEqual(row['realtimeDeparture'] - row['scheduledDeparture'], 300)
        # A run the feed also names by the plain id keeps its own update.
        own = {**update, 'trip': {'tripId': 'MOKranj:xfp_155095'}}
        self.assertIs(supplement.with_own_ids({'MOKranj:3_xfp_155095': update, 'MOKranj:xfp_155095': own})['MOKranj:xfp_155095'], own)


class LocalFeedTests(SimpleTestCase):
    """Hand-kept timetables in data/gtfs/<feedId>/ (Sevnica's city bus since its feed expired)."""

    def setUp(self):
        self.feed = supplement.parse('Sevnica', supplement._local_zip(str(supplement.LOCAL_GTFS / 'Sevnica')))

    def test_the_folder_is_a_feed_with_otps_ids(self):
        self.assertIn('Sevnica:1', self.feed['routes'])
        self.assertIn('Sevnica:1', self.feed['stops'])  # Sevnica - ŽELEZNIŠKA POSTAJA, as in OTP
        self.assertEqual(len(self.feed['trips']['Sevnica:1']['stops']), 32)

    def test_it_runs_on_school_days_but_not_on_holidays_or_weekends(self):
        runs = lambda trip, day: supplement.runs(self.feed, self.feed['trips'][trip]['serviceId'], day)  # noqa: E731
        self.assertTrue(runs('Sevnica:2', date(2026, 10, 12)))     # a Monday
        self.assertFalse(runs('Sevnica:2', date(2026, 10, 17)))    # Saturday
        self.assertFalse(runs('Sevnica:2', date(2026, 12, 25)))    # Christmas
        self.assertTrue(runs('Sevnica:4', date(2026, 11, 6)))      # the cemetery run, first Friday
        self.assertFalse(runs('Sevnica:4', date(2026, 11, 13)))

    def test_the_folders_are_feeds_when_turned_on(self):
        with self.settings(PRESTOP_LOCAL_GTFS=True, PRESTOP_KRANJ_GTFS_URL=''):
            self.assertEqual(set(supplement.feeds()), {'Brezice', 'CELEBUS', 'Jesenice', 'MARPROM', 'MOKoper', 'MOKrsko', 'Piran', 'Postojna', 'Ptuj', 'Sevnica'})
        with self.settings(PRESTOP_LOCAL_GTFS=False, PRESTOP_KRANJ_GTFS_URL=''):
            self.assertEqual(supplement.feeds(), {})


FILLS = {
    'agency.txt': 'agency_id,agency_name,agency_url,agency_timezone\nMP_Kranj,MP_Kranj,MP_Kranj,Europe/Ljubljana\n',
    'routes.txt': ('route_id,agency_id,route_short_name,route_long_name,route_type\n'
                   '4015,MP_Kranj,4015,PROGA 1: Prebačevo-Kranj kolodvor,3\n4153,MP_Kranj,4153,PROGA 15: Kolodvor-Planina-Kolodvor,3\n'),
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon\n150,Kranj AP,46.24,14.35\n31,Kranj Pokopališče,46.237,14.369\n9,Kranj Planina otok,46.2375,14.3647\n',
    'trips.txt': ('route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n'
                  '4153,NEP,AMY_1,PROGA 15: Kolodvor-Planina-Kolodvor,0,F\n4015,V,every_1,PROGA 1: Prebačevo-Kranj kolodvor,0,\n'),
    'stop_times.txt': ('trip_id,arrival_time,departure_time,stop_id,stop_sequence\n'
                       'AMY_1,08:52:00,08:52:00,150,1\nAMY_1,09:01:00,09:01:00,9,2\nAMY_1,09:04:00,09:04:00,31,3\n'
                       'every_1,09:00:00,09:00:00,150,1\nevery_1,09:10:00,09:10:00,31,2\n'),
    'shapes.txt': 'shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nF,46.24,14.35,1\nF,46.237,14.369,2\n',
    'calendar.txt': ('service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n'
                     'NEP,0,0,0,0,0,0,1,20261011,20270630\nV,1,1,1,1,1,1,1,20261011,20270630\n'),
    'calendar_dates.txt': 'service_id,date,exception_type\nNEP,20261014,1\n',
    'fills.txt': 'route_id\n4153\n4015\n',
}
SUNDAY = date(2026, 10, 18)


class FillTests(SimpleTestCase):
    """A fills folder (fills.txt) adds runs to the operator's file of the same feed on the days it runs none of that line:
    Kranj's line 15 on Sundays and holidays, which Ridango's file lacks."""

    def setUp(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for name, text in FILLS.items():
                z.writestr(name, text)
        self.feed = supplement.fill(feed(), supplement.parse('MOKranj', buf.getvalue()))
        runs = lambda trip, day: supplement.runs(self.feed, self.feed['trips'][trip]['serviceId'], day)  # noqa: E731
        self.runs = runs

    def test_its_runs_join_the_operators_file_on_days_it_has_none_of_the_line(self):
        self.assertTrue(self.runs('MOKranj:AMY_1', SUNDAY))
        self.assertFalse(self.runs('MOKranj:AMY_1', MONDAY))
        self.assertTrue(self.runs('MOKranj:AMY_1', date(2026, 10, 14)))  # a holiday in the folder; the file skips that Wednesday
        self.assertEqual(self.feed['trips']['MOKranj:AMY_1']['shapeId'], 'fill-F')
        self.assertIn('fill-F', self.feed['shapes'])
        self.assertIn(('MOKranj:AMY_1', 0), self.feed['byStop']['MOKranj:150'])
        self.assertIn('MOKranj:4153', self.feed['stopRoutes']['MOKranj:9'])

    def test_the_operators_own_runs_of_the_line_win_day_by_day(self):
        self.assertFalse(self.runs('MOKranj:every_1', MONDAY))            # the file runs line 1 on weekdays
        self.assertFalse(self.runs('MOKranj:every_1', date(2026, 10, 17)))  # and on Saturdays
        self.assertTrue(self.runs('MOKranj:every_1', SUNDAY))
        self.assertTrue(self.runs('MOKranj:every_1', date(2026, 10, 14)))  # the file's weekday run is off that day
        self.assertTrue(self.runs('MOKranj:every_1', date(2026, 11, 2)))   # past the file's dates: nothing to compare
        self.assertTrue(self.runs('MOKranj:xfp_155095', MONDAY))
        self.assertEqual(self.feed['routes']['MOKranj:4015']['color'], '00AEEF')  # the operator's route stays

    def test_kranjs_folder_is_a_fill_not_a_feed(self):
        with self.settings(PRESTOP_LOCAL_GTFS=True, PRESTOP_KRANJ_GTFS_URL=''):
            self.assertNotIn('MOKranj', supplement.feeds())
            self.assertIn('MOKranj', supplement._fills())
        kept = supplement.parse('MOKranj', supplement._local_zip(str(supplement.LOCAL_GTFS / 'MOKranj')))
        self.assertEqual(kept['fills'], {'MOKranj:4153'})
        self.assertEqual(len(kept['trips']), 10)  # Arriva's line 15 PDF: NEP 08:52 … 17:22
        self.assertEqual(sorted(t['stops'][0]['departure'] // 60 for t in kept['trips'].values()),
                         [532, 592, 652, 682, 772, 802, 892, 922, 1016, 1042])
        self.assertTrue(all(supplement.runs(kept, 'NEP', d) for d in (date(2026, 11, 8), date(2026, 12, 25), date(2027, 3, 29))))
        self.assertFalse(supplement.runs(kept, 'NEP', date(2026, 11, 9)))


CORRECTION = {
    'agency.txt': 'agency_id,agency_name,agency_url,agency_timezone\nA,Arriva d.o.o.,https://arriva.si,Europe/Ljubljana\n',
    'routes.txt': 'route_id,agency_id,route_short_name,route_long_name,route_type\n9,A,9,Koper AP - Potniški terminal,3\n2,A,2,Semedela - Bolnica,3\n',
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon\n100,Koper AP,45.54,13.73\n200,PH Sonce,45.53,13.72\n',
    'trips.txt': 'route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n9,D,fix-9-1,Koper AP,0,\n2,D,fix-2-1,Bolnica,0,\n',
    'stop_times.txt': ('trip_id,arrival_time,departure_time,stop_id,stop_sequence\n'
                       'fix-9-1,10:00:00,10:00:00,100,1\nfix-9-1,10:09:00,10:09:00,200,2\nfix-9-1,10:18:00,10:18:00,100,3\n'
                       'fix-2-1,10:55:00,10:55:00,100,1\nfix-2-1,11:05:00,11:05:00,200,2\n'),
    'calendar.txt': ('service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n'
                     'D,1,1,1,1,1,0,0,20261101,20270831\n'),
    'replaces.txt': 'route_id,mode\n9,replace\n2,add\n5,all\n',
}
THURSDAY, SATURDAY = date(2026, 11, 5), date(2026, 11, 7)


def correction():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, text in CORRECTION.items():
            z.writestr(name, text)
    return supplement.parse('MOKoper', buf.getvalue())


def call(route: str, trip: str, day: date, at: int) -> dict:
    return {'serviceDay': supplement.day_start(day), 'scheduledDeparture': at, 'realtimeDeparture': at,
            'trip': {'gtfsId': f'MOKoper:{trip}', 'route': {'gtfsId': f'MOKoper:{route}'}}}


class CorrectionTests(SimpleTestCase):
    """A hand-kept folder with replaces.txt corrects some lines of OTP's feed (Koper's line 9 on working days, two
    line 2 runs) and leaves the rest to OTP."""

    def setUp(self):
        patcher = mock.patch.object(supplement, '_feeds', return_value={'MOKoper': correction()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_its_own_runs_are_read_here(self):
        self.assertTrue(supplement.owns('MOKoper:fix-9-1'))
        self.assertIsNotNone(supplement.otp_trip('MOKoper:fix-9-1', THURSDAY))
        for otp_id in ('MOKoper:otp-9', 'MOKoper:100', 'MOKoper:9'):
            self.assertFalse(supplement.owns(otp_id), otp_id)
        self.assertFalse(supplement.stale('MOKoper:otp-9'))  # OTP's other runs are not an old table
        self.assertIsNone(supplement.stoptimes('MOKoper:100', 0, 3600, 10, {}))
        self.assertEqual((supplement.routes(), supplement.stops(), supplement.sequences()), ({}, [], []))

    def test_a_replaced_line_on_the_days_the_correction_runs_it(self):
        self.assertTrue(supplement.replaced('MOKoper:9', THURSDAY))
        self.assertFalse(supplement.replaced('MOKoper:9', SATURDAY))   # weekends stay OTP's
        self.assertFalse(supplement.replaced('MOKoper:2', THURSDAY))   # added runs, OTP's kept
        self.assertFalse(supplement.replaced('MOKoper:4', THURSDAY))
        leg = {'route': {'gtfsId': 'MOKoper:9'}, 'start': {'scheduledTime': '2026-11-05T10:00:00+01:00'}}
        self.assertTrue(supplement.leg_replaced(leg))
        self.assertFalse(supplement.leg_replaced({**leg, 'start': {'scheduledTime': '2026-11-07T10:00:00+01:00'}}))

    def test_mode_all_drops_otps_runs_on_every_day_of_the_folders_dates(self):
        # Postojna's school lines: OTP runs them through the holidays, when the folder runs nothing.
        for day in (THURSDAY, SATURDAY, date(2026, 12, 28), date(2027, 8, 31)):
            self.assertTrue(supplement.replaced('MOKoper:5', day), day)
        for day in (date(2026, 10, 30), date(2027, 9, 1)):
            self.assertFalse(supplement.replaced('MOKoper:5', day), day)

    def test_board_drops_replaced_runs_and_adds_its_own(self):
        calls = [call('9', 'otp-9', THURSDAY, 36_000), call('2', 'otp-2', THURSDAY, 37_000), call('4', 'otp-4', THURSDAY, 40_000)]
        start = supplement.day_start(THURSDAY) + 30_000
        board = supplement.corrected_board('MOKoper:100', calls, start, 20_000, {})
        self.assertEqual([c['trip']['gtfsId'] for c in board], ['MOKoper:fix-9-1', 'MOKoper:otp-2', 'MOKoper:fix-9-1', 'MOKoper:fix-2-1', 'MOKoper:otp-4'])
        saturday = [call('9', 'otp-9', SATURDAY, 36_000)]
        self.assertEqual(supplement.corrected_board('MOKoper:100', saturday, supplement.day_start(SATURDAY), 80_000, {}), saturday)
        self.assertEqual(supplement.corrected_board('IJPP:1', calls, start, 20_000, {}), calls)

    def test_line_keeps_otps_variants_and_adds_the_corrections(self):
        otp = {'gtfsId': 'MOKoper:9', 'patterns': [{'code': 'MOKoper:9:0:01', 'tripsForDate': [{'gtfsId': 'MOKoper:otp-9'}]}]}
        thursday = supplement.corrected_route(otp, THURSDAY)
        self.assertEqual([(p['code'], [t['gtfsId'] for t in p['tripsForDate']]) for p in thursday['patterns']],
                         [('MOKoper:9:0:01', []), ('MOKoper:9:0:3', ['MOKoper:fix-9-1'])])
        saturday = supplement.corrected_route(otp, SATURDAY)
        self.assertEqual([len(p['tripsForDate']) for p in saturday['patterns']], [1, 0])
        other = {'gtfsId': 'MOKoper:4', 'patterns': []}
        self.assertIs(supplement.corrected_route(other, THURSDAY), other)

    def test_a_line_otp_does_not_have_is_the_corrections_own(self):
        # Celje's line 4: new on 1 Sep 2026, in the folder only; its line page was 404.
        line = supplement.added_route('MOKoper:2', THURSDAY)
        self.assertEqual([[t['gtfsId'] for t in p['tripsForDate']] for p in line['patterns']], [['MOKoper:fix-2-1']])
        self.assertEqual(supplement.added_route('MOKoper:2', SATURDAY)['patterns'][0]['tripsForDate'], [])
        self.assertIsNone(supplement.added_route('MOKoper:4', THURSDAY))
        self.assertIsNone(supplement.added_route('IJPP:4', THURSDAY))

    def test_otps_stops_list_the_lines_it_adds(self):
        self.assertEqual([r['gtfsId'] for r in supplement.added_lines()['MOKoper:200']], ['MOKoper:2', 'MOKoper:9'])

    def test_a_live_bus_on_a_run_the_correction_replaced_is_superseded(self):
        """N3, 6 Nov: OTP's run of a replaced line loses its board row (corrected_board), so its bus goes on our run."""
        self.assertTrue(supplement.superseded('MOKoper:otp-9', 'MOKoper:9', THURSDAY))
        self.assertFalse(supplement.superseded('MOKoper:otp-9', 'MOKoper:9', SATURDAY))   # OTP's runs that day
        self.assertFalse(supplement.superseded('MOKoper:fix-9-1', 'MOKoper:9', THURSDAY))  # our own run
        self.assertFalse(supplement.superseded('MOKoper:otp-2', 'MOKoper:2', THURSDAY))   # added runs, OTP's kept
        self.assertTrue(supplement.superseded('MOKoper:new-2', 'MOKoper:2', THURSDAY, known=False))  # an id OTP lacks
        self.assertTrue(supplement.superseded('MOKoper:otp-5', 'MOKoper:5', SATURDAY))    # `all`, any day of its dates
        self.assertFalse(supplement.superseded('MOKoper:otp-4', 'MOKoper:4', THURSDAY, known=False))  # a line it leaves alone
        self.assertFalse(supplement.superseded('IJPP:1', 'IJPP:9', THURSDAY, known=False))
        self.assertFalse(supplement.superseded('MOKoper:otp-9', None, THURSDAY))

    def test_vehicles_place_a_superseded_bus_on_the_corrections_run(self):
        """sources._load_vehicles hands such a bus to LooseVehicles naming its line, keeps OTP's run out of the drawn
        runs, files our run id when it is placed and drops the trip id it can't open when it is not."""
        from prestop_api import sources
        from prestop_api.upstream import Snapshot, UpstreamError

        def entity(vid, trip):
            return {'id': vid, 'vehicle': {'vehicle': {'id': vid}, 'trip': {'tripId': trip, 'startDate': '20261105'},
                                          'timestamp': '1', 'position': {'latitude': 45.54, 'longitude': 13.73}}}
        feed = [entity('A', 'MOKoper:otp-9'), entity('B', 'MOKoper:otp-9b'), entity('C', 'MOKoper:otp-4')]
        infos = {'MOKoper:otp-9': {'routeId': 'MOKoper:9'}, 'MOKoper:otp-9b': {'routeId': 'MOKoper:9'}, 'MOKoper:otp-4': {'routeId': 'MOKoper:4'}}
        cache = lambda value: mock.Mock(get=lambda: Snapshot(value, 0), peek=lambda: Snapshot(value, 0))
        failing = mock.Mock(get=mock.Mock(side_effect=UpstreamError('x')))

        def build(entities, updates, trips, *args, **kw):
            return [{'id': e['id'], 'tripId': e['vehicle']['trip']['tripId'], 'mode': 'bus', 'routeName': '9', 'delaySeconds': None} for e in entities]
        seen = {}

        def assign(entities, drawn_runs, *args):
            seen['lines'] = {e['id']: e['vehicle']['trip'].get('routeId') for e in entities}
            seen['drawn'] = list(drawn_runs)
            a = next(e for e in entities if e['id'] == 'A')
            return [(a, 'MOKoper:fix-9-1', 60, 'MOKoper:200', {'stopSequence': 2, 'startDate': '20261105'})]
        with mock.patch.multiple(sources, positions=cache(feed), trip_updates=cache({}), routes=cache({'MOKoper:9': {}, 'MOKoper:4': {}}),
                                 stops=cache({}), patterns=failing, stop_names=lambda: {}, inferred_updates={}), \
                mock.patch.object(sources.trip_info, 'get_many', return_value=infos), \
                mock.patch.object(sources.mapping, 'build_vehicles', build), mock.patch.object(sources.mapping, 'fits_contract', return_value=True), \
                mock.patch.object(sources.loose_vehicles, 'assign', assign), \
                mock.patch('prestop_api.scheduled.vehicles', return_value=[]), mock.patch('prestop_api.scheduled.city_buses', return_value=[]):
            out = {v['id']: v for v in sources._load_vehicles()}
            filed = dict(sources.inferred_updates)
        self.assertEqual(seen['lines'], {'A': 'MOKoper:9', 'B': 'MOKoper:9'})   # line 4 is OTP's: drawn as it is
        self.assertEqual(seen['drawn'], ['MOKoper:otp-4'])
        self.assertEqual((out['A']['tripId'], out['A']['quality'], out['A']['delaySeconds']), ('MOKoper:fix-9-1', 'inferred', 60))
        self.assertIsNone(out['B']['tripId'])
        self.assertEqual(out['C']['tripId'], 'MOKoper:otp-4')
        self.assertEqual(list(filed), ['MOKoper:fix-9-1'])

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
            self.assertEqual(set(supplement.feeds()), {'Jesenice', 'Sevnica'})
        with self.settings(PRESTOP_LOCAL_GTFS=False, PRESTOP_KRANJ_GTFS_URL=''):
            self.assertEqual(supplement.feeds(), {})

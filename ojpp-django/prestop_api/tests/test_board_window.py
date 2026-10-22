from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from prestop_api import sources

LOCAL = ZoneInfo('Europe/Ljubljana')


def at(text):
    return int(datetime.strptime(text, '%Y-%m-%d %H:%M').replace(tzinfo=LOCAL).timestamp())


class BoardWindowTests(SimpleTestCase):
    def test_lists_everything_left_of_the_service_day(self):
        self.assertEqual(sources._until_service_day_end(at('2026-10-10 10:00')), 18 * 3600)

    def test_small_hours_run_on_through_the_coming_day(self):
        # 01:30: the night's last trips, then the whole day that starts at 04:00.
        self.assertEqual(sources._until_service_day_end(at('2026-10-11 01:30')), 26.5 * 3600)
        self.assertEqual(sources._until_service_day_end(at('2026-10-11 00:00')), 28 * 3600)
        self.assertEqual(sources._until_service_day_end(at('2026-10-11 03:30')), 24.5 * 3600)

    def test_small_hours_keep_a_late_train_whose_time_has_passed(self):
        """C8: at 01:10 IC 350 (01:04 at Ljubljana, +35 min) is still to come."""
        from unittest import mock
        from prestop_api.tests.test_mapping import stoptime
        day = at('2026-10-19 00:00')

        def row(trip, dep, rt=None):
            st = stoptime(trip, 'IJPP:x', 'IJPP:y', dep=dep - day, rt=rt - day if rt else None)
            return {**st, 'serviceDay': day}
        rows = [row('IJPP:late', at('2026-10-20 01:04'), at('2026-10-20 01:39')), row('IJPP:gone', at('2026-10-20 01:05')),
                row('IJPP:next', at('2026-10-20 01:30'))]
        otp = mock.Mock()
        otp.query.return_value = {'stop': {'stoptimesWithoutPatterns': rows}}
        with mock.patch.object(sources, 'otp', return_value=otp):
            board = sources._member_board('IJPP:s', 'departure', at('2026-10-20 01:10'), [])
            self.assertEqual(otp.query.call_args[0][1]['start'], at('2026-10-19 23:10'))
            self.assertEqual([r['tripId'] for r in board], ['IJPP:late', 'IJPP:next'])
            # By day OTP has each train's live time on its run: nothing more is asked for
            sources._member_board('IJPP:s', 'departure', at('2026-10-20 10:00'), [])
            self.assertEqual(otp.query.call_args[0][1]['start'], at('2026-10-20 10:00'))

    def test_a_late_run_otp_has_no_live_time_for_stays_until_it_leaves(self):
        """D3: A6295 (IJPP:463770) at Kranj AP, 13:30 and +19 min in the feed, which OTP left out: at 13:42 OTP no
        longer listed it, so the board lost a bus still in its bay (reported: a bus to Bled at Kranj, then it came)."""
        from unittest import mock
        from prestop_api import mapping
        from prestop_api.tests.test_mapping import stoptime
        day, here = at('2026-10-22 00:00'), 'IJPP:1121238'

        def row(trip, dep):
            st = stoptime(trip, here, 'IJPP:y', dep=at(dep) - day)
            return {**st, 'serviceDay': day}
        updates = mapping.trip_update_index([{'tripUpdate': {'trip': {'tripId': 'IJPP:463770', 'startDate': '20261022'}, 'stopTimeUpdate': [
            {'stopSequence': 1, 'stopId': here, 'departure': {'delay': 1149, 'time': str(at('2026-10-22 13:30') + 1149)}}]}}])
        otp = mock.Mock()
        otp.query.return_value = {'stop': {'stoptimesWithoutPatterns': [
            row('IJPP:463770', '2026-10-22 13:30'), row('IJPP:gone', '2026-10-22 13:35'), row('IJPP:next', '2026-10-22 13:50')]}}
        with mock.patch.object(sources, 'otp', return_value=otp), mock.patch('prestop_api.trainlive.trip_updates', return_value=updates):
            board = sources._member_board(here, 'departure', at('2026-10-22 13:42'), [])
            self.assertEqual(otp.query.call_args[0][1]['start'], at('2026-10-22 13:42') - 1149)
            self.assertEqual([(r['tripId'], r['effectiveAt']) for r in board],
                             [('IJPP:463770', '2026-10-22T11:49:09Z'), ('IJPP:next', None)])

    def test_a_terminus_board_is_filled_from_further_pages(self):
        """D3: at Ljubljana AP 80 of OTP's 150 calls end there, so the board had 70 departures to 16:00 and the app,
        given fewer than BOARD_MAX rows, took the rest of the day for done."""
        from prestop_api import mapping
        from prestop_api.tests.test_mapping import stoptime
        day, here = at('2026-10-22 00:00'), 'IJPP:ap'
        calls = []
        for i in range(12):  # every other call ends here
            st = stoptime(f'IJPP:{i}', 'IJPP:x', here if i % 2 else 'IJPP:y', dep=at('2026-10-22 15:00') + 300 * i - day)
            calls.append({**st, 'serviceDay': day})

        def answer(query, v):  # OTP: the first n calls from `start`
            return {'stop': {'stoptimesWithoutPatterns': [c for c in calls if day + c['realtimeDeparture'] >= v['start']][:v['n']]}}
        otp = mock.Mock()
        otp.query.side_effect = answer
        with mock.patch.object(sources, 'otp', return_value=otp), mock.patch.object(sources, 'BOARD_MAX', 4), \
                mock.patch('prestop_api.trainlive.trip_updates', return_value={}), mock.patch.object(sources, '_live_delays', return_value={}):
            board = sources._member_board(here, 'departure', at('2026-10-22 15:00'), [])
            self.assertEqual([r['tripId'] for r in board], ['IJPP:0', 'IJPP:2', 'IJPP:4', 'IJPP:6', 'IJPP:8', 'IJPP:10'])
            self.assertEqual([c[0][1]['n'] for c in otp.query.call_args_list], [4, 8])
            # A stop whose day fits one page is asked once.
            otp.query.reset_mock()
            self.assertEqual(len(sources._member_board(here, 'departure', at('2026-10-22 15:41'), [])), 1)
            self.assertEqual(otp.query.call_count, 1)
            # Rows by the time they go: a late bus (its timetable 15:00, +50 min) is the one past the cap.
            rows = [{'id': str(i), 'scheduledAt': mapping.iso(at('2026-10-22 15:00') + 300 * i), 'effectiveAt': None} for i in range(6)]
            rows[0]['effectiveAt'] = mapping.iso(at('2026-10-22 15:50'))
            drops: list = []
            self.assertEqual([r['id'] for r in sources._capped(rows, drops)], ['1', '2', '3', '4'])
            self.assertEqual([d['item']['id'] for d in drops], ['0', '5'])


class OldTripIdTests(SimpleTestCase):
    """D3: the feed names some runs by an older timetable's trip id, so OTP had no live data for the run and its board
    lost it when late. IJPP:445124 is OTP's A6105 IJPP:480671 from stop 1 at 14:40; its delays are against the older
    times (+253 s at 14:42:49, where OTP's run has 14:43)."""
    DAY = at('2026-10-22 00:00')

    def setUp(self):
        sources._old_ids.clear()

    @staticmethod
    def call(seq, stop, live, delay):
        return {'stopSequence': seq, 'stopId': stop, 'departure': {'delay': delay, 'time': str(live)}}

    def stoptime(self, trip, position, scheduled):
        return {'serviceDay': self.DAY, 'scheduledArrival': scheduled - self.DAY, 'scheduledDeparture': scheduled - self.DAY,
                'stopPosition': position, 'trip': {'gtfsId': trip}}

    def calls(self, *stops):
        return [{'stopPosition': i, 'stop': {'gtfsId': stop}, 'serviceDay': self.DAY, 'scheduledArrival': t - self.DAY,
                 'scheduledDeparture': t - self.DAY} for i, (stop, t) in enumerate(stops, 1)]

    def otp(self, boards, trips):
        otp = mock.Mock()
        otp.query.side_effect = lambda q, v: ({'trip': {'stoptimesForDate': trips[v['id']]}} if 'date' in v
                                              else {'stop': {'stoptimesWithoutPatterns': boards[v['id']]}})
        return otp

    def test_an_update_under_an_old_trip_id_is_filed_under_otps_run_with_otps_times(self):
        from prestop_api import mapping
        t = lambda hm, s=0: at(f'2026-10-22 {hm}') + s
        old = {'tripUpdate': {'trip': {'tripId': 'IJPP:445124', 'startDate': '20261022'}, 'stopTimeUpdate': [
            self.call(1, 'IJPP:1123958', t('14:40'), 0), self.call(2, 'IJPP:b', t('14:42', 49), 253), self.call(3, 'IJPP:c', t('14:44', 12), 253)]}}
        index = mapping.trip_update_index([old])
        # Another line starts at the same stop and time, a third passes it then: only A6105 calls at the update's stops.
        boards = {'IJPP:1123958': [self.stoptime('IJPP:480671', 1, t('14:40')), self.stoptime('IJPP:other', 1, t('14:40')),
                                   self.stoptime('IJPP:through', 7, t('14:40'))]}
        trips = {'IJPP:480671': self.calls(('IJPP:1123958', t('14:40')), ('IJPP:b', t('14:43')), ('IJPP:c', t('14:45'))),
                 'IJPP:other': self.calls(('IJPP:1123958', t('14:40')), ('IJPP:x', t('14:44')), ('IJPP:y', t('14:46')))}
        with mock.patch.object(sources, 'otp', return_value=self.otp(boards, trips)),                 mock.patch.object(sources.trip_info, 'get_many', return_value={'IJPP:445124': {}}):
            index = sources._with_old_ids(index)
        run = index['IJPP:480671']
        self.assertEqual((run['trip']['tripId'], run['oldId']), ('IJPP:480671', 'IJPP:445124'))
        self.assertEqual([mapping.update_delay(u) for u in run['updates']], [0, -11, -48])
        self.assertEqual(mapping.update_delay(index['IJPP:445124']['updates'][1]), 253)  # the feed's own stays as sent
        # OTP's run at the second stop now leaves at the live time
        self.assertEqual(mapping.update_run(run, 'IJPP:b', t('14:40'), t('14:43'), False, t('14:43'), self.DAY, 2), (True, t('14:42', 49)))

    def test_no_single_run_known_trips_and_runs_with_their_own_update_stay_as_they_are(self):
        from prestop_api import mapping
        first, second = at('2026-10-22 14:35'), at('2026-10-22 14:40')
        def update(trip, stops):
            calls = [self.call(1, stops[0], first, 0)] + ([self.call(2, stops[1], second + 300, 300)] if len(stops) > 1 else [])
            return {'tripUpdate': {'trip': {'tripId': trip, 'startDate': '20261022'}, 'stopTimeUpdate': calls}}
        index = mapping.trip_update_index([update('IJPP:two', ['IJPP:r', 'IJPP:s']), update('IJPP:none', ['IJPP:x', 'IJPP:y']),
                                           update('IJPP:one', ['IJPP:r']), update('IJPP:known', ['IJPP:r', 'IJPP:s']),
                                           update('IJPP:old', ['IJPP:m', 'IJPP:n']), update('IJPP:own', ['IJPP:m', 'IJPP:n'])])
        same = self.calls(('IJPP:r', first), ('IJPP:s', second))  # two runs alike at every stop: no telling which
        boards = {'IJPP:r': [self.stoptime('IJPP:a', 1, first), self.stoptime('IJPP:b', 1, first)], 'IJPP:x': [],
                  'IJPP:m': [self.stoptime('IJPP:own', 1, first)]}
        trips = {'IJPP:a': same, 'IJPP:b': same, 'IJPP:own': self.calls(('IJPP:m', first), ('IJPP:n', second))}
        otp = self.otp(boards, trips)
        infos = {'IJPP:two': {}, 'IJPP:none': {}, 'IJPP:one': {}, 'IJPP:old': {}, 'IJPP:known': {'routeId': 'IJPP:r1'}, 'IJPP:own': {'routeId': 'IJPP:r2'}}
        with mock.patch.object(sources, 'otp', return_value=otp), mock.patch.object(sources.trip_info, 'get_many', return_value=infos):
            out = sources._with_old_ids(dict(index))
            self.assertEqual(set(out), set(index))
            self.assertIs(out['IJPP:own'], index['IJPP:own'])
            # Each run is looked up once; one stop alone is never enough
            asked = otp.query.call_count
            sources._with_old_ids(dict(index))
            self.assertEqual(otp.query.call_count, asked)
        self.assertEqual(sources._old_ids[('IJPP:one', '20261022')], None)

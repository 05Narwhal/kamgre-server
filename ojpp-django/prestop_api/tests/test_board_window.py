from datetime import datetime
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

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

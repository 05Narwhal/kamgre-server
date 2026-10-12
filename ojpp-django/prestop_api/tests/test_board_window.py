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

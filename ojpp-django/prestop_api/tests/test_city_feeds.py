"""Spec 2026-11-04 M1: a city feed with no trips on a coming day it normally runs raises an alarm in /health, and
Marprom's weekday timetable (published feed ended 31 Aug) reaches the boards."""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import city_feeds, supplement
from prestop_api.tests.test_views import fixed

WED = date(2026, 11, 4)


def routes(**feeds):
    """OTP's answer: per feed, its trips on each asked day (d0, d1, ... in the order asked)."""
    return {'routes': [{'gtfsId': f'{feed}:1', 'patterns': [{f'd{n}': [{'gtfsId': f'{feed}:t'}] * count for n, count in enumerate(counts)}]}
                       for feed, counts in feeds.items()]}


def real(name):
    return supplement.parse(name, supplement._local_zip(str(supplement.LOCAL_GTFS / name)))


class DaysTests(SimpleTestCase):
    def test_the_next_and_the_last_weekday_and_saturday_of_the_window(self):
        self.assertEqual(city_feeds.days_to_check(WED), [('weekday', date(2026, 11, 5)), ('weekday', date(2026, 11, 18)),
                                                         ('saturday', date(2026, 11, 7)), ('saturday', date(2026, 11, 14))])

    def test_public_holidays_are_not_asked(self):
        days = city_feeds.days_to_check(date(2026, 12, 24))  # Fri 25 and Sat 26 Dec are holidays
        self.assertEqual(dict(days[:1]), {'weekday': date(2026, 12, 28)})
        self.assertNotIn(date(2026, 12, 25), [d for _, d in days])
        self.assertNotIn(date(2026, 12, 26), [d for _, d in days])


class AlarmTests(SimpleTestCase):
    def check(self, answer, own=None, today=WED):
        with mock.patch.object(city_feeds, 'FEEDS', {'MARPROM': True, 'CELEBUS': False, 'Sevnica': False}), \
                mock.patch.object(supplement, '_feeds', return_value=own or {}), \
                mock.patch.object(city_feeds, 'otp') as otp:
            otp.return_value.query.return_value = answer
            return city_feeds.check(today)

    def empty(self, result):
        return [(e['feed'], e['kind'], e['day']) for e in result['empty']]

    def test_marprom_as_it_was_no_weekday_trips_but_a_full_saturday(self):
        result = self.check(routes(MARPROM=[0, 0, 896, 896], CELEBUS=[9, 9, 0, 0], Sevnica=[4, 4, 0, 0]))
        self.assertEqual(self.empty(result), [('MARPROM', 'weekday', '2026-11-05'), ('MARPROM', 'weekday', '2026-11-18')])

    def test_a_weekday_only_feed_is_not_called_empty_on_a_saturday(self):
        result = self.check(routes(MARPROM=[9, 9, 9, 9], CELEBUS=[9, 9, 0, 0], Sevnica=[4, 4, 0, 0]))
        self.assertEqual(result['empty'], [])
        self.assertEqual(result['trips']['CELEBUS'], [9, 9, 0, 0])

    def test_a_feed_ending_inside_the_window_is_called_before_it_ends(self):
        result = self.check(routes(MARPROM=[9, 0, 9, 9], CELEBUS=[9, 9, 0, 0], Sevnica=[4, 4, 0, 0]))
        self.assertEqual(self.empty(result), [('MARPROM', 'weekday', '2026-11-18')])

    def test_a_feed_gone_from_otp_is_empty(self):
        result = self.check(routes(CELEBUS=[9, 9, 0, 0], Sevnica=[4, 4, 0, 0]))
        self.assertEqual(self.empty(result)[0], ('MARPROM', 'weekday', '2026-11-05'))
        self.assertEqual(len(result['empty']), 4)

    def test_a_feed_read_here_counts_from_its_own_calendar_not_otps(self):
        result = self.check(routes(MARPROM=[0, 0, 0, 0], CELEBUS=[9, 9, 0, 0]), own={'MARPROM': real('MARPROM'), 'Sevnica': real('Sevnica')})
        self.assertEqual(result['empty'], [])
        self.assertGreater(result['trips']['MARPROM'][0], 1000)
        self.assertGreater(result['trips']['Sevnica'][0], 0)

    def test_a_corrections_own_runs_count_on_top_of_otps(self):
        from prestop_api.tests.test_supplement import correction  # Koper's: two working-day runs, nothing at weekends
        with mock.patch.object(city_feeds, 'FEEDS', {'MOKoper': True}),                 mock.patch.object(supplement, '_feeds', return_value={'MOKoper': correction()}),                 mock.patch.object(city_feeds, 'otp') as otp:
            otp.return_value.query.return_value = routes(MOKoper=[5, 5, 0, 0])
            result = city_feeds.check(WED)
        self.assertEqual(result['trips']['MOKoper'], [7, 7, 0, 0])
        self.assertEqual(self.empty(result), [('MOKoper', 'saturday', '2026-11-07'), ('MOKoper', 'saturday', '2026-11-14')])

    def test_only_feeds_otp_answers_for_are_asked_of_it(self):
        with mock.patch.object(city_feeds, 'FEEDS', {'MARPROM': True}), mock.patch.object(supplement, '_feeds', return_value={'MARPROM': real('MARPROM')}), \
                mock.patch.object(city_feeds, 'otp') as otp:
            city_feeds.check(WED)
        otp.return_value.query.assert_not_called()

    def test_every_listed_feed_is_named_as_otp_or_the_folder_names_it(self):
        self.assertIn('MARPROM', city_feeds.FEEDS)
        self.assertIn('Sevnica', city_feeds.FEEDS)
        self.assertIn('Jesenice', city_feeds.FEEDS)


class HealthTests(SimpleTestCase):
    def test_health_carries_the_last_check_and_nothing_before_the_first(self):
        result = {'checkedAt': '2026-11-04T01:00:00Z', 'days': [], 'trips': {}, 'empty': []}
        with mock.patch.object(city_feeds, 'checked', fixed(result)):
            self.assertEqual(city_feeds.latest(), result)
        none = mock.Mock()
        none.peek.return_value = None
        with mock.patch.object(city_feeds, 'checked', none):
            self.assertIsNone(city_feeds.latest())

    def test_the_warmer_starts_a_due_check_in_its_own_thread(self):
        stale = fixed({}, age=city_feeds.checked.ttl)
        with mock.patch.object(city_feeds, 'checked', stale), mock.patch.object(stale, '_refresh_in_background') as start:
            city_feeds.warm()
            start.assert_called_once()


class MarpromWeekdayBoardTests(SimpleTestCase):
    def test_a_weekday_board_has_marproms_buses(self):
        monday = date(2026, 11, 9)
        with mock.patch.object(supplement, '_feeds', return_value={'MARPROM': real('MARPROM')}):
            rows = supplement.stoptimes('MARPROM:192', supplement.day_start(monday) + 8 * 3600, 3600, 50, {})
        lines = {r['trip']['route']['shortName'] for r in rows}
        self.assertGreater(len(rows), 10)
        self.assertIn('G1', lines)

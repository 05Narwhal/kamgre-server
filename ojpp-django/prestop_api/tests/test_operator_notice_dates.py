from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from prestop_api import operator_notices as notices

LOCAL = ZoneInfo('Europe/Ljubljana')
POSTED = datetime(2026, 10, 26, 10, tzinfo=LOCAL)


def days(title, text=''):
    start, end = notices.window(title, text, POSTED)
    return datetime.fromtimestamp(start, LOCAL).strftime('%d.%m.'), datetime.fromtimestamp(end, LOCAL).strftime('%d.%m.')


class WindowTests(SimpleTestCase):
    def test_two_whole_dates_joined_by_and_are_not_the_day_of_one_and_the_month_of_the_other(self):
        """Arriva's post of 26 Oct stayed up until 10 November."""
        self.assertEqual(days('Brezplačni avtobusni prevoz do koprskega pokopališča 31. 10. in 1. 11. 2026'), ('31.10.', '01.11.'))

    def test_two_days_of_one_month_still_are(self):
        self.assertEqual(days('Zapora 17. in 18. 10. 2026'), ('17.10.', '18.10.'))

    def test_a_span_of_days_of_one_month_still_is(self):
        self.assertEqual(days('Popolna zapora ceste, 16.–17. 11. 2026'), ('16.11.', '17.11.'))

    def test_a_notice_for_one_named_day_ends_that_day(self):
        self.assertEqual(days('Popolna zapora Delavske ceste v Stražišču (28.10.2026)'), ('28.10.', '28.10.'))

    def test_a_weekday_starting_with_s_or_do_is_no_from_or_until(self):
        """Arriva's post of 26 Oct: "v sredo, 28. 10. 2026 (cel dan)" stayed up until 11 November."""
        self.assertEqual(days('Popolna zapora (28.10.2026)', 'zapora Delavske ceste v Stražišču in sicer v sredo, 28. 10. 2026 (cel dan).'), ('28.10.', '28.10.'))
        self.assertEqual(days('Zapora', 'Zapora bo dopoldne, 28. 10. 2026.'), ('28.10.', '28.10.'))

    def test_from_a_weekday_still_is_from(self):
        self.assertEqual(days('Sprememba odhodov', 'Obveščamo vas, da se s ponedeljkom, 2. 11. 2026, odhodi premaknejo.'), ('02.11.', '16.11.'))
        self.assertEqual(days('Zapora', 'Zapora bo od torka, 3. 11. 2026.'), ('03.11.', '17.11.'))
        self.assertEqual(days('Zapora', 'Zapora bo do petka, 6. 11. 2026.'), ('26.10.', '06.11.'))


class NoticeTests(SimpleTestCase):
    def test_a_service_change_is_a_notice_and_news_is_not(self):
        self.assertTrue(notices.NOTICE.search('dodatna petkova odhoda na relaciji maribor'))
        self.assertTrue(notices.NOTICE.search('sprememba odhodov na relaciji'))
        self.assertFalse(notices.NOTICE.search('na festival brezplacno z avtobusom'))

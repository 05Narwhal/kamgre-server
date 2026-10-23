"""Earlier / later connections: OTP planConnection cursors through the facade."""
from django.test import SimpleTestCase

from prestop_api import journeys
from prestop_api.tests.test_insane import ride
from prestop_api.tests.test_journey_alerts import request

class JourneyPageTests(SimpleTestCase):
    def test_page_cursor_goes_to_otp_and_cursors_come_back(self):
        v = journeys.otp_variables(request(pageCursor='abc'))
        self.assertEqual((v['after'], v['first']), ('abc', 5))  # OTP planConnection uses before/after cursors
        page = journeys.page_info({'planConnection': {'pageInfo': {'startCursor': 's', 'endCursor': 'e', 'hasPreviousPage': True, 'hasNextPage': False}}})
        self.assertEqual(page, {'previous': 's', 'next': None})

    def test_earlier_page_asks_for_the_last_connections_before_the_cursor(self):
        v = journeys.otp_variables(request(pageCursor='s', pageDirection='earlier'))
        self.assertEqual((v['before'], v['last']), ('s', 5))
        self.assertNotIn('first', v)
        self.assertNotIn('after', v)

    def test_no_cursor_is_a_first_page(self):
        v = journeys.otp_variables(request())
        self.assertNotIn('after', v)
        self.assertNotIn('before', v)
        self.assertEqual(journeys.page_info({}), {'previous': None, 'next': None})

    def test_bad_page_parameters_are_rejected(self):
        for bad in ({'pageCursor': 5}, {'pageCursor': 'x' * 5000}, {'pageCursor': 'x', 'pageDirection': 'sideways'}):
            with self.assertRaises(journeys.RequestError):
                request(**bad)


def empty():
    return {'planConnection': {'edges': [], 'pageInfo': {}}}


def one_ride():
    return {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [ride('04:10:00', '05:00:00', 'IJPP:first')]}}],
                               'pageInfo': {'hasNextPage': True, 'endCursor': 'more', 'hasPreviousPage': True, 'startCursor': 'back'}}}


class Script:
    """Answers OTP queries from a list, remembering the variables asked."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, _query, variables):
        self.asked.append(variables)
        return self.answers.pop(0) if self.answers else empty()


class PagesAcrossDaysTests(SimpleTestCase):
    """Later after the day's last trip is the next service day's first trips; Earlier, the day before's last."""

    def test_a_cursor_without_cursors_of_its_own_offers_the_neighbouring_days(self):
        req = request(dateTime='2099-10-09T10:00:00+02:00')
        self.assertEqual(journeys.page_info(empty(), req), {'previous': '~-1a:', 'next': '~1d:'})
        self.assertEqual(journeys.page_info(empty()), {'previous': None, 'next': None})  # no request: OTP's cursors only

    def test_otp_cursors_stay_as_they_are_on_the_day_asked_for(self):
        req = request(dateTime='2099-10-09T10:00:00+02:00')
        self.assertEqual(journeys.page_info(one_ride(), req), {'previous': 'back', 'next': 'more'})

    def test_later_past_the_last_trip_returns_the_next_days_first_trips(self):
        req = request(dateTime='2099-10-09T21:00:00+02:00', pageCursor='abc', pageDirection='later')
        otp = Script(empty(), one_ride())
        data = journeys.plan(req, otp)
        self.assertEqual(otp.asked[0]['after'], 'abc')
        self.assertEqual(otp.asked[1]['dateTime'], {'earliestDeparture': '2099-10-10T04:00:00+02:00'})
        self.assertEqual(len(journeys._edges(data)), 1)
        self.assertEqual(journeys.page_info(data, req), {'previous': '~1d:back', 'next': '~1d:more'})

    def test_a_cursor_from_the_next_day_goes_on_from_there(self):
        req = request(dateTime='2099-10-09T21:00:00+02:00', pageCursor='~1d:more', pageDirection='later')
        otp = Script(empty(), one_ride())
        journeys.plan(req, otp)
        self.assertEqual(otp.asked[0]['after'], 'more')
        self.assertEqual(otp.asked[1]['dateTime'], {'earliestDeparture': '2099-10-11T04:00:00+02:00'})  # the day after that

    def test_earlier_before_the_first_trip_returns_the_day_befores_last_trips(self):
        req = request(dateTime='2099-10-09T05:00:00+02:00', pageCursor='abc', pageDirection='earlier')
        otp = Script(empty(), one_ride())
        data = journeys.plan(req, otp)
        self.assertEqual(otp.asked[0]['before'], 'abc')
        self.assertEqual(otp.asked[1]['dateTime'], {'latestArrival': '2099-10-09T04:00:00+02:00'})  # the end of 8 Oct's service day
        self.assertEqual(journeys.page_info(data, req)['previous'], '~-1a:back')

    def test_arriving_by_a_time_later_pages_also_go_to_the_next_day(self):
        req = request(timeMode='arriveBy', dateTime='2099-10-09T22:00:00+02:00', pageCursor='abc', pageDirection='later')
        otp = Script(empty(), one_ride())
        journeys.plan(req, otp)
        self.assertEqual(otp.asked[1]['dateTime'], {'earliestDeparture': '2099-10-10T04:00:00+02:00'})

    def test_it_gives_up_after_a_few_empty_days_and_offers_the_way_on(self):
        req = request(dateTime='2099-10-09T21:00:00+02:00', pageCursor='abc', pageDirection='later')
        otp = Script()
        data = journeys.plan(req, otp)
        self.assertEqual(len(otp.asked), journeys.PAGE_HOPS + 1)
        self.assertEqual(journeys._edges(data), [])
        self.assertEqual(journeys.page_info(data, req)['next'], '~3d:')

    def test_a_week_out_or_a_day_gone_by_is_not_offered(self):
        req = request(dateTime='2099-10-09T21:00:00+02:00')
        now = journeys._ts('2099-10-09T12:00:00+02:00')
        self.assertTrue(journeys._day_allowed(req, 7, now))
        self.assertFalse(journeys._day_allowed(req, 8, now))
        self.assertFalse(journeys._day_allowed(req, -1, now))  # yesterday is not planned
        far = request(dateTime='2099-10-09T21:00:00+02:00', pageCursor='~7d:abc', pageDirection='later')
        data = journeys.plan(far, Script(empty()))
        self.assertEqual(journeys.page_info(data, far)['next'], None)

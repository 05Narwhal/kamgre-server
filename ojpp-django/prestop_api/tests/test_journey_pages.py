"""Earlier / later connections: OTP planConnection cursors through the facade."""
from django.test import SimpleTestCase

from prestop_api import journeys
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

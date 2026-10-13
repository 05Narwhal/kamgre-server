"""Every connection that day counts, not only those inside the window OTP picks on its own (journeys.search)."""
from datetime import datetime

from django.test import SimpleTestCase

from prestop_api import journeys
from prestop_api.tests.test_insane import request, ride

DEFAULT_WINDOW = 70 * 60  # what OTP chose for Kropa → Ljubljana


class FakeOtp:
    """OTP's window rules: departures in [time, time + window], or arrivals in [time - window, time]; the `first`
    nearest to the time; searchWindowUsed says how long the window was."""

    def __init__(self, *rides):
        self.rides = rides
        self.asked = []

    def __call__(self, _query, variables):
        self.asked.append(variables)
        window = journeys._seconds(variables.get('searchWindow')) or DEFAULT_WINDOW
        stamp = variables['dateTime']
        if 'earliestDeparture' in stamp:
            at = datetime.fromisoformat(stamp['earliestDeparture']).timestamp()
            found = sorted((r for r in self.rides if at <= journeys._when(r['start']) <= at + window), key=lambda r: journeys._when(r['start']))
        else:
            at = datetime.fromisoformat(stamp['latestArrival']).timestamp()
            found = sorted((r for r in self.rides if at - window <= journeys._when(r['end']) <= at), key=lambda r: -journeys._when(r['end']))
        found = found[:variables['first']]
        hours, rest = divmod(window, 3600)
        return {'planConnection': {
            'routingErrors': [] if found else [{'code': 'NO_TRANSIT_CONNECTION_IN_SEARCH_WINDOW'}],
            'pageInfo': {'searchWindowUsed': f'PT{hours}H{rest // 60}M', 'hasNextPage': True, 'endCursor': 'next'},
            'edges': [{'node': {'walkTime': 0, 'legs': [r]}} for r in found]}}


def trips(data):
    return [e['node']['legs'][0]['trip']['gtfsId'] for e in data['planConnection']['edges']]


class DayWindowTests(SimpleTestCase):
    def test_arrive_by_finds_a_connection_long_before_the_time(self):
        otp = FakeOtp(ride('12:00:00', '13:30:00', 'IJPP:only'))
        req = request(insane=False, timeMode='arriveBy', dateTime='2026-10-09T15:00:00+02:00')
        data = journeys.plan(req, otp)
        self.assertEqual(trips(data), ['IJPP:only'])
        [j] = journeys.build_journeys(data, req, [])
        self.assertEqual(j['effectiveArrival'], '2026-10-09T13:30:00+02:00')
        self.assertEqual(otp.asked[-1]['searchWindow'], f'PT{11 * 3600}S')  # back to 04:00

    def test_depart_at_finds_a_late_evening_connection(self):
        otp = FakeOtp(ride('22:40:00', '23:30:00', 'IJPP:late'))
        data = journeys.plan(request(insane=False, dateTime='2026-10-09T08:00:00+02:00'), otp)
        self.assertEqual(trips(data), ['IJPP:late'])
        self.assertEqual(otp.asked[-1]['searchWindow'], f'PT{20 * 3600}S')  # on to 04:00 the next morning

    def test_the_nearest_connections_come_first(self):
        otp = FakeOtp(*(ride(f'{h:02d}:00:00', f'{h:02d}:30:00', f'IJPP:{h}') for h in (6, 8, 10, 12, 14, 16, 18)))
        data = journeys.plan(request(insane=False, timeMode='arriveBy', dateTime='2026-10-09T15:00:00+02:00'), otp)
        self.assertEqual(trips(data), ['IJPP:14', 'IJPP:12', 'IJPP:10', 'IJPP:8', 'IJPP:6'])
        self.assertEqual(trips(journeys.plan(request(insane=False, dateTime='2026-10-09T07:00:00+02:00'), FakeOtp(*otp.rides))),
                         ['IJPP:8', 'IJPP:10', 'IJPP:12', 'IJPP:14', 'IJPP:16'])

    def test_a_full_answer_is_one_request(self):
        otp = FakeOtp(*(ride(f'10:{m:02d}:00', f'10:{m + 5:02d}:00', f'IJPP:{m}') for m in range(0, 50, 10)))
        journeys.plan(request(insane=False), otp)
        self.assertEqual(len(otp.asked), 1)
        self.assertNotIn('searchWindow', otp.asked[0])

    def test_a_page_keeps_its_window(self):
        otp = FakeOtp()
        journeys.plan(request(insane=False, pageCursor='next'), otp)
        self.assertEqual(len(otp.asked), 1)

    def test_the_window_never_passes_otp_s_limit_or_the_day(self):
        at = lambda when, mode='departAt': journeys.day_window(request(insane=False, dateTime=when, timeMode=mode))
        self.assertEqual(at('2026-10-09T01:00:00+02:00'), journeys.MAX_SEARCH_WINDOW)  # the night runs into the coming day
        self.assertEqual(at('2026-10-09T01:00:00+02:00', 'arriveBy'), 21 * 3600)    # back to 04:00 the day before
        self.assertEqual(at('2026-10-09T04:30:00+02:00', 'arriveBy'), 3600)          # at least an hour
        self.assertEqual(at('2026-10-09T10:00:00Z'), 16 * 3600)                      # UTC in, local day out
        self.assertEqual(journeys._seconds('PT1H10M'), 4200)
        self.assertEqual(journeys._seconds(None), 0)

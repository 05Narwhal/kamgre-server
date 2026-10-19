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

    def test_nothing_within_the_usual_limits_asks_with_wider_ones(self):
        """Kropa → Ljubljana after the last bus: only a brisk walk to the train at Otoče gets there."""
        normal = FakeOtp()
        wider = FakeOtp(ride('20:22:00', '21:56:00', 'IJPP:train'))
        query = lambda q, v: (wider if 'walk' in v['preferences']['street'] else normal)(q, v)
        req = request(insane=False, slack=180, dateTime='2026-10-09T20:00:00+02:00')
        data = journeys.plan(req, query)
        self.assertEqual(trips(data), ['IJPP:train'])
        self.assertTrue(data['wider'])
        self.assertEqual(wider.asked[0]['preferences']['transit']['transfer']['slack'], 'PT0S')
        self.assertEqual(wider.asked[0]['preferences']['street']['walk']['speed'], journeys.INSANE_WALK_SPEED)
        self.assertEqual(journeys.page_info(data)['next'], 'wider:next')
        # Its later page keeps the wider limits.
        later = journeys.plan(request(insane=False, slack=180, pageCursor='wider:next'), query)
        self.assertTrue(later['wider'])
        self.assertEqual(wider.asked[-1]['after'], 'next')
        # A one-minute change found that way is still rated against the rider's 3 min buffer.
        tight = {'wider': True, 'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [
            ride('20:22:00', '20:40:00', 'IJPP:t1'), ride('20:41:00', '21:56:00', 'IJPP:t2', frm='IJPP:b', to='IJPP:c')]}}]}}
        [j] = journeys.build_journeys(tight, req, [])
        self.assertEqual(j['transfers'][0]['status'], 'tight')

    def test_found_within_the_usual_limits_or_insane_is_not_widened(self):
        otp = FakeOtp(ride('20:22:00', '21:56:00', 'IJPP:bus'))
        self.assertNotIn('wider', journeys.plan(request(insane=False, dateTime='2026-10-09T20:00:00+02:00'), otp))
        self.assertTrue(all('walk' not in v['preferences']['street'] for v in otp.asked))
        empty = FakeOtp()
        self.assertNotIn('wider', journeys.plan(request(dateTime='2026-10-09T20:00:00+02:00'), empty))
        self.assertTrue(all('walk' in v['preferences']['street'] for v in empty.asked))  # Insane asked once, as itself

    def test_the_window_never_passes_otp_s_limit_or_the_day(self):
        at = lambda when, mode='departAt': journeys.day_window(request(insane=False, dateTime=when, timeMode=mode))
        self.assertEqual(at('2026-10-09T01:00:00+02:00'), journeys.MAX_SEARCH_WINDOW)  # the night runs into the coming day
        self.assertEqual(at('2026-10-09T01:00:00+02:00', 'arriveBy'), 21 * 3600)    # back to 04:00 the day before
        self.assertEqual(at('2026-10-09T04:30:00+02:00', 'arriveBy'), 3600)          # at least an hour
        self.assertEqual(at('2026-10-09T10:00:00Z'), 16 * 3600)                      # UTC in, local day out
        self.assertEqual(journeys._seconds('PT1H10M'), 4200)
        self.assertEqual(journeys._seconds(None), 0)


class ShiftedSearchTests(SimpleTestCase):
    """A search moved for a replacement bus (searchShift) never costs the connections at the asked time."""

    def test_a_city_trip_near_the_station_keeps_its_connections(self):
        # 20 Oct, Tivoli → Fužine at 08:00: moved 49 min earlier, OTP's page was full of buses before 08:00 and the
        # answer came back empty once those were dropped.
        otp = FakeOtp(*(ride(f'{h:02d}:{m:02d}:00', f'{h:02d}:{m + 5:02d}:00', f'LPP:{h}{m:02d}') for h in (7, 8) for m in range(0, 55, 6)))
        req = request(insane=False, dateTime='2026-10-09T08:00:00+02:00')
        data = journeys.plan({**req, 'searchShift': 2940}, otp)
        self.assertEqual([v['dateTime'] for v in otp.asked], [{'earliestDeparture': '2026-10-09T07:11:00+02:00'},
                                                              {'earliestDeparture': '2026-10-09T08:00:00+02:00'}])
        self.assertEqual(trips(data)[:5], ['LPP:800', 'LPP:806', 'LPP:812', 'LPP:818', 'LPP:824'])  # the asked time's first
        self.assertEqual(len(journeys.within_time(journeys.build_journeys(data, {**req, 'searchShift': 2940}, []), {**req, 'searchShift': 2940})), 5)

    def test_a_moved_search_with_a_page_in_time_is_one_request(self):
        otp = FakeOtp(*(ride(f'10:{m:02d}:00', f'10:{m + 5:02d}:00', f'IJPP:{m}') for m in range(0, 50, 10)))
        journeys.plan({**request(insane=False), 'searchShift': 600}, otp)
        self.assertEqual(len(otp.asked), 1)

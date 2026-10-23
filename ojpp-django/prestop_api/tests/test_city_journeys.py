"""City buses OTP does not know, in journeys (city_journeys.py): inside a town, joined to OTP's trains, via a station."""
import io
import zipfile
from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import city_journeys, journeys, supplement, trainlive
from prestop_api import operators as companies

LOCAL = journeys.LOCAL
# One street west to east (A-D, ~770 m apart), a station north of B, and a line north from B past the station.
STOPS = {'A': ('Zahod', 46.4300, 14.0000), 'B': ('Center', 46.4300, 14.0100), 'C': ('Bolnica', 46.4300, 14.0200),
         'D': ('Vzhod', 46.4300, 14.0300), 'S': ('Postaja', 46.4380, 14.0100), 'F': ('Planina', 46.4600, 14.0100)}
FILES = {
    'agency.txt': 'agency_id,agency_name,agency_url,agency_timezone\narriva,Arriva,https://arriva.si/,Europe/Ljubljana\n',
    'routes.txt': 'route_id,agency_id,route_short_name,route_long_name,route_type\n1,arriva,1,Zahod - Vzhod,3\n2,arriva,2,Center - Planina,3\n',
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon\n' + ''.join(f'{k},{n},{lat},{lon}\n' for k, (n, lat, lon) in STOPS.items()),
    'trips.txt': ('route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n'
                  '1,wd,1-0800,Vzhod,0,\n1,wd,1-0900,Vzhod,0,\n2,wd,2-0810,Planina,0,\n'),
    'stop_times.txt': ('trip_id,arrival_time,departure_time,stop_id,stop_sequence\n'
                       '1-0800,08:00:00,08:00:00,A,1\n1-0800,08:03:00,08:03:00,B,2\n1-0800,08:06:00,08:06:00,C,3\n1-0800,08:09:00,08:09:00,D,4\n'
                       '1-0900,09:00:00,09:00:00,A,1\n1-0900,09:03:00,09:03:00,B,2\n1-0900,09:06:00,09:06:00,C,3\n1-0900,09:09:00,09:09:00,D,4\n'
                       '2-0810,08:10:00,08:10:00,B,1\n2-0810,08:14:00,08:14:00,S,2\n2-0810,08:22:00,08:22:00,F,3\n'),
    'calendar.txt': ('service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n'
                     'wd,1,1,1,1,1,0,0,20261001,20270624\n'),
}


def feed():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, text in FILES.items():
            z.writestr(name, text)
    return supplement.parse('Jesenice', buf.getvalue())


def place(key: str, north: float = 0.0, name: str = '', east: float = 0.0) -> dict:
    _, lat, lon = STOPS[key]
    return {'name': name or key, 'latitude': lat + north, 'longitude': lon + east}


def request(origin: dict, destination: dict, at: str = '07:50', mode: str = 'departAt', **extra) -> dict:
    body = {'origin': origin, 'destination': destination, 'dateTime': f'2026-10-26T{at}:00+01:00', 'timeMode': mode,
            'modes': ['walk', 'bus', 'rail'], **extra}
    return journeys.parse_request(body, True)


def stamp(hm: str) -> str:
    return f'2026-10-26T{hm}:00+01:00'


def otp_end(name: str, lat: float, lon: float, stop: str = None) -> dict:
    return {'name': name, 'lat': lat, 'lon': lon, 'stop': {'gtfsId': stop, 'platformCode': None} if stop else None}


def train(arrive: str, start: str = '07:20', to=('Jesenice ŽP', 46.4381, 14.0101, 'IJPP:9000')) -> dict:
    return {'mode': 'RAIL', 'transitLeg': True, 'realtimeState': 'SCHEDULED', 'interlineWithPreviousLeg': False, 'duration': 2100,
            'distance': 30000, 'start': {'scheduledTime': stamp(start), 'estimated': None}, 'end': {'scheduledTime': stamp(arrive), 'estimated': None},
            'from': otp_end('Ljubljana', 46.058, 14.51, 'IJPP:1'), 'to': otp_end(*to),
            'route': {'gtfsId': 'IJPP:R1', 'shortName': 'LP 2404', 'longName': '', 'mode': 'RAIL', 'agency': {'gtfsId': 'IJPP:SZ'}},
            'headsign': 'Jesenice', 'trip': {'gtfsId': 'IJPP:T1', 'tripHeadsign': 'Jesenice', 'blockId': None,
                                             'departureStoptime': {'scheduledDeparture': 26400}, 'stoptimes': []},
            'legGeometry': {'points': ''}, 'alerts': [], 'intermediatePlaces': []}


def walk(a: dict, b: dict, start: str, end: str, meters: float) -> dict:
    return {'mode': 'WALK', 'transitLeg': False, 'duration': 60, 'distance': meters, 'start': {'scheduledTime': stamp(start)},
            'end': {'scheduledTime': stamp(end)}, 'from': a, 'to': b, 'legGeometry': {'points': ''}, 'alerts': [], 'intermediatePlaces': []}


def otp(*legs_lists) -> dict:
    return {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': legs}} for legs in legs_lists], 'pageInfo': {}}}


class CityJourneyTests(SimpleTestCase):
    def setUp(self):
        self.feed = feed()
        for target, kwargs in ((supplement, {'_feeds': mock.DEFAULT}), (trainlive, {'trip_updates': mock.DEFAULT})):
            patcher = mock.patch.multiple(target, **kwargs)
            mocks = patcher.start()
            self.addCleanup(patcher.stop)
            if '_feeds' in mocks:
                mocks['_feeds'].return_value = {'Jesenice': self.feed}
            else:
                self.updates = mocks['trip_updates']
                self.updates.return_value = {}
        patcher = mock.patch.object(city_journeys, '_hubs', return_value=[])
        self.hubs = patcher.start()
        self.addCleanup(patcher.stop)
        # The feed's shapes as they are (no road legs table here).
        patcher = mock.patch.object(journeys.roads, 'repair', side_effect=lambda shape, *a, **k: (shape, True))
        patcher.start()
        self.addCleanup(patcher.stop)

    def add(self, req, data=None, anchor=None, query=None, budget=0):
        return city_journeys.add(data or otp(), req, anchor, query, budget)

    def rides(self, data) -> list[list[str]]:
        return [[f"{l['route']['shortName']} {l['from']['name']} {l['start']['scheduledTime'][11:16]}-{l['to']['name']} {l['end']['scheduledTime'][11:16]}"
                 for l in e['node']['legs'] if l.get('transitLeg')] for e in journeys._edges(data)]

    def test_a_trip_inside_the_town_rides_the_city_bus_and_builds_as_a_journey(self):
        # Nothing within 90 minutes of 06:20: the page holds the day's next bus.
        req = request(place('A', name='Doma'), place('D'), at='06:20')
        data, anchors = self.add(req)
        self.assertEqual(self.rides(data), [['1 Zahod 08:00-Vzhod 08:09']])
        [j] = journeys.build_journeys(data, req, [])
        [leg] = j['legs']
        self.assertEqual((leg['mode'], leg['routeName'], leg['tripId'], leg['operatorId'], leg['stopCount'], leg['origin']['name']),
                         ('bus', '1', 'Jesenice:1-0800', 'Jesenice:arriva', 3, 'Doma'))
        self.assertGreater(len(leg['geometry']), 1)
        self.assertEqual((j['transferCount'], j['effectiveArrival'][11:16]), (0, '08:09'))
        # The next page goes on after the last option shown, the previous one before the asked time.
        self.assertEqual(datetime.fromtimestamp(anchors['previous'], LOCAL).strftime('%H:%M'), '06:20')
        page = city_journeys.mark({'next': 'otp-next', 'previous': None}, anchors)
        self.assertTrue(page['next'].startswith('city:') and page['next'].endswith(':otp-next'))
        self.assertIsNone(page['previous'])

    def test_a_later_page_goes_on_from_its_anchor(self):
        req = request(place('A'), place('D'), at='06:20')
        first, anchors = self.add(req)
        later, back = city_journeys.take_anchor({**req, 'pageCursor': city_journeys.mark({'next': 'otp'}, anchors)['next'], 'pageDirection': 'later'})
        self.assertEqual(later['pageCursor'], 'otp')
        data, _ = self.add(later, anchor=back)
        self.assertEqual(self.rides(data), [['1 Zahod 09:00-Vzhod 09:09']])
        # A cursor without the mark (an older page) searches no town options.
        self.assertEqual(self.rides(self.add({**req, 'pageCursor': 'otp', 'pageDirection': 'later'})[0]), [])

    def test_a_change_of_bus_when_it_saves_time(self):
        # 300 m west of A: B (where line 2 starts) is too far to walk to.
        start = place('A', east=-0.004)
        data, _ = self.add(request(start, place('F')))
        self.assertEqual(self.rides(data), [['1 Zahod 08:00-Center 08:03', '2 Center 08:10-Planina 08:22']])
        # No change when the rider allows none.
        data, _ = self.add(request(start, place('F'), maxTransfers=0))
        self.assertEqual(self.rides(data), [])

    def test_walking_wins_over_a_bus_with_long_walks_to_and_from_it(self):
        # 400 m north of A to 400 m north of B: 770 m on foot, or 400 m + 3 min + 400 m.
        data, anchors = self.add(request(place('A', 0.0036), place('B', 0.0036)))
        self.assertEqual(self.rides(data), [])

    def test_arriving_by_takes_the_latest_bus_in_time(self):
        data, anchors = self.add(request(place('A'), place('D'), at='09:30', mode='arriveBy'))
        self.assertEqual(self.rides(data), [['1 Zahod 08:00-Vzhod 08:09'], ['1 Zahod 09:00-Vzhod 09:09']])
        # Later: arriving after the asked time; earlier: before the window the page covered (90 min).
        self.assertEqual([datetime.fromtimestamp(anchors[k], LOCAL).strftime('%H:%M') for k in ('next', 'previous')], ['09:30', '08:00'])
        data, _ = self.add(request(place('A'), place('D'), at='08:30', mode='arriveBy'))
        self.assertEqual(self.rides(data), [['1 Zahod 08:00-Vzhod 08:09']])

    def test_a_train_into_town_rides_the_city_bus_on_from_the_station(self):
        station = train('07:55')
        on_foot = walk(station['to'], otp_end('F', *STOPS['F'][1:]), '07:55', '08:35', 2500)
        req = request({'name': 'Ljubljana', 'latitude': 46.058, 'longitude': 14.51}, place('F'), at='07:00')
        data, _ = self.add(req, otp([station, on_foot]))
        self.assertEqual(self.rides(data), [['LP 2404 Ljubljana 07:20-Jesenice ŽP 07:55'],
                                            ['LP 2404 Ljubljana 07:20-Jesenice ŽP 07:55', '2 Postaja 08:14-Planina 08:22']])
        built = journeys.build_journeys(data, req, [])
        joined = built[1]
        self.assertEqual([l['mode'] for l in joined['legs']], ['rail', 'walk', 'bus'])
        self.assertEqual((joined['transferCount'], joined['transfers'][0]['status']), (1, 'safe'))
        # A train arriving too late for the bus walks, as OTP said.
        late = train('08:12')
        data, _ = self.add(req, otp([late, walk(late['to'], on_foot['to'], '08:12', '08:52', 2500)]))
        self.assertEqual(len(journeys._edges(data)), 1)

    def test_a_search_via_the_station_when_otp_ends_far_away_and_only_within_the_budget(self):
        self.hubs.return_value = [{'id': 'IJPP:9000', 'name': 'Jesenice ŽP', 'latitude': 46.4381, 'longitude': 14.0101, 'modes': ['rail']}]
        far = train('07:40', to=('Hrušica', 46.4500, 13.9600, 'IJPP:9100'))
        main = otp([far, walk(far['to'], otp_end('F', *STOPS['F'][1:]), '07:40', '08:40', 4200)])
        query = mock.Mock(return_value=otp([train('07:55')]))
        req = request({'name': 'Ljubljana', 'latitude': 46.058, 'longitude': 14.51}, place('F'), at='07:00')
        with mock.patch.object(companies, 'expand', return_value=[]):
            data, _ = self.add(req, main, query=query, budget=2)
        query.assert_called_once()
        self.assertEqual(query.call_args[0][1]['destination']['location'], {'stopLocation': {'stopLocationId': 'IJPP:9000'}})
        self.assertEqual(self.rides(data)[-1], ['LP 2404 Ljubljana 07:20-Jesenice ŽP 07:55', '2 Postaja 08:14-Planina 08:22'])
        city_journeys._hub_answers.clear()
        query.reset_mock()
        data, _ = self.add(req, main, query=query, budget=0)
        query.assert_not_called()
        self.assertEqual(len(journeys._edges(data)), 1)
        # No city bus leaves the station after the asked time (line 2's only run is at 08:14): no search.
        with mock.patch.object(companies, 'expand', return_value=[]):
            self.add({**req, 'dateTime': req['dateTime'].replace(hour=9)}, main, query=query, budget=2)
        query.assert_not_called()

    def test_a_run_otp_has_already_is_not_added_twice(self):
        req = request(place('A'), place('D'))
        data, _ = self.add(req)
        own = journeys._edges(data)[0]['node']['legs'][0]
        twin = {**own, 'route': {**own['route'], 'gtfsId': 'Jesenice:other'}, 'trip': {**own['trip'], 'gtfsId': 'Jesenice:3_1-0800'}}
        data, _ = self.add(req, otp([twin]))
        # OTP's copy of the 08:00 run stays alone; the 09:00 run is still added.
        self.assertEqual([e['node']['legs'][0]['trip']['gtfsId'] for e in journeys._edges(data)], ['Jesenice:3_1-0800', 'Jesenice:1-0900'])

    def test_a_live_delay_moves_the_ride(self):
        self.updates.return_value = {'Jesenice:1-0800': {'trip': {'tripId': 'Jesenice:1-0800', 'startDate': '20261026'},
                                                         'updates': [{'stopSequence': 1, 'departure': {'delay': 120}}]}}
        data, _ = self.add(request(place('A'), place('D')))
        leg = journeys._edges(data)[0]['node']['legs'][0]
        self.assertEqual((leg['start']['estimated']['time'][11:16], leg['end']['estimated']['time'][11:16], leg['realtimeState']), ('08:02', '08:11', 'UPDATED'))

    def test_only_the_chosen_operators(self):
        with mock.patch.object(companies, 'expand', side_effect=lambda ids: list(ids)):
            self.assertEqual(self.rides(self.add(request(place('A'), place('D'), operators=['IJPP:other']))[0]), [])
            self.assertEqual(len(self.rides(self.add(request(place('A'), place('D'), operators=['Jesenice:arriva']))[0])), 2)

    def test_the_api_answers_with_the_city_bus_and_pages_on(self):
        from prestop_api import views
        otp_api = mock.Mock()
        otp_api.query.return_value = {'planConnection': {'routingErrors': [], 'edges': [],
                                                         'pageInfo': {'startCursor': 's', 'endCursor': 'e', 'hasPreviousPage': True, 'hasNextPage': True}}}
        body = {'origin': place('A'), 'destination': place('D'), 'dateTime': '2026-10-26T06:20:00+01:00', 'timeMode': 'departAt',
                'modes': ['walk', 'bus', 'rail']}
        with mock.patch.object(views, 'otp', return_value=otp_api), mock.patch.object(companies, 'expand', return_value=[]):
            first = self.client.post('/api/v1/journeys', body, content_type='application/json').json()
            self.assertEqual([j['legs'][0]['tripId'] for j in first['data']], ['Jesenice:1-0800'])
            self.assertTrue(first['page']['next'].startswith('city:') and first['page']['next'].endswith(':e'))
            otp_api.query.reset_mock()
            later = self.client.post('/api/v1/journeys', {**body, 'pageCursor': first['page']['next'], 'pageDirection': 'later'},
                                     content_type='application/json').json()
        self.assertEqual([j['legs'][0]['tripId'] for j in later['data']], ['Jesenice:1-0900'])
        self.assertEqual(otp_api.query.call_args_list[0][0][1]['after'], 'e')  # OTP gets its own cursor back

    def test_nothing_near_a_city_bus_costs_nothing(self):
        req = request({'name': 'Ljubljana', 'latitude': 46.058, 'longitude': 14.51}, {'name': 'Kranj', 'latitude': 46.24, 'longitude': 14.35})
        data = otp([train('07:55')])
        with mock.patch.object(city_journeys, '_network') as network:
            self.assertEqual(self.add(req, data), (data, None))
        network.assert_not_called()

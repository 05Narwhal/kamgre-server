import time
from unittest import mock

from django.test import TestCase, override_settings

from prestop_api import sources
from prestop_api.upstream import Cached, Snapshot, UpstreamError

STOP = {'id': 'IJPP:1122804', 'name': 'Ljubljana', 'latitude': 46.0585, 'longitude': 14.5129, 'modes': ['bus', 'rail'],
        'operatorId': 'IJPP:1161', 'parentId': None, 'platform': None}


def fixed(value, age=0.0):
    cache = Cached(lambda: value, ttl=60, max_stale=600)
    cache._snap = Snapshot(value, time.time() - age)
    return cache


def failing():
    def boom():
        raise UpstreamError('down')
    return Cached(boom, ttl=60, max_stale=600)


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class FacadeTests(TestCase):
    def setUp(self):
        patches = {
            'stops': fixed({'list': [STOP] * 5001, 'routes': {'IJPP:1122804': {'IJPP:r1'}}}),
            'routes': fixed({'IJPP:r1': {'gtfsId': 'IJPP:r1', 'shortName': 'RG 310', 'mode': 'RAIL', 'agencyId': 'IJPP:1161',
                                         'agencyName': 'SŽ', 'patterns': []}}),
            'positions': fixed([]), 'trip_updates': fixed({}), 'vehicles': fixed([]), 'rentals': fixed([]),
            'alerts_raw': fixed([]),
        }
        for name, value in patches.items():
            p = mock.patch.object(sources, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_invalid_bbox_is_rejected(self):
        response = self.client.get('/api/v1/stops', {'bbox': '200,46,201,47'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'INVALID_BBOX')

    def test_stops_are_paged_with_a_cursor(self):
        first = self.client.get('/api/v1/stops', {'bbox': '13,45,17,47'}).json()
        self.assertEqual((len(first['data']['items']), first['data']['cursor'], first['meta']['status']), (4000, '4000', 'scheduled'))
        second = self.client.get('/api/v1/stops', {'bbox': '13,45,17,47', 'cursor': '4000'}).json()
        self.assertEqual((len(second['data']['items']), second['data']['cursor']), (1001, None))

    def test_upstream_outage_is_a_retryable_503(self):
        with mock.patch.object(sources, 'vehicles', failing()):
            response = self.client.get('/api/v1/vehicles', {'bbox': '13,45,17,47'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], {'code': 'UPSTREAM_UNAVAILABLE', 'message': mock.ANY, 'retryable': True})

    def test_old_snapshot_is_served_as_stale(self):
        with mock.patch.object(sources, 'positions', fixed([], age=600)):
            body = self.client.get('/api/v1/vehicles', {'bbox': '13,45,17,47'}).json()
        self.assertEqual(body['meta']['status'], 'stale')

    @override_settings(PRESTOP_INSANE_MODE=False)
    def test_capabilities_list_operators_and_gate_insane_mode(self):
        data = self.client.get('/api/v1/capabilities').json()['data']
        self.assertEqual(data['operators'], [{'id': 'IJPP:1161', 'name': 'SŽ', 'modes': ['rail'], 'sourceIds': ['IJPP:1161']}])
        self.assertEqual((data['journeyPlanning'], data['viaRouting'], data['insaneMode']), (True, True, False))
        statuses = {s['id']: s['status'] for s in data['sources']}
        self.assertEqual(statuses['prestop:statistics'], 'unavailable')

    def test_stop_alerts_include_alerts_for_routes_serving_the_stop(self):
        raw = [{'id': 'a', 'feed': 'IJPP', 'alertUrl': 'https://potniski.sz.si/', 'effectiveStartDate': time.time() - 10,
                'effectiveEndDate': None, 'alertHeaderTextTranslations': [{'language': 'en', 'text': 'Works'}],
                'alertDescriptionTextTranslations': [], 'agency': None,
                'entities': [{'__typename': 'Route', 'gtfsId': 'IJPP:r1', 'agency': {'gtfsId': 'IJPP:1161'}}]}]
        with mock.patch.object(sources, 'alerts_raw', fixed(raw)):
            items = self.client.get('/api/v1/alerts', {'stopId': 'IJPP:1122804'}).json()['data']
            other = self.client.get('/api/v1/alerts', {'stopId': 'IJPP:elsewhere'}).json()['data']
        self.assertEqual([a['id'] for a in items], ['alert:a'])
        self.assertEqual(other, [])
        self.assertEqual(set(items[0]), {'id', 'title', 'message', 'operatorId', 'stopIds', 'routeIds', 'validFrom', 'validTo', 'sourceUrl', 'kind'})

    def test_far_future_alerts_wait_until_they_are_near(self):
        soon, far = (time.time() + 86400, time.time() + 10 * 86400)
        raw = [{'id': name, 'feed': 'IJPP', 'alertUrl': None, 'effectiveStartDate': start, 'effectiveEndDate': None,
                'alertHeaderTextTranslations': [{'language': 'en', 'text': name}], 'alertDescriptionTextTranslations': [],
                'agency': None, 'entities': []} for name, start in (('soon', soon), ('far', far))]
        with mock.patch.object(sources, 'alerts_raw', fixed(raw)):
            items = self.client.get('/api/v1/alerts').json()['data']
        self.assertEqual([a['title'] for a in items], ['soon'])

    def test_station_search_does_not_call_the_geocoder(self):
        with mock.patch.object(sources, 'geocode') as geocode:
            body = self.client.get('/api/v1/places', {'q': 'ljub', 'scope': 'stations', 'limit': 5}).json()
        geocode.assert_not_called()
        self.assertEqual(body['data'][0], {'id': 'IJPP:1122804', 'name': 'Ljubljana', 'kind': 'station', 'stopId': 'IJPP:1122804',
                                           'modes': ['bus', 'rail'], 'latitude': 46.0585, 'longitude': 14.5129})

    def test_journey_validation_errors_are_422(self):
        response = self.client.post('/api/v1/journeys', {'origin': {}}, content_type='application/json')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'INVALID_REQUEST')

    def test_journeys_return_paging_cursors(self):
        from prestop_api import views
        place = {'name': 'A', 'latitude': 46.05, 'longitude': 14.5, 'kind': 'address'}
        body = {'origin': place, 'destination': {**place, 'name': 'B'}, 'via': [], 'dateTime': '2026-10-10T10:00:00+02:00', 'timeMode': 'departAt',
                'minTransferSeconds': 180, 'modes': ['walk', 'rail'], 'searchScope': 'all', 'riskMode': 'normal', 'pageCursor': 'c1'}
        otp = mock.Mock()
        otp.query.return_value = {'planConnection': {'routingErrors': [], 'edges': [],
                                                     'pageInfo': {'startCursor': 's', 'endCursor': 'e', 'hasPreviousPage': True, 'hasNextPage': True}}}
        with mock.patch.object(views, 'otp', return_value=otp):
            response = self.client.post('/api/v1/journeys', body, content_type='application/json')
        self.assertEqual((response.status_code, response.json()['page']), (200, {'previous': 's', 'next': 'e'}))
        self.assertEqual(otp.query.call_args[0][1]['after'], 'c1')

    def test_statistics_range_is_bounded(self):
        response = self.client.get('/api/v1/statistics/routes/IJPP:r1/daily',
                                   {'from': '2020-01-01', 'to': '2026-01-01', 'direction': 'all', 'quality': 'observed'})
        self.assertEqual(response.json()['error']['code'], 'INVALID_DATE_RANGE')

    def test_health_reports_database_readiness(self):
        response = self.client.get('/api/v1/health')
        self.assertEqual((response.status_code, response.json()['database']), (200, 'ready'))

    def test_pasted_coordinates_and_links_become_places(self):
        body = self.client.get('/api/v1/places', {'q': '46.0585, 14.5129'}).json()
        self.assertEqual(body['data'], [{'id': 'geo:46.058500,14.512900', 'name': '46.05850, 14.51290', 'latitude': 46.0585, 'longitude': 14.5129, 'kind': 'address'}])
        body = self.client.get('/api/v1/places', {'q': 'https://www.google.com/maps/place/Postaja/@46.0585,14.5129,17z', 'scope': 'stations'}).json()
        self.assertEqual(body['data'][0]['stopId'], 'IJPP:1122804')

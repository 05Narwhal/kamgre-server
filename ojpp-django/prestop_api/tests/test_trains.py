"""SŽ train pages and the statistics overview (spec 2026-10-26 F7): GET /trains/{number}, /trains/{number}/history,
/statistics/overview, /stations/{id}/statistics."""
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from prestop_api import scheduled, sources, trains, views
from prestop_api.tests.test_views import fixed
from prestop_statistics.models import StationDay, TrainDay

TODAY = date(2026, 10, 26)
SERVICE_DAY = 1_793_052_000 - 12 * 3600  # 26 Oct 2026, noon minus 12 h


def train_vehicle(number, delay, kind=None, **extra):
    return {'id': f'IJPP:scheduled-{number}', 'mode': 'rail', 'trainNumber': number, 'routeName': f'RG {number}', 'routeId': f'IJPP:r{number}',
            'tripId': f'IJPP:t{number}', 'trainCategory': 'RG', 'destination': 'Jesenice', 'nextStop': 'Kranj', 'delaySeconds': delay,
            **({'delayKind': kind} if kind else {}), **extra}


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class TrainEndpointTests(TestCase):
    def setUp(self):
        views._derived.clear()
        for name, value in {'vehicles': fixed([train_vehicle('310', 600), train_vehicle('2428', 60), train_vehicle('480', 900, 'predicted'),
                                               train_vehicle('18', None), {**train_vehicle('18969', 300), 'replacement': True}]),
                            'positions': fixed([]), 'alerts_raw': fixed([])}.items():
            p = mock.patch.object(sources, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(scheduled, 'service_day', return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def test_the_overview_counts_the_trains_on_their_way_and_lists_the_biggest_delays(self):
        StationDay.objects.create(service_date=date(2026, 10, 25), stop_id='IJPP:lj', name='Ljubljana', trains=100, on_time_share=0.5, avg_delay=200)
        StationDay.objects.create(service_date=date(2026, 10, 24), stop_id='IJPP:lj', name='Ljubljana', trains=100, on_time_share=0.7, avg_delay=100)
        StationDay.objects.create(service_date=date(2026, 10, 25), stop_id='IJPP:kr', name='Kranj', trains=50, on_time_share=1, avg_delay=0)
        StationDay.objects.create(service_date=date(2026, 10, 1), stop_id='IJPP:old', name='Old', trains=999, on_time_share=0, avg_delay=0)
        with mock.patch.object(scheduled, 'timetable', fixed([])):
            body = self.client.get('/api/v1/statistics/overview').json()['data']
        self.assertEqual((body['running'], body['measured'], body['onTimeShare']), (4, 3, 0.3333))  # the bus is not a train
        self.assertEqual(body['buckets'], {'onTime': 1, 'slightlyLate': 0, 'late': 2})  # under 3 min, 3-4 min, 5 min or more
        self.assertEqual([(t['number'], t['delaySeconds'], t.get('delayKind')) for t in body['biggestDelays']], [('480', 900, 'predicted'), ('310', 600, None)])
        self.assertEqual([(s['name'], s['trains'], s['onTimeShare'], s['avgDelaySeconds']) for s in body['stations']],
                         [('Ljubljana', 200, 0.6, 150), ('Kranj', 50, 1.0, 0)])

    def test_a_trains_history_from_the_rollups(self):
        for day, final in ((25, 60), (24, 600), (23, None)):
            TrainDay.objects.create(service_date=date(2026, 10, day), number='310', route_id='IJPP:r310', trip_id='IJPP:t310',
                                    max_delay=700, avg_delay=300, final_delay=final, on_time_share=0.5, stops=[])
        TrainDay.objects.create(service_date=TODAY, number='310', route_id='IJPP:r310', trip_id='IJPP:t310', final_delay=0, stops=[])
        body = self.client.get('/api/v1/trains/310/history', {'days': '30'}).json()['data']
        self.assertEqual([(d['date'], d['onTime']) for d in body['days']], [('2026-10-25', True), ('2026-10-24', False), ('2026-10-23', None)])
        self.assertEqual(body['summary'], {'runs': 3, 'avgDelaySeconds': 300, 'onTimeShare': 0.5})
        self.assertEqual(self.client.get('/api/v1/trains/31x/history').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/trains/310/history', {'days': '400'}).status_code, 422)

    def test_a_stations_days_merge_its_stop_ids(self):
        StationDay.objects.create(service_date=date(2026, 10, 25), stop_id='IJPP:lj', name='Ljubljana', trains=30, on_time_share=0.5, avg_delay=120)
        StationDay.objects.create(service_date=date(2026, 10, 25), stop_id='IJPP:lj2', name='Ljubljana', trains=10, on_time_share=1, avg_delay=0)
        with mock.patch.object(sources, 'stop_group', return_value=['IJPP:lj', 'IJPP:lj2']):
            body = self.client.get('/api/v1/stations/IJPP:lj/statistics').json()['data']
            self.assertEqual(body['days'], [{'date': '2026-10-25', 'trains': 40, 'onTimeShare': 0.625, 'avgDelaySeconds': 90}])
            self.assertEqual(body['stopId'], 'IJPP:lj')
        self.assertEqual(self.client.get('/api/v1/stations/IJPP:none/statistics').status_code, 404)

    def test_a_trains_run_today(self):
        run = {'id': 'IJPP:t310', 'route': {'gtfsId': 'IJPP:r310', 'shortName': 'RG 310', 'mode': 'RAIL'}, 'serviceDay': SERVICE_DAY,
               'stops': [], 'departures': []}
        bus = {**run, 'id': 'IJPP:b', 'route': {'gtfsId': 'IJPP:rb', 'shortName': 'BUS 310', 'mode': 'BUS'}}
        yesterday = {**run, 'id': 'IJPP:t310-y', 'serviceDay': SERVICE_DAY - 86_400}
        trip = {'id': 'IJPP:t310', 'realtime': True, 'stops': []}
        with mock.patch.object(scheduled, 'timetable', fixed([yesterday, bus, run])), \
                mock.patch('prestop_api.trips.load_trips', return_value={'IJPP:t310': {'static': {}}}), \
                mock.patch('prestop_api.trips.build_trip', return_value=trip), \
                mock.patch.object(sources, 'alerts', return_value=[{'id': 'a', 'title': '', 'routeIds': ['IJPP:r310'], '_from': 0, '_to': None}, {'id': 'b', 'title': '', 'routeIds': ['x'], '_from': 0, '_to': None},
                                                                       {'id': 'old', 'title': '', 'routeIds': ['IJPP:r310'], '_from': 0, '_to': 1}]):
            body = self.client.get('/api/v1/trains/0310').json()
        data = body['data']
        self.assertEqual((data['number'], data['category'], data['tripId'], data['date'], data['trip'], body['meta']['status']),
                         ('310', 'RG', 'IJPP:t310', '2026-10-26', trip, 'live'))
        self.assertEqual((data['vehicle']['delaySeconds'], [a['id'] for a in data['alerts']]), (600, ['a']))
        with mock.patch.object(scheduled, 'timetable', fixed([run])):
            self.assertEqual(self.client.get('/api/v1/trains/999').status_code, 404)

    def test_runs_of_another_day_come_from_that_days_timetable(self):
        run = {'id': 'IJPP:t310', 'route': {'gtfsId': 'IJPP:r310', 'shortName': 'RG 310', 'mode': 'RAIL'}, 'serviceDay': SERVICE_DAY + 86_400}
        with mock.patch.object(scheduled, 'day_timetable', return_value=fixed([run])) as day:
            self.assertEqual(trains.find_run('310', date(2026, 10, 27)), run)
        day.assert_called_once_with(date(2026, 10, 27))

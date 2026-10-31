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
            self.assertEqual(body['hours'][8], {'trains': 0, 'onTimeShare': None, 'avgDelaySeconds': None})  # rows from before H3
            self.assertEqual(body['stopId'], 'IJPP:lj')
        self.assertEqual(self.client.get('/api/v1/stations/IJPP:none/statistics').status_code, 404)

    def test_a_stations_trains_by_hour(self):
        StationDay.objects.create(service_date=date(2026, 10, 25), stop_id='IJPP:lj', name='Ljubljana', trains=3, on_time_share=0.5, avg_delay=120,
                                  hours={'7': [2, 1, 300], '8': [1, 1, 0]})
        StationDay.objects.create(service_date=date(2026, 10, 24), stop_id='IJPP:lj', name='Ljubljana', trains=2, on_time_share=0.5, avg_delay=120,
                                  hours={'7': [2, 0, 900], '25': [9, 9, 9]})  # an hour that cannot be is left out
        with mock.patch.object(sources, 'stop_group', return_value=['IJPP:lj']):
            body = self.client.get('/api/v1/stations/IJPP:lj/statistics').json()['data']
        self.assertEqual(len(body['hours']), 24)
        self.assertEqual(body['hours'][7], {'trains': 4, 'onTimeShare': 0.25, 'avgDelaySeconds': 300})
        self.assertEqual(body['hours'][8], {'trains': 1, 'onTimeShare': 1.0, 'avgDelaySeconds': 0})

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


def train_day(day, number, final, *, avg=None, mx=None, category='RG', departure=8 * 3600, canceled=False, replaced='none', stops=()):
    return TrainDay.objects.create(service_date=day, number=number, category=category, route_id=f'IJPP:r{number}', trip_id=f'IJPP:t{number}',
                                   origin='Ljubljana', destination='Jesenice', final_delay=final, avg_delay=avg if avg is not None else final,
                                   max_delay=mx if mx is not None else final, departure=departure, canceled=canceled, replaced=replaced,
                                   stops=list(stops))


def stops(*delays):
    """Stops lj, kr, le, je with these delays (None: not reported) and the gain since the station reported before."""
    out, before = [], None
    for (stop, name), d in zip([('IJPP:lj', 'Ljubljana'), ('IJPP:kr', 'Kranj'), ('IJPP:le', 'Lesce-Bled'), ('IJPP:je', 'Jesenice')], delays):
        out.append({'id': stop, 'name': name, 'delay': d, 'gained': d - before if d is not None and before is not None else None, 'track': None})
        before = d if d is not None else before
    return out


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class TrainTrendsTests(TestCase):
    """GET /statistics/trains (spec 2026-10-31 H2): all trains over 7, 30 or 90 days from the nightly rollups."""

    def setUp(self):
        trains._trends.clear()
        trains._lost_days.clear()
        views._derived.clear()
        p = mock.patch.object(scheduled, 'service_day', return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def get(self, days='7'):
        return self.client.get('/api/v1/statistics/trains', {'days': days})

    def test_no_rows_yet(self):
        body = self.get().json()['data']
        self.assertEqual((body['since'], body['dates'], body['worstTrains'], body['timeLost'], body['categories']), (None, [], [], [], []))
        self.assertEqual(body['headline'], {'trains': 0, 'onTimeShare': None, 'avgDelaySeconds': None,
                                            'buckets': {'onTime': 0, 'slightlyLate': 0, 'late': 0}, 'canceled': 0, 'replaced': 0})
        self.assertEqual(len(body['hours']), 24)
        self.assertEqual((body['from'], body['to']), ('2026-10-19', '2026-10-25'))

    def test_only_7_30_or_90_days(self):
        self.assertEqual(self.get('14').status_code, 422)
        self.assertEqual(self.get('90').status_code, 200)

    def test_one_day_of_rows(self):
        day = date(2026, 10, 25)
        train_day(day, '310', 60, departure=8 * 3600 + 120, stops=stops(0, 60, None, 60))
        train_day(day, '2428', 240, category='LPV', departure=8 * 3600, stops=stops(0, 240, 300, 240))
        train_day(day, '480', 600, departure=25 * 3600, stops=stops(0, 300, 600, 600))   # after midnight: hour 1
        train_day(day, '18', None, canceled=True, departure=None)
        train_day(day, '20', None, replaced='whole')
        train_day(TODAY, '310', 900)                                                     # today: not yet
        body = self.get().json()['data']
        self.assertEqual(body['since'], '2026-10-25')
        self.assertEqual(body['headline'], {'trains': 3, 'onTimeShare': 0.3333, 'avgDelaySeconds': 300,
                                            'buckets': {'onTime': 1, 'slightlyLate': 1, 'late': 1}, 'canceled': 1, 'replaced': 1})
        self.assertEqual([(d['date'], d['trains']) for d in body['dates']], [('2026-10-25', 3)])
        self.assertEqual((body['hours'][8]['trains'], body['hours'][8]['onTimeShare'], body['hours'][1]['trains']), (2, 0.5, 1))
        self.assertEqual([(c['category'], c['trains']) for c in body['categories']], [('RG', 2), ('LPV', 1)])
        self.assertEqual(body['worstTrains'], [])  # nobody has 3 runs
        self.assertEqual(body['timeLost'], [])     # no stretch has 5 runs

    def test_worst_trains_time_lost_and_the_period_before(self):
        for back in range(1, 8):
            day = date(2026, 10, 26 - back)
            train_day(day, '480', 600, mx=900, stops=stops(0, 400, 600, 600))
            train_day(day, '310', 0, stops=stops(0, 0, 0, 0))
        for back in range(8, 15):  # the week before: everything on time
            train_day(date(2026, 10, 26 - back), '480', 0)
        body = self.get().json()['data']
        self.assertEqual([(w['number'], w['name'], w['runs'], w['onTimeShare'], w['avgDelaySeconds'], w['maxDelaySeconds']) for w in body['worstTrains']],
                         [('480', 'RG 480', 7, 0.0, 600, 900), ('310', 'RG 310', 7, 1.0, 0, 0)])
        self.assertEqual([(s['fromName'], s['toName'], s['trains'], s['meanGainedSeconds']) for s in body['timeLost']],
                         [('Ljubljana', 'Kranj', 14, 200), ('Kranj', 'Lesce-Bled', 14, 100)])  # RG 310 gains nothing; nobody Lesce-Bled - Jesenice
        self.assertEqual((body['headline']['onTimeShare'], body['previous']['onTimeShare'], body['previous']['trains']), (0.5, 1.0, 7))

    def test_kept_an_hour_and_renewed_by_a_new_nights_rows(self):
        train_day(date(2026, 10, 24), '310', 0)
        first = trains.trends_cached(7, TODAY, now=1000)
        train_day(date(2026, 10, 24), '480', 0)
        self.assertIs(trains.trends_cached(7, TODAY, now=1000 + 3000), first)       # same night: the kept copy
        train_day(date(2026, 10, 25), '480', 0)
        self.assertEqual(trains.trends_cached(7, TODAY, now=1000 + 3100)['headline']['trains'], 3)  # the night's rows landed

    def test_time_lost_reads_only_the_days_whose_rows_changed(self):
        for back in range(1, 8):
            train_day(date(2026, 10, 26 - back), '480', 600, stops=stops(0, 600, 600, 600))
        self.assertEqual(trains.time_lost(date(2026, 10, 19), TODAY, now=0)[0]['meanGainedSeconds'], 600)
        TrainDay.objects.filter(service_date=date(2026, 10, 25)).delete()
        train_day(date(2026, 10, 25), '480', 0, stops=stops(0, 0, 0, 0))  # re-rolled, as many rows: kept a day
        self.assertEqual(trains.time_lost(date(2026, 10, 19), TODAY, now=60)[0]['trains'], 7)
        self.assertEqual(trains.time_lost(date(2026, 10, 19), TODAY, now=60)[0]['meanGainedSeconds'], 600)
        self.assertEqual(trains.time_lost(date(2026, 10, 19), TODAY, now=trains.LOST_KEEP + 1)[0]['meanGainedSeconds'], 514)  # 3600 / 7
        train_day(date(2026, 10, 25), '310', 0, stops=stops(0, 600, 600, 600))  # another row that day: read again now
        self.assertEqual(trains.time_lost(date(2026, 10, 19), TODAY, now=trains.LOST_KEEP + 2)[0]['trains'], 8)

    def test_the_warmer_builds_every_period_even_when_idle(self):
        from django.db import connection
        from prestop_api import warm
        with mock.patch.object(warm, 'caches', return_value=[]), mock.patch.object(warm, 'plans'),                 mock.patch.object(connection, 'close'):  # the warmer's thread closes its own connection; this test's is the test's
            warm._last_request = 0
            warm.tick(5000)
        self.assertEqual(sorted(trains._trends), [7, 30, 90])


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class TrainHistoryStationsTests(TestCase):
    """GET /trains/{n}/history (spec 2026-10-31 H2): per station along the route, weekdays, canceled and replaced."""

    def setUp(self):
        views._derived.clear()
        p = mock.patch.object(scheduled, 'service_day', return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def test_stations_weekdays_and_the_runs_that_did_not_run(self):
        train_day(date(2026, 10, 25), '480', 600, mx=700, stops=stops(0, 300, 600, 600))   # Sunday
        train_day(date(2026, 10, 24), '480', 120, mx=200, stops=stops(0, 60, 120, 120))    # Saturday
        train_day(date(2026, 10, 23), '480', 60, stops=stops(0, None, 60, 60))             # Friday
        train_day(date(2026, 10, 22), '480', None, canceled=True)
        train_day(date(2026, 10, 21), '480', None, replaced='whole')
        body = self.client.get('/api/v1/trains/480/history', {'days': '30'}).json()['data']
        self.assertEqual(body['summary']['runs'], 3)  # canceled and wholly replaced runs did not run
        self.assertEqual((body['canceled'], body['replaced'], body['medianDelaySeconds'], body['worstDelaySeconds']), (1, 1, 120, 700))
        self.assertEqual([(s['name'], s['runs'], s['medianDelaySeconds'], s['p80DelaySeconds'], s['medianGainedSeconds']) for s in body['stations']],
                         [('Ljubljana', 3, 0, 0, None), ('Kranj', 2, 60, 300, 60), ('Lesce-Bled', 3, 120, 600, 60), ('Jesenice', 3, 120, 600, 0)])
        self.assertEqual([w['runs'] for w in body['weekdays']], [0, 0, 0, 0, 1, 1, 1])
        self.assertEqual(body['weekdays'][6]['onTimeShare'], 0.0)
        self.assertEqual((body['name'], body['origin'], body['destination'], body['since']), ('RG 480', 'Ljubljana', 'Jesenice', '2026-10-21'))
        self.assertEqual([d.get('canceled') for d in body['days']], [None, None, None, True, None])
        self.assertEqual(body['days'][4]['replaced'], 'whole')

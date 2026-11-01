"""Buses in Reliability (Nov 2026): the overview's buses now, GET /statistics/buses (the lines' trends),
/statistics/departure (one bus departure day by day), /statistics/stations (bus stops) and a stop's bus statistics."""
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from prestop_api import buses, scheduled, sources, views
from prestop_api.tests.test_views import fixed
from prestop_statistics.models import RouteDay, StationDay, TripDelay, TripStops

TODAY = date(2026, 10, 26)


def bus(vehicle_id, delay, **extra):
    return {'id': vehicle_id, 'mode': 'bus', 'routeName': '6', 'routeId': 'LPP:6', 'operatorId': 'LPP:lpp', 'tripId': f'LPP:t-{vehicle_id}',
            'destination': 'Dolgi most', 'nextStop': 'Konzorcij', 'delaySeconds': delay, **extra}


def route_day(day, route, trips, on_time, late, delay_sum, **extra):
    return RouteDay.objects.create(service_date=day, route_id=route, operator_id=extra.pop('operator', 'LPP:lpp'), mode='bus', name=extra.pop('name', route),
                                   trips=trips, on_time=on_time, late=late, delay_sum=delay_sum, **extra)


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class BusEndpointTests(TestCase):
    def setUp(self):
        views._derived.clear()
        buses._cache.clear()
        vehicles = [bus('v1', 0), bus('v2', 240), bus('v3', 600), bus('v4', None), bus('v5', 900, replacement=True),
                    {'id': 'IJPP:scheduled-1', 'mode': 'rail', 'trainNumber': '310', 'delaySeconds': 60}]
        for name, value in {'vehicles': fixed(vehicles), 'positions': fixed([]), 'alerts_raw': fixed([])}.items():
            p = mock.patch.object(sources, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(scheduled, 'service_day', return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def test_the_overview_counts_the_buses_on_their_way(self):
        with mock.patch.object(scheduled, 'timetable', fixed([])):
            body = self.client.get('/api/v1/statistics/overview').json()['data']
        b = body['buses']
        self.assertEqual((b['running'], b['measured'], b['onTimeShare']), (4, 3, 0.3333))  # SŽ's replacement bus is the trains'
        self.assertEqual(b['buckets'], {'onTime': 1, 'slightlyLate': 1, 'late': 1})
        self.assertEqual(b['avgDelaySeconds'], 280)
        self.assertEqual([(x['vehicleId'], x['delaySeconds']) for x in b['biggestDelays']], [('v3', 600), ('v2', 240)])
        self.assertEqual(body['running'], 1)  # the trains' own figures stay as they were

    def test_the_lines_over_a_period_against_the_one_before(self):
        for i in range(1, 8):
            route_day(TODAY - timedelta(days=i), 'LPP:6', 10, 8, 1, 1200, hours={'7': [10, 8, 1200]}, name='6')
            route_day(TODAY - timedelta(days=i), 'NOMAGO:n69', 4, 1, 3, 1600, operator='NOMAGO:n', name='N0069', origin='Krško', destination='Blanca')
        route_day(TODAY - timedelta(days=9), 'LPP:6', 10, 10, 0, 0)  # the week before
        body = self.client.get('/api/v1/statistics/buses', {'days': '7'}).json()['data']
        self.assertEqual(body['headline']['trips'], 98)
        self.assertEqual(body['headline']['onTimeShare'], round(63 / 98, 4))
        self.assertEqual(body['headline']['buckets'], {'onTime': 63, 'slightlyLate': 7, 'late': 28})
        self.assertEqual(body['previous']['onTimeShare'], 1.0)
        self.assertEqual(len(body['dates']), 7)
        self.assertEqual(body['hours'][7], {'trips': 70, 'onTimeShare': 0.8, 'avgDelaySeconds': 120})
        self.assertEqual([o['operatorId'] for o in body['operators']], ['LPP:lpp', 'NOMAGO:n'])
        self.assertEqual([(w['routeId'], w['name'], w['origin'], w['avgDelaySeconds']) for w in body['worstLines']],
                         [('NOMAGO:n69', 'N0069', 'Krško', 400), ('LPP:6', '6', None, 120)])
        self.assertEqual(self.client.get('/api/v1/statistics/buses', {'days': '14'}).status_code, 422)

    def test_one_departure_day_by_day(self):
        TripStops.objects.create(trip_id='LPP:t1', route_id='LPP:6', mode='bus', seen=TODAY, stops=[[1, 'LPP:a', 'A', 25200], [2, 'LPP:b', 'B', 25320]])
        TripStops.objects.create(trip_id='LPP:t1b', route_id='LPP:6', mode='bus', seen=TODAY, stops=[[1, 'LPP:a', 'A', 25200]])
        TripStops.objects.create(trip_id='LPP:t2', route_id='LPP:6', mode='bus', seen=TODAY, stops=[[1, 'LPP:a', 'A', 28800]])
        now = timezone.now()
        for day, trip, delays, canceled in ((25, 'LPP:t1', {'1': 60, '2': 120}, False), (24, 'LPP:t1b', {'1': 300, '2': 500}, False),
                                            (23, 'LPP:t1', {}, True), (25, 'LPP:t2', {'1': 900}, False)):
            TripDelay.objects.create(service_date=date(2026, 10, day), trip_id=trip, route_id='LPP:6', operator_id='LPP:lpp', direction='0',
                                     stop_delays=delays, canceled=canceled, first_seen=now, last_seen=now)
        body = self.client.get('/api/v1/statistics/departure', {'tripId': 'LPP:t1', 'days': '30'}).json()['data']
        self.assertEqual((body['routeId'], body['start']), ('LPP:6', '07:00'))  # LPP:t2 leaves at 08:00: another departure
        self.assertEqual([(d['date'], d['avgDelaySeconds'], d['finalDelaySeconds'], d['onTime'], d.get('canceled')) for d in body['days']],
                         [('2026-10-25', 90, 120, True, None), ('2026-10-24', 400, 500, False, None), ('2026-10-23', None, None, None, True)])
        self.assertEqual(body['summary'], {'runs': 2, 'onTimeShare': 0.5, 'avgDelaySeconds': 245})
        self.assertEqual((body['worstDelaySeconds'], body['canceled']), (500, 1))
        self.assertEqual(self.client.get('/api/v1/statistics/departure', {'tripId': 'LPP:none'}).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/statistics/departure').status_code, 422)

    def test_bus_stops_both_sides_as_one_and_a_stop_s_buses(self):
        for stop, n, share, avg in (('LPP:k1', 30, 0.5, 120), ('LPP:k2', 10, 1.0, 0), ('LPP:x', 5, 1.0, 0)):
            StationDay.objects.create(service_date=TODAY - timedelta(days=1), stop_id=stop, mode='bus', name='Konzorcij' if stop != 'LPP:x' else 'Xa', trains=n, on_time_share=share, avg_delay=avg)
        StationDay.objects.create(service_date=TODAY - timedelta(days=1), stop_id='IJPP:lj', name='Ljubljana', trains=99, on_time_share=0.5, avg_delay=60)
        group = {'LPP:k1': ['LPP:k1', 'LPP:k2'], 'LPP:k2': ['LPP:k1', 'LPP:k2']}
        with mock.patch.object(sources, 'stop_group', side_effect=lambda stop_id, wait=False: group.get(stop_id, [stop_id])):
            body = self.client.get('/api/v1/statistics/stations', {'mode': 'bus'}).json()['data']
            self.assertEqual([(s['stopId'], s['name'], s['trains'], s['onTimeShare'], s['avgDelaySeconds']) for s in body['stations']],
                             [('LPP:k1', 'Konzorcij', 40, 0.625, 90), ('LPP:x', 'Xa', 5, 1.0, 0)])
            found = self.client.get('/api/v1/statistics/stations', {'mode': 'bus', 'q': 'konz'}).json()['data']
            self.assertEqual([s['stopId'] for s in found['stations']], ['LPP:k1'])
            stop = self.client.get('/api/v1/stations/LPP:k2/statistics', {'mode': 'bus'}).json()['data']
            self.assertEqual(stop['days'], [{'date': '2026-10-25', 'trains': 40, 'onTimeShare': 0.625, 'avgDelaySeconds': 90}])
            self.assertEqual(self.client.get('/api/v1/stations/LPP:k2/statistics').status_code, 404)  # no train stops there
            self.assertEqual(self.client.get('/api/v1/statistics/stations', {'mode': 'tram'}).status_code, 422)

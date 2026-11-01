"""Buses in Reliability (Nov 2026): RouteDay per line and day, bus StationDay rows per stop, from TripDelay and the
trip stops the collector keeps; SŽ's trains and their station rows stay rollup.py's."""
from datetime import date, datetime, timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from prestop_statistics import bus_rollup, rollup
from prestop_statistics.collector import LJUBLJANA, ScheduleCache
from prestop_statistics.models import RouteDay, StationDay, TripDelay, TripStops

DAY = date(2026, 10, 25)
ROUTES = {'LPP:6': {'mode': 'bus', 'name': '6', 'origin': 'Črnuče', 'destination': 'Dolgi most'},
          'IJPP:r2428': {'mode': 'rail', 'name': 'LPV 2428', 'origin': 'Ljubljana', 'destination': 'Jesenice'}}


def delay(trip, stops, route='LPP:6', operator='LPP:lpp', day=DAY, canceled=False, seen=None):
    now = seen or timezone.now()
    return TripDelay.objects.create(service_date=day, trip_id=trip, route_id=route, operator_id=operator, direction='0',
                                    stop_delays={str(k): v for k, v in stops.items()}, canceled=canceled, first_seen=now, last_seen=now)


def trip_stops(trip, route='LPP:6', first=7 * 3600):
    TripStops.objects.create(trip_id=trip, route_id=route, mode='bus', seen=DAY, stops=[
        [1, 'LPP:a1', 'Bavarski dvor', first], [2, 'LPP:b1', 'Konzorcij', first + 120], [3, 'LPP:c1', 'Ajdovščina', first + 240]])


class BusRollupTests(TestCase):
    def setUp(self):
        trip_stops('LPP:t1')
        trip_stops('LPP:t2', first=8 * 3600 + 600)
        delay('LPP:t1', {1: 0, 2: 60, 3: 120})        # 60 s late on average: on time
        delay('LPP:t2', {1: 240, 2: 420, 3: 360})     # 340 s: late
        delay('LPP:t3', {1: -30}, seen=datetime(2026, 10, 25, 12, tzinfo=LJUBLJANA))  # early, stops unknown: the line only
        delay('LPP:t4', {}, canceled=True)
        delay('IJPP:t2428', {1: 600}, route='IJPP:r2428', operator='IJPP:1161')  # SŽ: the trains' rollup

    def test_a_line_per_day_with_its_trips_on_time_and_late(self):
        lines, stations, counts = bus_rollup.build(DAY, ROUTES)
        self.assertEqual([line['route_id'] for line in lines], ['LPP:6'])
        line = lines[0]
        self.assertEqual((line['name'], line['origin'], line['destination'], line['mode']), ('6', 'Črnuče', 'Dolgi most', 'bus'))
        self.assertEqual((line['trips'], line['on_time'], line['late'], line['canceled']), (3, 2, 1, 1))
        self.assertEqual(line['delay_sum'], 60 + 340 + 0)  # the late part of each trip's mean
        self.assertEqual(line['max_delay'], 420)
        self.assertEqual(line['hours']['7'], [1, 1, 60])
        self.assertEqual(line['hours']['8'], [1, 0, 340])
        self.assertEqual(counts['busTripsWithStops'], 2)

    def test_each_stop_by_its_buses(self):
        _, stations, _ = bus_rollup.build(DAY, ROUTES)
        by_id = {s['stop_id']: s for s in stations}
        self.assertEqual(set(by_id), {'LPP:a1', 'LPP:b1', 'LPP:c1'})
        konzorcij = by_id['LPP:b1']
        self.assertEqual((konzorcij['mode'], konzorcij['name'], konzorcij['trains']), ('bus', 'Konzorcij', 2))
        self.assertEqual((konzorcij['on_time_share'], konzorcij['avg_delay']), (0.5, 240))
        self.assertEqual(konzorcij['hours'], {'7': [1, 1, 60], '8': [1, 0, 420]})

    def test_a_stop_abroad_is_left_out(self):
        TripStops.objects.filter(trip_id='LPP:t1').update(stops=[[1, 'IJPP:INTL-8300096', 'Gorizia Centrale', 0], [2, 'LPP:b1', 'Konzorcij', 120]])
        _, stations, _ = bus_rollup.build(DAY, ROUTES)
        self.assertNotIn('IJPP:INTL-8300096', {s['stop_id'] for s in stations})

    def test_writing_keeps_the_railway_stations(self):
        StationDay.objects.create(service_date=DAY, stop_id='IJPP:lj', name='Ljubljana', trains=4, on_time_share=0.5, avg_delay=120)
        lines, stations, _ = bus_rollup.build(DAY, ROUTES)
        bus_rollup.write(DAY, lines, stations)
        bus_rollup.write(DAY, lines, stations)  # a re-run replaces the day
        self.assertEqual(RouteDay.objects.count(), 1)
        self.assertEqual(StationDay.objects.filter(mode='bus').count(), 3)
        self.assertTrue(StationDay.objects.filter(mode='rail', stop_id='IJPP:lj').exists())
        rollup.write(DAY, [], [])  # the trains' re-run leaves the bus stops
        self.assertEqual(StationDay.objects.filter(mode='bus').count(), 3)

    def test_days_to_backfill_are_days_with_bus_delays_and_no_lines(self):
        delay('LPP:t9', {1: 0}, day=DAY - timedelta(days=1))
        lines, stations, _ = bus_rollup.build(DAY, ROUTES)
        bus_rollup.write(DAY, lines, stations)
        self.assertEqual(bus_rollup.days_to_backfill(DAY + timedelta(days=1), 7), [DAY - timedelta(days=1)])


class TripStopsTests(TestCase):
    def test_the_collector_keeps_each_trip_s_stops_once(self):
        cache = ScheduleCache()
        answer = {'t0': {'directionId': 0, 'blockId': None, 'route': {'gtfsId': 'LPP:6', 'mode': 'BUS', 'agency': {'gtfsId': 'LPP:lpp'}},
                         'stoptimesForDate': [{'stopPosition': 2, 'scheduledArrival': 25320, 'scheduledDeparture': 25320, 'serviceDay': 0,
                                               'stop': {'gtfsId': 'LPP:b1', 'name': 'Konzorcij', 'lat': 46.05, 'lon': 14.5}},
                                              {'stopPosition': 1, 'scheduledArrival': 25200, 'scheduledDeparture': 25200, 'serviceDay': 0,
                                               'stop': {'gtfsId': 'LPP:a1', 'name': 'Bavarski dvor', 'lat': 46.06, 'lon': 14.5}}]}}
        with mock.patch('prestop_statistics.collector.otp') as otp:
            otp.return_value.query.return_value = answer
            cache.get_many([('LPP:t1', '20261025')])
            cache._data.clear()
            cache.get_many([('LPP:t1', '20261026')])  # met again: not written twice
        kept = TripStops.objects.get()
        self.assertEqual((kept.trip_id, kept.route_id, kept.mode), ('LPP:t1', 'LPP:6', 'bus'))
        self.assertEqual(kept.stops, [[1, 'LPP:a1', 'Bavarski dvor', 25200], [2, 'LPP:b1', 'Konzorcij', 25320]])
        self.assertEqual(kept.seen, datetime.now(LJUBLJANA).date())

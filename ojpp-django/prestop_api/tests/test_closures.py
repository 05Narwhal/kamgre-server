"""Replacement buses made from SŽ closure notices when the feed has none (closures.py)."""
import base64
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from prestop_api import closures, geometry, roads, scheduled

LOCAL = ZoneInfo('Europe/Ljubljana')
DAY = datetime(2026, 10, 10, tzinfo=LOCAL).timestamp()  # service day 2026-10-10, local midnight
T0 = DAY + 8 * 3600
SZ = {'gtfsId': 'IJPP:1161'}
LINE = ['Ljubljana', 'Ljubljana Šiška', 'Medvode', 'Kranj', 'Lesce-Bled', 'Jesenice', 'Bled Jezero']


def station(name):
    return {'gtfsId': f'IJPP:{name}', 'name': name, 'lat': 46.05 + LINE.index(name) * 0.03, 'lon': 14.5 - LINE.index(name) * 0.03}


def train(id_, name, stations, start=T0, step=600, mode='RAIL', route=None):
    n = len(stations)
    return {'id': f'IJPP:{id_}', 'pattern': f'p-{id_}', 'headsign': None, 'delays': [None] * n, 'serviceDay': DAY,
            'route': {'gtfsId': route or f'IJPP:r-{id_}', 'shortName': name, 'mode': mode, 'agency': SZ},
            'stops': [station(s) for s in stations],
            'arrivals': [start + i * step for i in range(n)], 'departures': [start + i * step + 60 * (0 < i < n - 1) for i in range(n)]}


def notice(title, routes, start=DAY - 86400 * 14, end=DAY + 86400, number='11049'):
    raw = base64.b64encode(f'Alert:IJPP:SZ-OVIRA-{number}'.encode()).decode().rstrip('=')
    return {'id': f'alert:{raw}', '_aliases': [f'alert:{raw}'], 'title': title, 'message': '', 'kind': 'replacement',
            'routeIds': routes, 'stopIds': [], 'operatorId': 'IJPP:1161', '_from': start, '_to': end}


JESENICE = 'Vozni red nadomestnega prevoza: Ljubljana - Jesenice - Beljak (A) in obratno (26. 9. - 11. 10.).'


class NoticeTests(SimpleTestCase):
    def test_closure_notices_and_their_section(self):
        self.assertTrue(closures.is_closure(notice(JESENICE, [])))
        self.assertTrue(closures.is_closure(notice('Vozni red nad. prevoza: Ljubljana / Lesce Bled - Jesenice / Beljak (A) in obratno (12. - 18. 10.).', [])))
        self.assertFalse(closures.is_closure(notice('DODATNO: Avtobusni prevoz za vezo (NG-LJ): Lesce Bled - Bled Jezero in obratno (26.9. - 25.10.).', [])))
        self.assertFalse(closures.is_closure({**notice('OBVESTILO: Vlak vozi samo do/z postaje Ljubljana Šiška.', []), 'kind': 'info'}))
        self.assertEqual(closures.sides(notice(JESENICE, [])), [['ljubljana'], ['jesenice'], ['beljak']])
        self.assertEqual(closures.sides(notice('Vozni red nad. prevoza: Ljubljana / Lesce Bled - Jesenice / Beljak (A) in obratno (12. - 18. 10.).', [])),
                         [['lesce bled', 'ljubljana'], ['beljak', 'jesenice']])

    def test_station_names_match_whole_names_and_abbreviations(self):
        self.assertTrue(closures.names_match('ljubljana', 'Ljubljana'))
        self.assertFalse(closures.names_match('ljubljana', 'Ljubljana Šiška'))
        self.assertTrue(closures.names_match('b. bistrica', 'Bohinjska Bistrica'))
        self.assertTrue(closures.names_match('lesce bled', 'Lesce-Bled'))

    def test_notice_number_from_the_alert_id(self):
        self.assertEqual(closures.notice_id(notice(JESENICE, [], number='11049')), '11049')

    def test_dates_and_listed_days(self):
        borovnica = notice('Vozni red nadomestnega prevoza: Ljubljana - Borovnica in obratno (10., 11., 17., 24., 25. oktober).', [],
                           start=DAY, end=DAY + 15 * 86400)
        self.assertTrue(closures.in_effect(borovnica, T0, T0 + 1800))
        self.assertFalse(closures.in_effect(borovnica, T0 + 2 * 86400, T0 + 2 * 86400 + 1800))  # 12 October is not listed
        self.assertFalse(closures.in_effect(notice(JESENICE, [], end=DAY - 1), T0, T0 + 1800))

    def test_map_links_in_the_notice_text(self):
        raw = [{'ID_ovire': ['11049'], 'Opis': ['<a href="https://www.google.com/maps/place/x/@46.05,14.5,17z/data=!3d46.058118!4d14.513669">Lokacija</a>']}]
        self.assertEqual(closures.notice_points(raw), {'11049': [(46.058118, 14.513669)]})


class SynthesisTests(SimpleTestCase):
    def build(self, trips, alerts, real=None, patterns=(), points=None, bus_stops=()):
        with mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]):
            return closures.synthesize(trips, real or {}, alerts, list(patterns), points or {}, list(bus_stops))

    def test_a_listed_train_on_the_closed_section_gets_a_bus_at_its_times(self):
        t = train('453228', 'LPV 2494', ['Ljubljana', 'Ljubljana Šiška', 'Medvode', 'Kranj', 'Lesce-Bled', 'Jesenice'])
        [bus] = self.build([t], [notice(JESENICE, ['IJPP:r-453228'])])
        self.assertEqual(bus['id'], 'IJPP:sub-20261010-453228-0')
        self.assertEqual(bus['route']['shortName'], 'BUS 2494')
        # Its own line (the bus on the roads), named after the train it replaces.
        self.assertEqual(bus['route']['gtfsId'], 'IJPP:sub-r-r-453228')
        self.assertEqual((bus['trainRouteId'], bus['trainName']), ('IJPP:r-453228', 'LPV 2494'))
        self.assertEqual([s['name'] for s in bus['stops']], [s['name'] for s in t['stops']])
        self.assertEqual((bus['departures'], bus['arrivals']), (t['departures'], t['arrivals']))
        self.assertEqual(bus['alertIds'], [notice(JESENICE, [])['id']])
        self.assertEqual(closures.sections([bus])['IJPP:453228'][0]['fromIndex'], 0)
        self.assertEqual(closures.sections([bus])['IJPP:453228'][0]['toIndex'], 5)

    def test_a_through_train_is_replaced_only_on_the_section(self):
        t = train('456520', 'LP 4290', ['Ljubljana', 'Medvode', 'Kranj', 'Jesenice', 'Bled Jezero'])
        [bus] = self.build([t], [notice(JESENICE, ['IJPP:r-456520'])])
        self.assertEqual((bus['fromIndex'], bus['toIndex']), (0, 3))
        self.assertEqual(bus['headsign'], 'Jesenice')

    def test_a_train_starting_inside_the_section_is_replaced(self):
        # Ljubljana Šiška is not named in the notice, but lies between Ljubljana and Jesenice on other trains.
        full = train('a', 'LPV 2400', ['Ljubljana', 'Ljubljana Šiška', 'Kranj', 'Jesenice'])
        short = train('b', 'LPV 2418', ['Ljubljana Šiška', 'Kranj', 'Jesenice'])
        buses = self.build([full, short], [notice(JESENICE, ['IJPP:r-a', 'IJPP:r-b'])])
        self.assertEqual(sorted(b['route']['shortName'] for b in buses), ['BUS 2400', 'BUS 2418'])

    def test_unlisted_trains_and_other_lines_get_none(self):
        listed = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice'])
        other = train('b', 'LPV 2402', ['Ljubljana', 'Kranj', 'Jesenice'])
        buses = self.build([listed, other], [notice(JESENICE, ['IJPP:r-a'])])
        self.assertEqual([b['trainTripId'] for b in buses], ['IJPP:a'])

    def test_a_train_with_a_real_bus_gets_no_synthetic_duplicate(self):
        t = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice'])
        real = {'IJPP:a': [{'start': T0, 'end': T0 + 1200, 'fromIndex': 0, 'toIndex': 2, 'busTripId': 'IJPP:bus'}]}
        self.assertEqual(self.build([t], [notice(JESENICE, ['IJPP:r-a'])], real=real), [])

    def test_a_notice_the_feed_has_buses_for_gets_none(self):
        t = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice'])
        patterns = [('ljubljana', 'jesenice', frozenset({'20261005'}))]
        self.assertEqual(self.build([t], [notice(JESENICE, ['IJPP:r-a'])], patterns=patterns), [])
        # Buses on other days (March) do not cover this notice.
        march = [('ljubljana', 'jesenice', frozenset({'20260328'}))]
        self.assertEqual(len(self.build([t], [notice(JESENICE, ['IJPP:r-a'])], patterns=march)), 1)
        # Year-round buses for some trains (another notice's) do not cover a closure of a few days.
        year = [('ljubljana', 'jesenice', frozenset(f'2026{m:02d}{d:02d}' for m in range(1, 13) for d in range(1, 29)))]
        self.assertEqual(len(self.build([t], [notice(JESENICE, ['IJPP:r-a'])], patterns=year)), 1)

    def test_notices_not_in_effect_give_none(self):
        t = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice'])
        self.assertEqual(self.build([t], [notice(JESENICE, ['IJPP:r-a'], end=DAY - 60)]), [])

    def test_two_notices_meeting_at_a_station_make_one_bus(self):
        t = train('a', 'LP 4290', ['Ljubljana', 'Kranj', 'Jesenice', 'Bled Jezero'])
        vintgar = notice('Vozni red nadomestnega prevoza: Jesenice - Bled Jezero in obratno (23. 9. - 25. 10.).', ['IJPP:r-a'], number='11056')
        [bus] = self.build([t], [notice(JESENICE, ['IJPP:r-a']), vintgar])
        self.assertEqual((bus['fromIndex'], bus['toIndex']), (0, 3))
        self.assertEqual(len(bus['alertIds']), 2)

    def test_replacement_stops_in_order_of_trust(self):
        s = station('Jesenice')
        checked = [{'lat': s['lat'] + 0.003, 'lon': s['lon'], 'label': 'AP', 'stationId': s['gtfsId']}]
        with mock.patch('prestop_api.stopfix.replacement_stops', return_value=checked):
            self.assertEqual(closures.replacement_point(s, [(s['lat'], s['lon'] + 0.001)], []), {'lat': s['lat'] + 0.003, 'lon': s['lon'], 'unverified': False, 'label': 'AP'})
        with mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]):
            linked = closures.replacement_point(s, [(s['lat'] + 0.002, s['lon'])], [])
            self.assertEqual((linked['lat'], linked['unverified']), (s['lat'] + 0.002, False))
            near = [{'name': 'Jesenice AP', 'latitude': s['lat'] + 0.001, 'longitude': s['lon'], 'modes': ['bus']},
                    {'name': 'Hrušica', 'latitude': s['lat'], 'longitude': s['lon'] + 0.0005, 'modes': ['bus']}]
            guessed = closures.replacement_point(s, [], near)
            self.assertEqual((guessed['lat'], guessed['unverified']), (s['lat'] + 0.001, True))
            self.assertEqual(closures.replacement_point(s, [], []), {'lat': s['lat'], 'lon': s['lon'], 'unverified': True})
            self.assertIsNone(closures.replacement_point(s, [], near, fallback=False))


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self

    def get_nowait(self):
        return self

    def wait(self, timeout):
        return self

    def peek(self):
        return self


class ScheduledSyntheticTests(SimpleTestCase):
    def test_the_bus_runs_on_the_roads_and_the_train_is_hidden(self):
        t = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice'])
        rail = [[s['lon'], s['lat']] for s in t['stops']]
        rail_shape = {'coords': rail, 'cum': geometry.cumulative(rail), 'distances': geometry.cumulative(rail), 'stops': t['stops']}
        [bus] = closures.synthesize([t], {}, [notice(JESENICE, ['IJPP:r-a'])], [], {}, [])
        derived = {'key': None, 'sections': closures.sections([bus]), 'synthetic': [bus], 'by_id': {bus['id']: bus}}
        road = [[14.5, 46.05], [14.5, 46.11], [14.44, 46.11], [14.44, 46.2], [14.35, 46.2]]
        with mock.patch.object(scheduled, 'timetable', _Value([t])), mock.patch.object(scheduled, 'shapes', _Value({'p-a': rail_shape})), \
                mock.patch.object(scheduled, '_derive', return_value=derived), \
                mock.patch.object(scheduled.roads, 'repair', return_value=(road, True)) as repair:
            scheduled._road_shapes.clear()
            shown = scheduled.vehicles(now=T0 + 300, live={})
            entry = scheduled.synthetic_entry(bus['id'])
        self.assertEqual([v['tripId'] for v in shown], [bus['id']])
        [v] = shown
        self.assertEqual((v['mode'], v['quality'], v['replacement'], v['name'], v['alertIds']), ('bus', 'scheduled', True, 'BUS 2400', bus['alertIds']))
        self.assertTrue(all(call.kwargs.get('road_only') for call in repair.call_args_list))
        self.assertEqual(entry['static']['geometry'], geometry.simplify(road))
        self.assertTrue(entry['static']['replacement'])
        self.assertEqual(entry['times'][0]['scheduledDeparture'], t['departures'][0] - DAY)


class RoadOnlyTests(SimpleTestCase):
    def test_a_replacement_shape_is_never_the_rail_shape(self):
        stops = [{'lat': 46.05, 'lon': 14.5}, {'lat': 46.2, 'lon': 14.35}]
        rail = [[14.5, 46.05], [14.47, 46.1], [14.42, 46.15], [14.35, 46.2]]  # dense, through both stops: fine for a train
        self.assertEqual(roads.repair(rail, stops)[0], rail)
        with mock.patch.object(roads.legs, 'get_many', return_value={}), mock.patch.object(roads.worker, 'request', return_value=[]), \
                self.settings(PRESTOP_VALHALLA_URL='https://valhalla.example/route'):
            routing, complete = roads.repair(rail, stops, road_only=True)
        self.assertEqual(routing, [[14.5, 46.05], [14.35, 46.2]])  # straight between the stops until the road is routed
        self.assertFalse(complete)
        road = [[14.5, 46.05], [14.55, 46.12], [14.35, 46.2]]
        with mock.patch.object(roads.legs, 'get_many', return_value={roads.leg_key(*stops): road}):
            self.assertEqual(roads.repair(rail, stops, road_only=True), (road, True))

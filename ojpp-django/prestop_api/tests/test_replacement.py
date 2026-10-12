"""SŽ replacement buses (nadomestni prevoz): recognised, labelled and routable from a rail-only request."""
from django.test import SimpleTestCase

from prestop_api import journeys, leg_alerts, mapping
from prestop_api.tests.test_journey_alerts import request
from prestop_api.tests.test_leg_alerts import LEG, T0, alert
from prestop_api.tests.test_mapping import leg, stoptime


def plan(raw):
    return {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [raw]}}]}}


class ReplacementTests(SimpleTestCase):
    def test_sz_bus_leg_is_a_replacement(self):
        raw = leg('BUS', '10:00:00', '10:40:00', trip='IJPP:9')
        raw['route'] = {'gtfsId': 'IJPP:r9', 'shortName': 'BUS 61706', 'mode': 'BUS', 'agency': {'gtfsId': 'IJPP:1161'}}
        [j] = journeys.build_journeys(plan(raw), request(), [])
        self.assertTrue(j['legs'][0]['replacement'])

    def test_ordinary_bus_is_not_a_replacement(self):
        raw = leg('BUS', '10:00:00', '10:40:00', trip='LPP:9')
        raw['route'] = {'gtfsId': 'LPP:6', 'shortName': '6', 'mode': 'BUS', 'agency': {'gtfsId': 'LPP:lpp'}}
        [j] = journeys.build_journeys(plan(raw), request(), [])
        self.assertNotIn('replacement', j['legs'][0])

    def test_sz_trains_are_not_replacements(self):
        self.assertFalse(mapping.is_replacement({'shortName': 'IC 509', 'mode': 'RAIL', 'agency': {'gtfsId': 'IJPP:1161'}}))
        self.assertTrue(mapping.is_replacement({'shortName': 'BUS 18969', 'mode': 'BUS', 'agencyId': 'IJPP:1161'}))

    def test_rail_only_request_includes_sz_replacement_buses(self):
        v = journeys.otp_variables(request(modes=['walk', 'rail']))
        modes = {m['mode'] for m in v['modes']['transit']['transit']}
        self.assertTrue({'RAIL', 'BUS'} <= modes)
        self.assertEqual(v['preferences']['transit']['filters'], [{'include': [{'agencies': ['IJPP:1161']}]}])

    def test_rail_only_with_operator_filter_keeps_the_intersection(self):
        v = journeys.otp_variables(request(modes=['walk', 'rail'], operators=['IJPP:1161', 'LPP:lpp']))
        self.assertEqual(v['preferences']['transit']['filters'], [{'include': [{'agencies': ['IJPP:1161']}]}])

    def test_rail_only_without_sz_in_the_operator_filter_adds_no_buses(self):
        v = journeys.otp_variables(request(modes=['walk', 'rail'], operators=['LPP:lpp']))
        self.assertNotIn('BUS', {m['mode'] for m in v['modes']['transit']['transit']})
        self.assertEqual(v['preferences']['transit']['filters'], [{'include': [{'agencies': ['LPP:lpp', 'IJPP:1118']}]}])  # LPP in every feed

    def test_rail_and_bus_request_is_unfiltered(self):
        v = journeys.otp_variables(request(modes=['walk', 'bus', 'rail']))
        self.assertNotIn('filters', v['preferences']['transit'])

    def test_board_marks_sz_buses(self):
        row = stoptime('IJPP:b1', 'IJPP:x', 'IJPP:y')
        row['trip']['route'] = {'gtfsId': 'IJPP:r9', 'shortName': 'BUS 18969', 'mode': 'BUS', 'agency': {'gtfsId': 'IJPP:1161'}}
        train = stoptime('IJPP:t1', 'IJPP:x', 'IJPP:y')
        bus, rail = mapping.build_board('IJPP:s', [row, train], 'departure', [])
        self.assertEqual((bus['replacement'], bus['mode']), (True, 'bus'))
        self.assertNotIn('replacement', rail)

    def test_replacement_leg_shows_the_replacement_notice_of_its_section(self):
        # SŽ attaches "Vozni red nadomestnega prevoza" to the train routes; the bus that runs instead travels that section.
        notice = {**alert('alert:n', routes=['IJPP:train'], title='Vozni red nadomestnega prevoza: Ljubljana - Borovnica in obratno.'), 'kind': 'replacement'}
        works = {**alert('alert:w', routes=['IJPP:train'], title='Dela na progi: Ljubljana - Borovnica in obratno.'), 'kind': 'disruption'}
        bus = {**LEG, 'routeId': 'IJPP:r9', 'mode': 'bus', 'replacement': True}
        self.assertEqual(leg_alerts.match(bus, set(), {'ljubljana', 'brezovica', 'borovnica'}, [notice, works]), ['alert:n'])
        self.assertEqual(leg_alerts.match({**LEG, 'routeId': 'IJPP:other'}, set(), {'ljubljana', 'borovnica'}, [notice]), [])


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self


class ScheduledReplacementTests(SimpleTestCase):
    def test_sz_bus_is_placed_by_timetable_on_a_road_shape(self):
        from unittest import mock
        from prestop_api import geometry, scheduled
        stops = [{'gtfsId': 'IJPP:a', 'name': 'Ljubljana', 'lat': 46.05, 'lon': 14.5}, {'gtfsId': 'IJPP:b', 'name': 'Logatec', 'lat': 45.91, 'lon': 14.22}]
        trip = {'id': 'IJPP:b1', 'route': {'gtfsId': 'IJPP:r9', 'shortName': 'BUS 18969', 'mode': 'BUS', 'agency': {'gtfsId': 'IJPP:1161'}},
                'pattern': 'p1', 'headsign': 'Logatec', 'stops': stops, 'arrivals': [T0, T0 + 3600], 'departures': [T0, T0 + 3600], 'delays': [None, None]}
        straight = [[14.5, 46.05], [14.22, 45.91]]
        shape = {'coords': straight, 'cum': geometry.cumulative(straight), 'distances': geometry.stop_distances(straight, stops), 'stops': stops}
        bent = [[14.5, 46.05], [14.5, 45.91], [14.22, 45.91]]
        calls = []

        def repair(coords, stops_, deadline=None, road_only=False):
            calls.append((len(stops_), road_only))
            return bent, True

        with mock.patch.object(scheduled, 'timetable', _Value([trip])), mock.patch.object(scheduled, 'shapes', _Value({'p1': shape})), \
                mock.patch.object(scheduled.roads, 'repair', repair):
            [v] = scheduled.vehicles(now=T0 + 600, live={})
        self.assertEqual((v['mode'], v['replacement'], v['quality'], v['trainNumber']), ('bus', True, 'scheduled', None))
        self.assertEqual(calls, [(2, True)])  # routed on the roads whatever shape the feed has
        self.assertAlmostEqual(v['longitude'], 14.5, places=3)  # on the road shape's first (north-south) side


class TripReplacementTests(SimpleTestCase):
    def test_trip_of_an_sz_bus_is_a_replacement(self):
        from datetime import date
        from unittest import mock
        from prestop_api import trips
        from prestop_api.tests.test_trips import otp_trip
        trips._static._data.clear()
        trips._times._data.clear()
        raw = otp_trip('IJPP:b1')
        raw['route'] = {'gtfsId': 'IJPP:r9', 'shortName': 'BUS 18969', 'mode': 'BUS', 'color': None, 'agency': {'gtfsId': 'IJPP:1161'}}
        with mock.patch.object(trips, '_query_trips', return_value={'IJPP:b1': raw}):
            found = trips.load_trips(['IJPP:b1'], date(2026, 10, 9))
        trip = trips.build_trip(found['IJPP:b1'], {})
        self.assertEqual((trip['mode'], trip['replacement']), ('bus', True))

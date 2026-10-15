"""Slovenia only: places abroad are text, never stops, shapes or vehicles (abroad.py)."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import abroad, mapping, trips


def _stop(sid, name, lat, lon):
    return {'gtfsId': sid, 'name': name, 'lat': lat, 'lon': lon}


GORIZIA = _stop('IJPP:1167555', 'Gorizia Stazione FF SS (I)', 45.9334, 13.6072)
CORSO = _stop('IJPP:1167558', 'Gorizia Corso Italia 85/89 (I)', 45.9399, 13.6151)
NOVA = _stop('IJPP:ng', 'Nova Gorica AP', 45.9555, 13.6497)
SOLKAN = _stop('IJPP:so', 'Solkan', 45.9710, 13.6520)


def _trip(stops, mode='BUS', name='1', headsign=''):
    return {
        'gtfsId': 'IJPP:t1', 'tripHeadsign': headsign, 'directionId': 0,
        'route': {'gtfsId': 'IJPP:r1', 'shortName': name, 'mode': mode, 'agency': {'gtfsId': 'IJPP:a'}},
        'stoptimes': [{'stopPosition': i, 'stop': s, 'scheduledDeparture': 3600 * 7 + 60 * i} for i, s in enumerate(stops)],
        'shapeCoordinates': [[s['lon'], s['lat']] for s in stops],
    }


def _static(t):
    with mock.patch.object(trips, '_corrected', side_effect=lambda stops, replacement=False: stops), \
            mock.patch.object(trips, 'road_shape', side_effect=lambda raw, *a, **k: (raw, True)), \
            mock.patch.object(trips.platforms, 'place', side_effect=lambda stops, *a: (stops, None)), \
            mock.patch.object(trips.platforms, 'origin_area', return_value=None), \
            mock.patch.object(trips.stopfix, 'renamed', side_effect=lambda sid, name: name):
        return trips._build_static(t)


class PlaceTests(SimpleTestCase):
    def test_feed_stops_abroad_are_known_by_their_country(self):
        self.assertTrue(abroad.is_abroad_stop('Tarvisio autostazione (I)'))
        self.assertTrue(abroad.is_abroad_stop('Bleiburg Bahnhof (A)'))
        self.assertFalse(abroad.is_abroad_stop('Nova Gorica AP'))
        self.assertFalse(abroad.is_abroad_stop('Kidričeva (Center)'))

    def test_places_read_as_riders_know_them(self):
        self.assertEqual(abroad.place('Gorizia Corso Italia 85/89 (I)'), 'Gorica / Gorizia')
        self.assertEqual(abroad.place('BELJAK'), 'Beljak / Villach')
        self.assertEqual(abroad.place('OPČINE'), 'Opčine')
        self.assertEqual(abroad.place('Somewhere (A)'), 'Somewhere')

    def test_international_trains_show_their_real_ends(self):
        self.assertEqual(abroad.train_ends('EC 115', 'Jesenice', 'Dobova'), ('München', 'Zagreb'))
        self.assertEqual(abroad.train_ends('RG 310', 'Ljubljana', 'Jesenice'), (None, 'Beljak / Villach'))
        self.assertEqual(abroad.train_ends('MV 481', 'Ljubljana', 'Ilirska Bistrica'), (None, 'Reka / Rijeka'))
        self.assertEqual(abroad.train_ends('LPV 2400', 'Ljubljana', 'Jesenice'), (None, None))  # a domestic train


class TripTests(SimpleTestCase):
    def test_a_trip_into_italy_ends_at_its_last_stop_in_slovenia(self):
        static = _static(_trip([SOLKAN, NOVA, CORSO, GORIZIA]))
        self.assertEqual([s['name'] for s in static['stops']], ['Solkan', 'Nova Gorica AP'])
        self.assertEqual(static['destination'], 'Gorica / Gorizia')
        self.assertNotIn('comesFrom', static)
        # The shape stops at Nova Gorica: nothing drawn in Italy.
        self.assertEqual([round(x, 5) for x in static['geometry'][-1]], [NOVA['lon'], NOVA['lat']])

    def test_a_trip_from_italy_starts_at_its_first_stop_in_slovenia(self):
        static = _static(_trip([GORIZIA, CORSO, NOVA, SOLKAN]))
        self.assertEqual([s['name'] for s in static['stops']], ['Nova Gorica AP', 'Solkan'])
        self.assertEqual((static['comesFrom'], static['destination']), ('Gorica / Gorizia', 'Solkan'))
        self.assertEqual([round(x, 5) for x in static['geometry'][0]], [NOVA['lon'], NOVA['lat']])

    def test_a_trip_only_abroad_is_none(self):
        self.assertIsNone(_static(_trip([GORIZIA, CORSO])))

    def test_a_zagreb_ec_keeps_its_stops_in_slovenia_and_reads_zagreb(self):
        jes, lj, dob = _stop('IJPP:jes', 'Jesenice', 46.43, 14.06), _stop('IJPP:lj', 'Ljubljana', 46.05, 14.51), _stop('IJPP:dob', 'Dobova', 45.89, 15.65)
        with mock.patch.object(trips.tracks.tracks, 'track', return_value=(None, False)):
            static = _static(_trip([jes, lj, dob], mode='RAIL', name='EC 115', headsign='Jesenice - Dobova'))
        self.assertEqual([s['name'] for s in static['stops']], ['Jesenice', 'Ljubljana', 'Dobova'])
        self.assertEqual((static['comesFrom'], static['destination']), ('München', 'Zagreb'))


class BoardAndVehicleTests(SimpleTestCase):
    def test_a_board_row_reads_the_real_end(self):
        route = {'gtfsId': 'IJPP:ec', 'shortName': 'EC 115', 'mode': 'RAIL', 'agency': {'gtfsId': 'IJPP:sz'}}
        st = {'stop': {'gtfsId': 'IJPP:lj'}, 'serviceDay': 0, 'scheduledDeparture': 100, 'realtimeDeparture': 100, 'scheduledArrival': 90, 'realtimeArrival': 90, 'stopPosition': 3,
              'trip': {'gtfsId': 'IJPP:t', 'route': route, 'departureStoptime': {'stop': {'gtfsId': 'IJPP:jes', 'name': 'Jesenice'}},
                       'arrivalStoptime': {'stop': {'gtfsId': 'IJPP:dob', 'name': 'Dobova'}}}}
        with mock.patch('prestop_api.stopfix.renamed', side_effect=lambda sid, name: name):
            self.assertEqual(mapping.build_board('IJPP:lj', [st], 'departure', [])[0]['destination'], 'Zagreb')
            self.assertEqual(mapping.build_board('IJPP:lj', [st], 'arrival', [])[0]['destination'], 'München')

    def test_no_vehicle_on_its_way_through_italy(self):
        positions = [{'id': 'v1', 'vehicle': {'trip': {'tripId': 'IJPP:t1'}, 'position': {'latitude': 45.94, 'longitude': 13.61},
                                              'stopId': 'IJPP:1167558', 'timestamp': 1}}]
        names = {'IJPP:1167558': CORSO['name']}
        routes = {'IJPP:r1': {'mode': 'BUS'}}
        self.assertEqual(mapping.build_vehicles(positions, {}, {'IJPP:t1': {'routeId': 'IJPP:r1'}}, routes, names, now=10), [])


class OneStopBusTests(SimpleTestCase):
    """Sežana - Opčine: the bus's only stop in Slovenia is Sežana; it still shows there, going to Opčine."""

    def bus(self, **ends):
        stop = {'gtfsId': 'IJPP:sez', 'name': 'Sežana', 'lat': 45.7066, 'lon': 13.8692}
        return {'id': 'IJPP:sub-1', 'source': 'timetable', 'synthetic': True, 'serviceDay': 0, 'stops': [stop],
                'departures': [1000.0], 'arrivals': [1000.0], 'alertIds': [], 'trainName': 'LPV 1824',
                'route': {'gtfsId': 'IJPP:sub-r', 'shortName': 'BUS 1824', 'agency': {'gtfsId': 'IJPP:sz'}}, **ends}

    def test_the_bus_to_opcine_leaves_sezana(self):
        from prestop_api import replacement
        plan = {'synthetic': [self.bus(goesTo='Opčine')]}
        rows = replacement.timetable_rows(plan, 'departure', {'IJPP:sez'}, 0, 2000, {}, merged=False)
        self.assertEqual([(r['routeName'], r['destination']) for r in rows], [('BUS 1824', 'Opčine')])
        self.assertEqual(replacement.timetable_rows(plan, 'arrival', {'IJPP:sez'}, 0, 2000, {}, merged=False), [])

    def test_the_bus_from_opcine_arrives_in_sezana(self):
        from prestop_api import replacement
        plan = {'synthetic': [self.bus(comesFrom='Opčine')]}
        rows = replacement.timetable_rows(plan, 'arrival', {'IJPP:sez'}, 0, 2000, {}, merged=False)
        self.assertEqual([r['destination'] for r in rows], ['Opčine'])
        self.assertEqual(replacement.timetable_rows(plan, 'departure', {'IJPP:sez'}, 0, 2000, {}, merged=False), [])

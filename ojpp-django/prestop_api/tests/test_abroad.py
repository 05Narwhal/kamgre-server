"""Slovenia only: places abroad are text, never stops, shapes or vehicles (abroad.py)."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from prestop_api import abroad, mapping, trips
from prestop_statistics.models import TripDelay, TripStops


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

    def test_international_stations_are_abroad_by_their_country_code(self):
        self.assertTrue(abroad.is_abroad_stop('Szombathely', 'IJPP:INTL-5500028'))
        self.assertTrue(abroad.is_abroad_stop('Rijeka', 'IJPP:INTL-7800013'))
        self.assertTrue(abroad.is_abroad_stop('Villach Hauptbahnhof', 'IJPP:INTL-8100147'))
        self.assertTrue(abroad.is_abroad_stop('Gorizia Centrale', 'IJPP:INTL-8300096'))
        self.assertFalse(abroad.is_abroad_stop('Lendava / Lendva', 'IJPP:INTL-7900070'))  # 79: Slovenia's own
        self.assertTrue(abroad.is_abroad_stop('Hodos Drzavna meja', 'IJPP:INTL-7943778'))  # only the border point
        self.assertFalse(abroad.is_abroad_stop('Maribor', 'IJPP:1122913'))
        self.assertFalse(abroad.is_abroad_stop('Maribor'))

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

    def test_a_train_to_wien_ends_at_its_last_station_in_slovenia(self):
        """The feed's international stations (Nov 2026) carry no country mark, only their id."""
        mb = _stop('IJPP:1122913', 'Maribor', 46.56, 15.66)
        spilje = _stop('IJPP:INTL-8100082', 'Spielfeld-Straß', 46.71, 15.63)
        wien = _stop('IJPP:INTL-8100001', 'Wien Hauptbahnhof', 48.18, 16.38)
        lj = _stop('IJPP:1122804', 'Ljubljana', 46.05, 14.51)
        with mock.patch.object(trips.tracks.tracks, 'track', return_value=(None, False)):
            static = _static(_trip([lj, mb, spilje, wien], mode='RAIL', name='EC 70', headsign='Ljubljana - Wien'))
        self.assertEqual([s['name'] for s in static['stops']], ['Ljubljana', 'Maribor'])
        self.assertEqual(static['destination'], 'Dunaj / Wien')  # where it really goes, as text
        self.assertEqual([round(x, 5) for x in static['geometry'][-1]], [mb['lon'], mb['lat']])

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


    def test_no_vehicle_on_its_way_to_an_international_station(self):
        positions = [{'id': 'v1', 'vehicle': {'trip': {'tripId': 'IJPP:t1'}, 'position': {'latitude': 47.75, 'longitude': 16.12},
                                              'stopId': 'IJPP:INTL-8100035', 'timestamp': 1}}]
        names = {'IJPP:INTL-8100035': 'Leibnitz'}
        routes = {'IJPP:r1': {'mode': 'RAIL'}}
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


# Stations as the national feed has them: Slovenia's own ids, others by UIC country (81 Austria, 78 Croatia, ...).
S = {name: {'gtfsId': sid, 'name': name, 'lat': 46.0, 'lon': 15.0} for name, sid in {
    'München Hauptbahnhof': 'IJPP:INTL-8000261', 'Stuttgart Hauptbahnhof': 'IJPP:INTL-8000096', 'Villach Hauptbahnhof': 'IJPP:INTL-8100147',
    'Graz Hauptbahnhof': 'IJPP:INTL-8100173', 'Spielfeld-Straß': 'IJPP:INTL-8100999', 'Wien Hauptbahnhof': 'IJPP:INTL-8103000',
    'Zagreb Glavni kolodvor': 'IJPP:INTL-7800020', 'Zaprešić': 'IJPP:INTL-7800021', 'Rijeka': 'IJPP:INTL-7800013', 'Vinkovci': 'IJPP:INTL-7800050',
    'Budapest-Déli': 'IJPP:INTL-5500007', 'Szombathely': 'IJPP:INTL-5500028',
    'Jesenice': 'IJPP:1122836', 'Ljubljana': 'IJPP:1122804', 'Dobova': 'IJPP:1122782', 'Maribor': 'IJPP:1122913', 'Šentilj': 'IJPP:1122935',
    'Ilirska Bistrica': 'IJPP:1123053', 'Hodoš': 'IJPP:1122962',
}.items()}
DAY = 1_793_000_000  # a service day's midnight


def _leg(trip_id, name, *calls, delays=None):
    """A timetable trip (scheduled._trips_for): `calls` are (station, minutes after midnight)."""
    seconds = [DAY + at * 60 for _, at in calls]
    delays = delays or [None] * len(calls)
    live = [at + (d or 0) for at, d in zip(seconds, delays)]
    return {'id': trip_id, 'route': {'shortName': name, 'mode': 'RAIL', 'gtfsId': f'r-{name}'}, 'stops': [S[s] for s, _ in calls], 'serviceDay': DAY,
            'scheduledArrivals': seconds, 'scheduledDepartures': seconds, 'arrivals': live, 'departures': live, 'delays': delays}


# One train per family and direction, cut as the feed cuts it (leg names and categories as it gives them).
FAMILIES = {
    'RG out': ([_leg('IJPP:1', 'RG 678', ('Maribor', 1232), ('Šentilj', 1242)), _leg('IJPP:INTL-2', 'IR 678', ('Šentilj', 1243), ('Spielfeld-Straß', 1250), ('Graz Hauptbahnhof', 1293))],
               ['Maribor', 'Šentilj'], [], ['Spielfeld-Straß', 'Graz Hauptbahnhof'], None, 'Gradec / Graz'),
    'RG back': ([_leg('IJPP:INTL-1', 'IR 679', ('Graz Hauptbahnhof', 400), ('Spielfeld-Straß', 440), ('Šentilj', 450)), _leg('IJPP:2', 'RG 679', ('Šentilj', 451), ('Maribor', 461))],
                ['Šentilj', 'Maribor'], ['Graz Hauptbahnhof', 'Spielfeld-Straß'], [], 'Gradec / Graz', None),
    'EC out': ([_leg('IJPP:INTL-1', 'EC 115', ('München Hauptbahnhof', 616), ('Villach Hauptbahnhof', 880), ('Jesenice', 930)), _leg('IJPP:2', 'EC 115', ('Jesenice', 935), ('Ljubljana', 1000), ('Dobova', 1114)),
                _leg('IJPP:INTL-3', 'EC 115', ('Dobova', 1135), ('Zaprešić', 1150), ('Zagreb Glavni kolodvor', 1160))],
               ['Jesenice', 'Ljubljana', 'Dobova'], ['München Hauptbahnhof', 'Villach Hauptbahnhof'], ['Zaprešić', 'Zagreb Glavni kolodvor'], 'München', 'Zagreb'),
    'EC back': ([_leg('IJPP:INTL-1', 'EC 78', ('Zagreb Glavni kolodvor', 426), ('Zaprešić', 440), ('Dobova', 451)), _leg('IJPP:2', 'EC 78', ('Dobova', 466), ('Maribor', 615)),
                 _leg('IJPP:INTL-3', 'EC 78', ('Maribor', 624), ('Graz Hauptbahnhof', 700), ('Wien Hauptbahnhof', 847))],
                ['Dobova', 'Maribor'], ['Zagreb Glavni kolodvor', 'Zaprešić'], ['Graz Hauptbahnhof', 'Wien Hauptbahnhof'], 'Zagreb', 'Dunaj / Wien'),
    'EN out': ([_leg('IJPP:2', 'EN 40414', ('Ljubljana', 1100), ('Maribor', 1249)), _leg('IJPP:INTL-3', 'EN 40414', ('Maribor', 1258), ('Graz Hauptbahnhof', 1320), ('Stuttgart Hauptbahnhof', 1958))],
               ['Ljubljana', 'Maribor'], [], ['Graz Hauptbahnhof', 'Stuttgart Hauptbahnhof'], None, 'Stuttgart'),
    'EN back': ([_leg('IJPP:INTL-1', 'EN 40465', ('Stuttgart Hauptbahnhof', 100), ('Graz Hauptbahnhof', 500), ('Maribor', 539)), _leg('IJPP:2', 'EN 40465', ('Maribor', 545), ('Ljubljana', 700))],
                ['Maribor', 'Ljubljana'], ['Stuttgart Hauptbahnhof', 'Graz Hauptbahnhof'], [], 'Stuttgart', None),
    'MV in': ([_leg('IJPP:INTL-1', '480', ('Vinkovci', 900), ('Rijeka', 1146), ('Ilirska Bistrica', 1218)), _leg('IJPP:2', 'MV 480', ('Ilirska Bistrica', 1220), ('Ljubljana', 1324))],
              ['Ilirska Bistrica', 'Ljubljana'], ['Vinkovci', 'Rijeka'], [], 'Vinkovci', None),
    'MV out': ([_leg('IJPP:2', 'MV 481', ('Ljubljana', 500), ('Ilirska Bistrica', 604)), _leg('IJPP:INTL-1', '481', ('Ilirska Bistrica', 606), ('Rijeka', 650), ('Vinkovci', 900))],
               ['Ljubljana', 'Ilirska Bistrica'], [], ['Rijeka', 'Vinkovci'], None, 'Vinkovci'),
    'IC in': ([_leg('IJPP:INTL-1', 'IC 246', ('Budapest-Déli', 540), ('Szombathely', 700), ('Hodoš', 787)), _leg('IJPP:2', 'MV 246', ('Hodoš', 799), ('Ljubljana', 1004))],
              ['Hodoš', 'Ljubljana'], ['Budapest-Déli', 'Szombathely'], [], 'Budimpešta / Budapest', None),
    # One trip that runs on abroad itself: the feed's IC 351, no other leg.
    'IC one trip': ([_leg('IJPP:INTL-1', 'IC 351', ('Maribor', 300), ('Šentilj', 310), ('Graz Hauptbahnhof', 360), ('Szombathely', 480), ('Budapest-Déli', 640))],
                    ['Maribor', 'Šentilj'], [], ['Graz Hauptbahnhof', 'Szombathely', 'Budapest-Déli'], None, 'Budimpešta / Budapest'),
}


class WholeRunTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.dict(abroad._feed_ends, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_family_both_ways_reads_its_whole_route(self):
        for label, (legs, inside, before, after, comes, goes) in FAMILIES.items():
            with self.subTest(label):
                run = abroad.main_run(legs)
                self.assertEqual([s['name'] for s in run['stops'] if not abroad.is_abroad_stop(s['name'], s['gtfsId'])], inside)
                whole = abroad.whole_run(run, legs)
                self.assertEqual([r['name'] for r in whole['before']], before)
                self.assertEqual([r['name'] for r in whole['after']], after)
                self.assertEqual((whole['comes'], whole['goes']), (comes, goes))
                self.assertTrue(all(r['abroad'] for r in whole['before'] + whole['after']))

    def test_every_name_learns_its_ends_from_the_feed(self):
        for label, (legs, *_, comes, goes) in FAMILIES.items():
            with self.subTest(label):
                abroad.learn(legs)
                for leg in legs:
                    self.assertEqual(abroad.train_ends(leg['route']['shortName'], 'Maribor', 'Ljubljana'), (comes, goes))

    def test_a_stop_abroad_is_text_only_by_the_timetable(self):
        legs = FAMILIES['EC out'][0]
        row = abroad.whole_run(legs[1], legs)['after'][-1]
        self.assertEqual(set(row), {'name', 'abroad', 'country', 'scheduledArrival', 'scheduledDeparture'})
        self.assertEqual(row['country'], 'HR')

    def test_a_stop_abroad_knows_its_country_from_the_feed(self):
        self.assertEqual(abroad.country_of('Villach Hauptbahnhof', 'IJPP:INTL-8100147'), 'AT')
        self.assertEqual(abroad.country_of('München Hauptbahnhof', 'IJPP:INTL-8000261'), 'DE')
        self.assertEqual(abroad.country_of('Szombathely', 'IJPP:INTL-5500028'), 'HU')
        self.assertEqual(abroad.country_of('Tarvisio autostazione (I)'), 'IT')
        self.assertEqual(abroad.country_of('Hodos Drzavna meja', 'IJPP:INTL-7943778'), None)  # 79: no country to name
        self.assertEqual(abroad.country_of('Nowhere', 'IJPP:INTL-9900001'), None)  # one we don't know: no mark, no guess

    def test_a_delay_abroad_only_where_the_feed_is_live(self):
        legs = [_leg('IJPP:2', 'EC 79', ('Ljubljana', 500), ('Dobova', 600)), _leg('IJPP:INTL-3', 'EC 79', ('Dobova', 620), ('Zaprešić', 635), ('Zagreb Glavni kolodvor', 650), delays=[None, 120, None])]
        rows = abroad.whole_run(legs[0], legs)['after']
        self.assertEqual(rows[0]['delaySeconds'], 120)
        self.assertEqual(rows[0]['effectiveDeparture'], mapping.iso(DAY + 635 * 60 + 120))
        self.assertNotIn('delaySeconds', rows[1])

    def test_a_live_zero_abroad_does_not_read_as_on_time(self):
        legs = [_leg('IJPP:2', 'EC 79', ('Ljubljana', 500), ('Dobova', 600)), _leg('IJPP:INTL-3', 'EC 79', ('Dobova', 620), ('Zaprešić', 635), delays=[None, 0])]
        row = abroad.whole_run(legs[0], legs)['after'][0]
        self.assertNotIn('delaySeconds', row)
        self.assertNotIn('effectiveDeparture', row)

    def test_a_leg_too_long_after_is_not_the_same_train(self):
        legs = [_leg('IJPP:2', 'EC 79', ('Ljubljana', 500), ('Dobova', 600)), _leg('IJPP:INTL-3', 'EC 79', ('Dobova', 600 + 61), ('Zagreb Glavni kolodvor', 700))]
        self.assertEqual(abroad.whole_run(legs[0], legs)['after'], [])

    def test_a_leg_that_left_before_it_arrived_is_not_joined(self):
        legs = [_leg('IJPP:2', 'EC 79', ('Ljubljana', 500), ('Dobova', 600)), _leg('IJPP:INTL-3', 'EC 79', ('Dobova', 590), ('Zagreb Glavni kolodvor', 640))]
        self.assertEqual(abroad.whole_run(legs[0], legs)['goes'], None)

    def test_the_table_fills_an_end_the_feed_does_not_reach(self):
        self.assertEqual(abroad.train_ends('EC 115', 'Jesenice', 'Dobova'), ('München', 'Zagreb'))  # feed silent
        abroad.learn([_leg('IJPP:2', 'EC 115', ('Jesenice', 500), ('Dobova', 600)), _leg('IJPP:INTL-3', 'EC 115', ('Dobova', 610), ('Vinkovci', 900))])
        self.assertEqual(abroad.train_ends('EC 115', 'Jesenice', 'Dobova'), ('München', 'Vinkovci'))  # the feed wins, the table fills

    def test_a_replacement_bus_is_no_train_of_that_number(self):
        abroad.learn(FAMILIES['EN back'][0])
        self.assertFalse(abroad.crosses('BUS 40465'))
        self.assertEqual(abroad.train_ends('BUS 40465', 'Maribor', 'Ljubljana'), (None, None))

    def test_a_domestic_train_has_no_whole_run(self):
        legs = [_leg('IJPP:9', 'LPV 2400', ('Ljubljana', 500), ('Jesenice', 560))]
        abroad.learn(legs)
        self.assertFalse(abroad.crosses('LPV 2400'))
        self.assertEqual(abroad.whole_run(legs[0], legs), {'before': [], 'after': [], 'comes': None, 'goes': None})

    def test_stuttgart_reads_as_the_town(self):
        self.assertEqual(abroad.place('Stuttgart Hauptbahnhof'), 'Stuttgart')
        self.assertEqual(abroad.place('Zagreb Glavni kolodvor'), 'Zagreb')

    def test_the_train_page_takes_the_leg_in_slovenia(self):
        from prestop_api import trains
        legs = FAMILIES['EC out'][0]
        with mock.patch.object(trains, 'runs_on', return_value=legs):
            self.assertEqual(trains.find_run('115', None)['id'], 'IJPP:2')

    def test_the_trip_keeps_its_stops_in_slovenia_and_adds_the_rest_beside_them(self):
        legs = FAMILIES['MV in'][0]
        abroad.learn(legs)
        static = {'id': 'IJPP:2', 'routeName': 'MV 480', 'destination': 'Ljubljana', 'mode': 'rail'}
        stops = [{'name': 'Ilirska Bistrica'}, {'name': 'Ljubljana'}]
        with mock.patch('prestop_api.scheduled.loaded_trips', return_value=legs):
            out = trips._outside_slovenia(static, stops, datetime.fromtimestamp(DAY + 12 * 3600, ZoneInfo('Europe/Ljubljana')).date())
        self.assertEqual([r['name'] for r in out['stopsBefore']], ['Vinkovci', 'Rijeka'])
        self.assertNotIn('stopsAfter', out)
        self.assertEqual(out['comesFrom'], 'Vinkovci')
        self.assertEqual(out['longName'], 'Vinkovci – Ljubljana')

    def test_with_the_timetable_not_in_memory_the_table_still_names_the_route(self):
        abroad.learn(FAMILIES['MV in'][0])
        static = {'id': 'IJPP:2', 'routeName': 'MV 480', 'destination': 'Ljubljana', 'mode': 'rail', 'comesFrom': 'Reka / Rijeka'}
        with mock.patch('prestop_api.scheduled.loaded_trips', return_value=[]):
            out = trips._outside_slovenia(static, [{'name': 'Ilirska Bistrica'}, {'name': 'Ljubljana'}], None)
        self.assertEqual(out, {'longName': 'Reka / Rijeka – Ljubljana'})

    def test_a_domestic_trip_gets_nothing_new(self):
        static = {'id': 'IJPP:9', 'routeName': 'LPV 2400', 'destination': 'Jesenice', 'mode': 'rail'}
        self.assertEqual(trips._outside_slovenia(static, [{'name': 'Ljubljana'}, {'name': 'Jesenice'}], None), {})


class LineTests(SimpleTestCase):
    def test_a_line_to_zagreb_says_so_and_keeps_its_stops_in_slovenia(self):
        jes, dob = _stop('IJPP:jes', 'Jesenice', 46.43, 14.06), _stop('IJPP:dob', 'Dobova', 45.89, 15.65)
        route = {'gtfsId': 'IJPP:r', 'shortName': 'EC 115', 'mode': 'RAIL', 'agency': {'gtfsId': 'IJPP:a', 'name': 'SŽ'},
                 'patterns': [{'code': 'p', 'directionId': 0, 'headsign': 'Dobova', 'stops': [jes, dob], 'tripsForDate': [],
                               'shapeCoordinates': [[jes['lon'], jes['lat']], [dob['lon'], dob['lat']]]}]}
        with mock.patch.object(trips, '_corrected', side_effect=lambda stops, replacement=False: stops), \
                mock.patch.object(trips, 'road_shape', side_effect=lambda raw, *a, **k: (raw, True)), \
                mock.patch.object(trips.stopfix, 'renamed', side_effect=lambda sid, name: name), \
                mock.patch.object(trips.mapping, 'route_ends', return_value=('Jesenice', 'Dobova')):
            line, _ = trips.build_line(route, date(2026, 11, 3))
        pattern = line['patterns'][0]
        self.assertEqual(line['longName'], 'München – Zagreb')
        self.assertEqual(pattern['goesTo'], 'Zagreb')
        self.assertEqual([s['name'] for s in pattern['stops']], ['Jesenice', 'Dobova'])


class OnTheMapTests(SimpleTestCase):
    """The map by the timetable: an international train is one vehicle, in Slovenia only."""

    def setUp(self):
        patcher = mock.patch.dict(abroad._feed_ends, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def vehicles(self, legs, minute, drops=None):
        from prestop_api import scheduled
        abroad.learn(legs)
        table = [{**t, 'pattern': t['id'], 'alertIds': [], 'headsign': ''} for t in legs]
        with mock.patch.object(scheduled.timetable, 'get', return_value=mock.Mock(value=table)), \
                mock.patch.object(scheduled.shapes, 'get', return_value=mock.Mock(value={})), \
                mock.patch.object(scheduled, '_derive', return_value={'sections': {}, 'synthetic': []}), \
                mock.patch.object(scheduled.closures, 'train_alert_ids', return_value=[]), \
                mock.patch.object(scheduled.zamudil, 'class_of', return_value=None), \
                mock.patch.object(scheduled.tracks.tracks, 'track', return_value=(None, False)):
            return scheduled.vehicles(now=DAY + minute * 60, live={}, updates={}, drops=drops)

    def test_a_train_from_muenchen_shows_from_its_first_station_in_slovenia(self):
        legs = FAMILIES['EC out'][0]
        self.assertEqual(self.vehicles(legs, 700), [])  # between München and Villach
        self.assertEqual(self.vehicles(legs, 900), [])  # Villach to Jesenice, still abroad
        [train] = self.vehicles(legs, 960)
        self.assertEqual((train['tripId'], train['comesFrom'], train['destination']), ('IJPP:2', 'München', 'Zagreb'))

    def test_a_train_to_zagreb_goes_at_its_last_station_in_slovenia(self):
        legs = FAMILIES['EC out'][0]
        [standing] = self.vehicles(legs, 1134)  # the stand at Dobova, its last minutes
        self.assertEqual((standing['nextStop'], standing['stopped'], standing['destination']), ('Dobova', True, 'Zagreb'))
        self.assertEqual(self.vehicles(legs, 1140), [])  # on its way to Zaprešić

    def test_where_it_changes_legs_at_the_border_it_is_one_train(self):
        legs = FAMILIES['RG out'][0]  # arrives at Šentilj 1242 on one leg, leaves 1243 on the other
        drops = []
        [train] = self.vehicles(legs, 1242, drops)
        self.assertEqual(train['tripId'], 'IJPP:1')
        self.assertEqual(len(drops), 1)

    def test_it_comes_back_when_it_re_enters(self):
        legs = FAMILIES['RG back'][0]
        self.assertEqual(self.vehicles(legs, 420), [])  # Graz to Spielfeld
        self.assertEqual(self.vehicles(legs, 445), [])  # Spielfeld to Šentilj
        [train] = self.vehicles(legs, 455)
        self.assertEqual((train['tripId'], train['comesFrom']), ('IJPP:2', 'Gradec / Graz'))

    def test_two_parts_of_one_number_both_in_slovenia_stay_two(self):
        """EN 415: a part from Jesenice and one from Maribor run at the same time under one number."""
        legs = [_leg('IJPP:1', 'EN 415', ('Jesenice', 414), ('Ljubljana', 480), ('Dobova', 593)), _leg('IJPP:INTL-2', 'EN 415', ('Maribor', 539), ('Ljubljana', 600), ('Dobova', 670))]
        self.assertEqual(len(self.vehicles(legs, 560)), 2)


class KeptDelayTests(TestCase):
    """Delays abroad outlive the feed's report of them (spec 2026-11-03 L3): the collector's TripDelay keeps them."""
    LEGS = [_leg('IJPP:1', 'RG 678', ('Maribor', 1232), ('Šentilj', 1242)), _leg('IJPP:INTL-2', 'IR 678', ('Šentilj', 1243), ('Spielfeld-Straß', 1250), ('Graz Hauptbahnhof', 1293))]
    SERVICE_DATE = datetime.fromtimestamp(DAY + 12 * 3600, ZoneInfo('Europe/Ljubljana')).date()

    def _keep(self, trip_id, delays, day=None):
        now = timezone.now()
        TripDelay.objects.create(service_date=day or self.SERVICE_DATE, trip_id=trip_id, route_id='r', operator_id='o', direction='0', stop_delays=delays, first_seen=now, last_seen=now)
        TripStops.objects.update_or_create(trip_id=trip_id, defaults={'route_id': 'r', 'mode': 'RAIL', 'seen': self.SERVICE_DATE, 'stops': [
            [i + 1, S[name]['gtfsId'], name, 0] for i, name in enumerate(('Šentilj', 'Spielfeld-Straß', 'Graz Hauptbahnhof'))]})

    def test_a_feed_that_stopped_reporting_keeps_the_delay(self):
        self._keep('IJPP:INTL-2', {'2': 240, '3': 300})
        after = abroad.whole_run(self.LEGS[0], self.LEGS, abroad.kept_delays(self.LEGS))['after']
        self.assertEqual([r.get('observedDelaySeconds') for r in after], [240, 300])
        self.assertTrue(all('delaySeconds' not in r for r in after))  # not live any more: only what was seen

    def test_a_kept_zero_is_no_measurement(self):
        self._keep('IJPP:INTL-2', {'2': 0, '3': 60})
        after = abroad.whole_run(self.LEGS[0], self.LEGS, abroad.kept_delays(self.LEGS))['after']
        self.assertNotIn('observedDelaySeconds', after[0])
        self.assertEqual(after[1]['observedDelaySeconds'], 60)

    def test_nothing_kept_says_nothing(self):
        after = abroad.whole_run(self.LEGS[0], self.LEGS, abroad.kept_delays(self.LEGS))['after']
        self.assertTrue(all('observedDelaySeconds' not in r for r in after))

    def test_another_days_run_is_not_this_run(self):
        self._keep('IJPP:INTL-2', {'2': 240}, day=self.SERVICE_DATE - timedelta(days=1))
        self.assertEqual(abroad.kept_delays(self.LEGS), {})

    def _next_day(self):
        """The timetable in memory holds several service days, so one trip id comes once per day (EC 115, 3 Nov)."""
        return [{**t, 'serviceDay': t['serviceDay'] + 86400, **{k: [x + 86400 for x in t[k]] for k in ('scheduledArrivals', 'scheduledDepartures', 'arrivals', 'departures')}} for t in self.LEGS]

    def test_the_same_trip_on_the_next_day_does_not_hide_todays_delays(self):
        self._keep('IJPP:INTL-2', {'3': 300})
        tomorrow = self._next_day()
        legs = self.LEGS + tomorrow
        kept = abroad.kept_delays(legs)
        self.assertEqual(abroad.whole_run(self.LEGS[0], legs, kept)['after'][-1]['observedDelaySeconds'], 300)
        self.assertNotIn('observedDelaySeconds', abroad.whole_run(tomorrow[0], legs, kept)['after'][-1])  # only that day's run

    def test_the_trip_takes_the_run_of_its_own_day(self):
        self._keep('IJPP:INTL-2', {'3': 300})
        static = {'id': 'IJPP:1', 'routeName': 'RG 678', 'destination': 'Šentilj'}
        with mock.patch.object(abroad, 'crosses', return_value=True), mock.patch('prestop_api.scheduled.loaded_trips', return_value=self._next_day() + self.LEGS):
            out = trips._outside_slovenia(static, [{'name': 'Maribor'}, {'name': 'Šentilj'}], self.SERVICE_DATE)
        self.assertEqual(out['stopsAfter'][-1]['observedDelaySeconds'], 300)
        self.assertEqual(out['stopsAfter'][-1]['scheduledArrival'], abroad.whole_run(self.LEGS[0], self.LEGS)['after'][-1]['scheduledArrival'])

    def test_the_trip_serves_them(self):
        self._keep('IJPP:INTL-2', {'3': 300})
        static = {'id': 'IJPP:1', 'routeName': 'RG 678', 'destination': 'Šentilj'}
        with mock.patch.object(abroad, 'crosses', return_value=True), mock.patch('prestop_api.scheduled.loaded_trips', return_value=self.LEGS):
            out = trips._outside_slovenia(static, [{'name': 'Maribor'}, {'name': 'Šentilj'}], self.SERVICE_DATE)
        self.assertEqual(out['stopsAfter'][-1]['observedDelaySeconds'], 300)

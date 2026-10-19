import json
from datetime import date, datetime, timezone
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import driving, journeys, mapping, pricing
from prestop_api.tests.test_mapping import PLACE
from prestop_api.upstream import Snapshot, UpstreamError

START = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc).timestamp()
FUEL = {'petrol': 1.742, 'diesel': 1.881, 'valid': 'od 13. 10. do 19. 10. 2026', 'from': '2026-10-13', 'to': '2026-10-19', 'checked': '2026-10-19'}
# gov.si's CSV as read on Monday 2026-10-19, 18:50: the first row is tomorrow's.
GOV_CSV = ('﻿"Datum veljavnosti ","Maloprodajna cena NMB 95 (evro/liter)","Maloprodajna cena dizel goriva (evro/liter)"\n'
           '"od 20. 10. do 26. 10. 2026","1.702","1.923"\n"od 13. 10. do 19. 10. 2026","1.742","1.881"\n'
           '"od 6. 10. do 12. 10. 2026","1.744","1.883"\n"od 29. 9. do 5. 10. 2026","1.76","1.929"\n')
at = lambda m: mapping.iso(START + m * 60)


def car_leg(km=20.0, motorway=False, parking=None, minute=0):
    car = {'distanceMeters': round(km * 1000), 'fuelLitres': None, 'fuelCents': None, 'motorway': motorway}
    if parking:
        car['parking'] = {'name': parking, 'feeCents': None, 'parkAndRide': 'P+R' in parking, 'lat': 46.04, 'lon': 14.46}
    return {'id': f'leg:c{minute}', 'mode': 'car', 'tripId': None, 'geometry': [], 'effectiveDeparture': at(minute), 'effectiveArrival': at(minute + 20), 'car': car}


def bus(minute, feed='LPP'):
    return {'id': f'leg:b{minute}', 'mode': 'bus', 'tripId': f'{feed}:t{minute}', 'routeId': f'{feed}:r', 'operatorId': 'LPP:lpp', 'routeName': '6',
            'geometry': [[14.46, 46.04], [14.50, 46.05]], 'effectiveDeparture': at(minute), 'effectiveArrival': at(minute + 15)}


def price(*legs, car=None, lpg=None, language='en'):
    profile = {'cards': [], 'bikeMemberships': [], 'scooterPasses': [], **({'car': car} if car else {})}
    with mock.patch.object(driving, 'fuel', return_value=FUEL), mock.patch.object(driving, 'lpg', return_value=lpg):
        return pricing.price_journey({'legs': list(legs)}, profile, language)


def station(name, lpg, petrol=1.742):
    return {'pk': 1, 'name': name, 'prices': {'95': petrol, 'dizel': 1.881, 'avtoplin-lpg': lpg}}


def responses(*bodies):
    """Mocked gov.si / goriva.si answers, one per request."""
    out = []
    for body in bodies:
        resp = mock.MagicMock(status_code=200)
        resp.__enter__.return_value = resp
        resp.raw.read.return_value = (body if isinstance(body, str) else json.dumps(body)).encode('utf-8')
        out.append(resp)
    return out


class CarCostTests(SimpleTestCase):
    def test_fuel_at_the_regulated_price(self):
        j = price(car_leg(20), car={'fuel': 'diesel', 'litresPer100km': 5.0, 'vignette': True})
        self.assertEqual(j['legs'][0]['car']['fuelLitres'], 1.0)
        self.assertEqual(j['legs'][0]['price']['amountCents'], 189)  # 1 l × 1.881 €
        self.assertEqual(j['price']['totalCents'], 189)

    def test_no_car_given_means_an_average_petrol_car_and_says_so(self):
        j = price(car_leg(20))
        self.assertEqual(j['legs'][0]['price']['amountCents'], 227)  # 1.3 l × 1.742 €
        self.assertIn('average petrol car', j['legs'][0]['price']['basis'])

    def test_motorway_without_a_vignette_adds_the_7_day_vignette_once(self):
        j = price(car_leg(30, motorway=True), car_leg(10, motorway=True, minute=40), car={'fuel': 'petrol', 'litresPer100km': 6.0, 'vignette': False})
        self.assertEqual([l['car'].get('vignetteCents') for l in j['legs']], [1600, None])
        self.assertEqual(j['legs'][0]['price']['amountCents'], 314 + 1600)  # 1.8 l × 1.742 € = 3.14 €

    def test_electric_charges_an_estimate_and_lpg_is_unknown(self):
        e = price(car_leg(100), car={'fuel': 'electric', 'litresPer100km': 18.0, 'vignette': True})
        self.assertEqual((e['legs'][0]['car']['energyKwh'], e['legs'][0]['price']['amountCents']), (18.0, 990))  # 18 kWh × 0.55 €
        self.assertIn('estimate', e['legs'][0]['price']['basis'])
        lpg = price(car_leg(100), car={'fuel': 'lpg', 'litresPer100km': 8.0, 'vignette': True})
        self.assertIsNone(lpg['price']['totalCents'])  # no LPG price known

    def test_lpg_at_the_usual_station_price(self):
        usual = {'lpg': 1.016, 'stations': 105, 'checked': '2026-10-19'}
        j = price(car_leg(100), car={'fuel': 'lpg', 'litresPer100km': 8.0, 'vignette': True}, lpg=usual, language='sl')
        leg = j['legs'][0]['price']
        self.assertEqual((leg['amountCents'], j['price']['totalCents']), (813, 813))  # 8 l × 1.016 €
        self.assertIn('avtoplin, 1,016 €/l, srednja cena 105 črpalk', leg['basis'])
        self.assertEqual((leg['sourceUrl'], leg['checked']), ('https://goriva.si/', '2026-10-19'))

    def test_ljubljana_park_and_ride_includes_two_bus_rides(self):
        j = price(car_leg(15, parking='P+R Dolgi most'), bus(30), bus(50), bus(200))
        self.assertEqual((j['legs'][0]['car']['parking']['feeCents'], j['legs'][0]['car']['parking']['fee']), (150, 'paid'))
        self.assertEqual([l['price']['amountCents'] for l in j['legs'][1:]], [0, 0, 150])
        self.assertEqual(j['legs'][1]['price']['basis'], 'Included in the P+R parking ticket')

    def test_an_unknown_car_park_makes_the_total_unknown(self):
        j = price(car_leg(15, parking='Parkirišče pri postaji'))
        self.assertIsNone(j['price']['totalCents'])
        self.assertEqual((j['legs'][0]['car']['parking']['feeCents'], j['legs'][0]['car']['parking']['fee']), (None, 'unknown'))


class FuelPriceTests(SimpleTestCase):
    def read(self, text=GOV_CSV, status=200):
        resp, = responses(text)
        resp.status_code = status
        with mock.patch.object(driving, 'session') as session:
            session.return_value.get.return_value = resp
            return driving._load_fuel()

    def on(self, day, rows=None, fetched=datetime(2026, 10, 19, 16, 50, tzinfo=timezone.utc)):
        with mock.patch.object(driving.fuel_prices, 'get', return_value=Snapshot(rows or self.read(), fetched.timestamp())):
            return driving.fuel(day)

    def test_periods_carry_the_year_once_at_the_end(self):
        self.assertEqual(driving.period('od 29. 9. do 5. 10. 2026'), (date(2026, 9, 29), date(2026, 10, 5)))
        self.assertEqual(driving.period('od 10. 3. do 23. 3. 2026'), (date(2026, 3, 10), date(2026, 3, 23)))
        self.assertEqual(driving.period('od 30. 12. do 5. 1. 2027'), (date(2026, 12, 30), date(2027, 1, 5)))
        self.assertEqual(driving.period('od 30. 12. 2026 do 5. 1. 2027'), (date(2026, 12, 30), date(2027, 1, 5)))

    def test_every_period_is_read_newest_first(self):
        rows = self.read()
        self.assertEqual([(r['from'], r['petrol'], r['diesel']) for r in rows][:2], [('2026-10-20', 1.702, 1.923), ('2026-10-13', 1.742, 1.881)])
        self.assertEqual(len(rows), 4)

    def test_today_uses_todays_prices_though_tomorrows_are_listed(self):
        self.assertEqual((self.on(date(2026, 10, 19))['petrol'], self.on(date(2026, 10, 19))['from']), (1.742, '2026-10-13'))
        self.assertEqual(self.on(date(2026, 10, 20))['diesel'], 1.923)  # a plan for Tuesday: the new prices
        self.assertEqual(self.on(date(2026, 10, 29))['from'], '2026-10-20')  # not listed yet: the newest begun
        self.assertEqual(self.on(date(2026, 10, 19))['checked'], '2026-10-19')  # the day gov.si was read

    def test_a_bad_csv_or_no_gov_si_falls_back_to_the_tariff_file(self):
        with self.assertRaises(UpstreamError):
            self.read('<html>maintenance</html>')
        with self.assertRaises(UpstreamError):
            self.read(status=503)
        with mock.patch.object(driving.fuel_prices, 'get', side_effect=UpstreamError('gov.si down')):
            prices = driving.fuel(date(2026, 10, 19))
        fallback = pricing.tariffs()['driving']['fuel']
        self.assertEqual((prices['valid'], prices['checked']), ('od 13. 10. do 19. 10. 2026', fallback['fallbackChecked']))

    def test_a_drive_says_the_price_per_litre_and_since_when(self):
        rows = self.read()
        with mock.patch.object(driving.fuel_prices, 'get', return_value=Snapshot(rows, datetime(2026, 10, 19, 16, 50, tzinfo=timezone.utc).timestamp())):
            today = pricing.price_journey({'legs': [car_leg(20)]}, {}, 'en')['legs'][0]['price']  # 06:00 UTC on Monday 19 Oct
            tomorrow = pricing.price_journey({'legs': [car_leg(20, minute=24 * 60)]}, {}, 'sl')['legs'][0]['price']
        self.assertEqual(today['amountCents'], 227)  # 1.3 l × 1.742 €
        self.assertIn('petrol, 1.742 €/l from 13 Oct', today['basis'])
        self.assertEqual(today['checked'], '2026-10-19')
        self.assertEqual(tomorrow['amountCents'], 222)  # 1.3 l × 1.702 €
        self.assertIn('bencin, 1,702 €/l od 20. 10.', tomorrow['basis'])


class LpgPriceTests(SimpleTestCase):
    def read(self, *pages):
        with mock.patch.object(driving, 'session') as session:
            session.return_value.get.side_effect = responses(*pages)
            out = driving._load_lpg()
            return out, [c.args[0] for c in session.return_value.get.call_args_list]

    def test_the_median_off_the_motorways_over_every_page(self):
        first = {'next': 'https://goriva.si/api/v1/search/?format=json&page=2',
                 'results': [station(f'PETROL KRANJ {i}', 0.99) for i in range(12)] + [station('PETROL ZALOKE AC - JUG', 1.076)] * 9}
        second = {'next': None, 'results': [station(f'OMV CELJE {i}', 1.069) for i in range(10)] + [station('SHELL KOPER', None, petrol=0.001), station('X', 0.001)]}
        usual, asked = self.read(first, second)
        self.assertEqual(usual, {'lpg': 0.99, 'stations': 22})  # 12 × 0.99, 10 × 1.069; motorway, empty and bogus left out
        self.assertEqual(asked, ['https://goriva.si/api/v1/search/?format=json', 'https://goriva.si/api/v1/search/?format=json&page=2'])

    def test_few_stations_or_a_foreign_next_page_is_no_price(self):
        with self.assertRaises(UpstreamError):
            self.read({'next': 'https://elsewhere.example/page2', 'results': [station(f'S {i}', 1.0) for i in range(19)]})
        with self.assertRaises(UpstreamError):
            self.read('<html>maintenance</html>')

    def test_never_waits_on_goriva_si_the_tariff_file_until_it_is_read(self):
        with mock.patch.object(driving.lpg_prices, 'get_nowait', return_value=None):
            self.assertEqual(driving.lpg(), pricing.tariffs()['driving']['lpg']['fallback'])
        read = Snapshot({'lpg': 1.02, 'stations': 100}, datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc).timestamp())
        with mock.patch.object(driving.lpg_prices, 'get_nowait', return_value=read):
            self.assertEqual(driving.lpg(), {'lpg': 1.02, 'stations': 100, 'checked': '2026-10-20'})


class DriveComparisonTests(SimpleTestCase):
    def test_every_journey_says_what_it_saves_against_driving(self):
        drive = {'id': 'd', 'legs': [{'mode': 'car'}], 'effectiveDeparture': at(0), 'effectiveArrival': at(30), 'price': {'totalCents': 900}}
        train = {'id': 't', 'legs': [{'mode': 'walk'}, {'mode': 'rail'}], 'effectiveDeparture': at(0), 'effectiveArrival': at(38), 'price': {'totalCents': 590}}
        ranked = pricing.rank([drive, train], {'costPreset': 'fastest', 'dateTime': datetime.fromtimestamp(START, timezone.utc), 'timeMode': 'departAt'})
        self.assertEqual([j['id'] for j in ranked], ['d', 't'])
        self.assertEqual((train['price']['savedCents'], train['price']['comparedTo']), (310, 'car'))


class CarSearchTests(SimpleTestCase):
    def request(self, **overrides):
        body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-19T08:00:00Z', 'timeMode': 'departAt',
                'minTransferSeconds': 180, 'modes': ['walk', 'car', 'carPark'], 'searchScope': 'all', 'riskMode': 'normal', **overrides}
        return journeys.parse_request(body, insane_enabled=False)

    def test_drive_and_park_and_ride_are_the_extra_searches(self):
        searches = dict(journeys.extra_searches(self.request()))
        self.assertEqual(searches['car']['modes'], {'direct': ['CAR'], 'directOnly': True})
        self.assertEqual(searches['carPark'], {})  # park_and_ride makes its own (ParkAndRideTests)

    def test_a_drive_to_a_car_free_place_parks_and_walks_within_the_query_budget(self):
        asked = []

        def query(q, v):
            asked.append(v['modes'])
            return {'planConnection': {'edges': [] if v['modes'].get('direct') == ['CAR'] else [{'node': {'legs': [
                {'mode': 'CAR', 'trip': None, 'start': {'scheduledTime': '2026-10-19T09:41:00+02:00'}, 'end': {'scheduledTime': '2026-10-19T10:01:00+02:00'}},
                {'mode': 'WALK', 'trip': None, 'duration': 300, 'start': {'scheduledTime': '2026-10-19T10:01:00+02:00'}, 'end': {'scheduledTime': '2026-10-19T10:06:00+02:00'}}]}}]}}
        journeys._extra_cache.clear()
        journeys._drive_cache.clear()
        req = self.request(modes=['walk', 'car'], dateTime='2026-10-19T07:41:00Z')
        with mock.patch('prestop_api.parking.nearest_drivable', return_value=None):  # no car park near the start
            out = journeys.with_extras({'planConnection': {'edges': []}}, req, query, budget=2)
            self.assertEqual([m['direct'] for m in asked], [['CAR'], ['CAR_PARKING']])
            self.assertEqual(len(out['planConnection']['edges']), 1)
            journeys._drive_cache.clear()
            asked.clear()
            journeys.with_extras({'planConnection': {'edges': []}}, req, query, budget=1)  # no query left for the second try
            self.assertEqual(len(asked), 1)

    def test_a_drive_is_asked_once_per_pair_of_places_and_moved_to_the_time_asked(self):
        asked = []

        def query(q, v):
            asked.append(v)
            return {'planConnection': {'edges': [{'node': {'legs': [{'mode': 'CAR', 'duration': 1500,
                    'start': {'scheduledTime': '2026-10-19T09:41:00+02:00'}, 'end': {'scheduledTime': '2026-10-19T10:06:00+02:00'}}]}}]}}
        journeys._extra_cache.clear()
        journeys._drive_cache.clear()
        with mock.patch('prestop_api.parking.nearest_drivable', return_value=None):
            first = journeys.with_extras({'planConnection': {'edges': []}}, self.request(modes=['walk', 'car'], dateTime='2026-10-19T07:41:00Z'), query)
            later = journeys.with_extras({'planConnection': {'edges': []}}, self.request(modes=['walk', 'car'], dateTime='2026-10-19T07:42:00Z'), query)
            by = journeys.with_extras({'planConnection': {'edges': []}}, self.request(modes=['walk', 'car'], dateTime='2026-10-19T09:00:00Z', timeMode='arriveBy'), query)
        self.assertEqual(len(asked), 1)  # C2: a minute later, or arriving by a time, reuses the drive
        leg = lambda out: out['planConnection']['edges'][0]['node']['legs'][0]
        self.assertEqual((leg(first)['start']['scheduledTime'], leg(later)['start']['scheduledTime']), ('2026-10-19T09:41:00+02:00', '2026-10-19T09:42:00+02:00'))
        self.assertEqual((leg(later)['end']['scheduledTime'], leg(by)['end']['scheduledTime']), ('2026-10-19T10:07:00+02:00', '2026-10-19T11:00:00+02:00'))

    def test_car_only_skips_the_main_search(self):
        asked = []
        data = journeys.plan(self.request(), lambda q, v: asked.append(v) or {})
        self.assertEqual((asked, data['planConnection']['edges']), ([], []))

    def test_a_driven_leg_knows_its_car_park(self):
        leg = {'mode': 'CAR', 'distance': 15733.0, 'to': {'lat': 46.04, 'lon': 14.46, 'vehicleParking': {'name': 'P+R Dolgi most'}}}
        with mock.patch.object(driving, 'motorway_km', return_value=0.0):
            car = driving.leg_car(leg, [[14.4, 46.1], [14.46, 46.04]])
        self.assertEqual((car['distanceMeters'], car['motorway'], car['parking']['name'], car['parking']['parkAndRide']), (15733, False, 'P+R Dolgi most', True))

    def test_motorway_detection_needs_two_km_on_vignette_roads(self):
        line = [[14.40, 46.10], [14.40 + 3.0 / 77.3, 46.10]]  # 3 km east
        cell = 0.001
        on_road = {(round(46.10 / cell), ix) for ix in range(round(14.40 / cell), round((14.40 + 3.0 / 77.3) / cell) + 1)}
        with mock.patch.object(driving, '_motorway_cells', return_value=(cell, on_road)):
            self.assertGreater(driving.motorway_km(line), driving.MOTORWAY_MIN_KM)
        with mock.patch.object(driving, '_motorway_cells', return_value=(cell, set())):
            self.assertEqual(driving.motorway_km(line), 0.0)


class ParkAndRideTests(SimpleTestCase):
    """Drive + park + ride (journeys.park_and_ride, spec 2026-10-19 C4): OTP drives to any stop, the car parks there."""
    KROPA = {'name': 'Kropa', 'latitude': 46.2905, 'longitude': 14.2066}
    LJUBLJANA = {'name': 'Ljubljana', 'latitude': 46.0503, 'longitude': 14.5039}
    PODNART = {'name': 'Podnart', 'lat': 46.2939, 'lon': 14.2585, 'stop': {'gtfsId': 'IJPP:podnart'}}
    NAKLO = {'name': 'Naklo', 'lat': 46.2740, 'lon': 14.3170, 'stop': {'gtfsId': 'IJPP:naklo'}}
    LOT = {'lat': 46.2948, 'lon': 14.2585, 'name': 'P Podnart', 'osmFee': 'no', 'parkRide': False, 'capacity': 40}  # 100 m north of the station

    def setUp(self):
        journeys._extra_cache.clear()
        journeys._drive_cache.clear()
        self.asked = []

    def request(self, **overrides):
        body = {'origin': self.KROPA, 'destination': self.LJUBLJANA, 'via': [], 'dateTime': '2026-10-20T07:00:00+02:00', 'timeMode': 'departAt',
                'minTransferSeconds': 180, 'modes': ['walk', 'bus', 'rail', 'carPark'], 'riskMode': 'normal', **overrides}
        return journeys.parse_request(body, insane_enabled=False)

    @staticmethod
    def leg(mode, start, end, src, dst, **extra):
        return {'mode': mode, 'transitLeg': mode in ('RAIL', 'BUS'), 'start': {'scheduledTime': f'2026-10-20T{start}:00+02:00'},
                'end': {'scheduledTime': f'2026-10-20T{end}:00+02:00'}, 'from': src, 'to': dst, **extra}

    def dropped_off(self, stop, depart, mode='RAIL'):
        """OTP's drop-off connection: driven to the road beside `stop`, a walk to it and the ride at `depart` (HH:MM)."""
        road = {'name': 'road', 'lat': stop['lat'] - 0.0003, 'lon': stop['lon']}
        h, m = map(int, depart.split(':'))
        drive_start, drive_end = f'{h:02}:{m - 15:02}', f'{h:02}:{m - 3:02}'
        return {'node': {'legs': [
            self.leg('CAR', drive_start, drive_end, {'name': 'Kropa', 'lat': 46.2905, 'lon': 14.2066}, road, duration=720, distance=9000,
                     legGeometry={'points': mapping.encode_polyline([[14.2066, 46.2905], [road['lon'], road['lat']]])}),
            self.leg('WALK', drive_end, f'{h:02}:{m - 1:02}', road, stop, duration=120),
            self.leg(mode, f'{h:02}:{m:02}', '08:00', stop, {'name': 'Ljubljana', 'lat': 46.0581, 'lon': 14.5109}, trip={'gtfsId': f'T{depart}'})]}}

    def run_extras(self, req, edges, budget=4):
        def query(q, v):
            self.asked.append(v)
            return {'planConnection': {'edges': edges(v) if callable(edges) else edges}}
        with mock.patch('prestop_api.parking.near', side_effect=lambda lat, lon, r: [self.LOT] if abs(lat - self.LOT['lat']) < 0.002 else []):
            return journeys.with_extras({'planConnection': {'edges': []}}, req, query, budget=budget)

    def test_otp_drives_to_a_stop_and_the_car_parks_at_its_car_park(self):
        out = self.run_extras(self.request(), [self.dropped_off(self.PODNART, '07:30')])
        legs = out['planConnection']['edges'][0]['node']['legs']
        self.assertEqual([l['mode'] for l in legs], ['CAR', 'WALK', 'RAIL'])
        car, walk = legs[0], legs[1]
        self.assertEqual((car['to']['name'], car['to']['vehicleParking']), ('P Podnart', {'name': 'P Podnart'}))
        self.assertEqual(mapping.decode_polyline(car['legGeometry']['points'])[-1], [14.2585, 46.2948])  # driven on to the car park
        # The walk from the car park (100 m x 1.3 at 1.2 m/s) reaches the stop when OTP's walk did; parked 2 min before.
        self.assertEqual((walk['from']['name'], walk['to']['name'], walk['end']['scheduledTime']), ('P Podnart', 'Podnart', '2026-10-20T07:29:00+02:00'))
        self.assertAlmostEqual(journeys._ts(walk['start']['scheduledTime']) - journeys._ts(car['end']['scheduledTime']), journeys.PARK_SECONDS)
        self.assertGreater(car['duration'], 720)  # the stretch from the road to the car park

    def test_buses_and_trains_and_trains_alone_are_searched_side_by_side(self):
        self.run_extras(self.request(), [])
        self.assertEqual(len(self.asked), 2)
        for v in self.asked:
            self.assertEqual((v['modes']['transit']['access'], v['searchWindow'], v['preferences']['street']['car']), (['WALK', 'CAR_DROP_OFF'], 'PT2H', {'reluctance': 1.0}))
            self.assertEqual(v['dateTime'], {'earliestDeparture': '2026-10-20T07:04:00+02:00'})  # parking and the walk come first
        modes = [{t['mode'] for t in v['modes']['transit']['transit']} for v in self.asked]
        self.assertTrue({'BUS', 'RAIL'} <= modes[0] and 'RAIL' in modes[1])
        self.assertNotIn('filters', self.asked[0]['preferences']['transit'])
        self.assertTrue(self.asked[1]['preferences']['transit']['filters'])  # buses only of the railway (its replacement buses)

    def test_car_and_transit_alone_still_rides_and_one_query_to_spare_asks_once(self):
        journeys.park_and_ride(self.request(modes=['walk', 'car', 'carPark']), lambda kind, v: self.asked.append(v), spare=1)
        self.assertEqual(len(self.asked), 1)
        self.assertTrue({'BUS', 'RAIL'} <= {t['mode'] for t in self.asked[0]['modes']['transit']['transit']})

    def test_arriving_by_a_time_asks_for_it(self):
        self.run_extras(self.request(timeMode='arriveBy', dateTime='2026-10-20T08:10:00+02:00'), [])
        self.assertEqual(self.asked[0]['dateTime'], {'latestArrival': '2026-10-20T08:10:00+02:00'})

    def test_walking_to_the_first_stop_or_no_car_park_there_is_no_park_and_ride(self):
        walked = {'node': {'legs': [self.leg('WALK', '07:00', '07:10', {'name': 'Kropa', 'lat': 46.2905, 'lon': 14.2066}, self.PODNART),
                                    self.leg('RAIL', '07:30', '08:00', self.PODNART, {'name': 'Ljubljana', 'lat': 46.0581, 'lon': 14.5109})]}}
        near = {'name': 'Kropa/Rad.', 'lat': 46.2930, 'lon': 14.2066, 'stop': {'gtfsId': 'IJPP:kropa'}}  # 280 m from the start: walk
        out = self.run_extras(self.request(), [walked, self.dropped_off(self.NAKLO, '07:40', 'BUS'), self.dropped_off(near, '07:20', 'BUS')])
        self.assertEqual(out['planConnection']['edges'], [])  # Naklo: no car park mapped there

    def test_a_short_trip_has_no_park_and_ride(self):
        self.run_extras(self.request(destination={'name': 'Kamna Gorica', 'latitude': 46.3000, 'longitude': 14.2700}), [])  # 5 km
        self.assertEqual(self.asked, [])

    def test_places_take_turns_up_to_park_keep(self):
        naklo_lot = {**self.LOT, 'lat': 46.2741, 'lon': 14.3170, 'name': 'P Naklo'}
        lots = lambda lat, lon, r: [self.LOT] if abs(lat - self.LOT['lat']) < 0.002 else [naklo_lot] if abs(lat - naklo_lot['lat']) < 0.002 else []
        edges = [self.dropped_off(self.PODNART, t) for t in ('07:30', '07:40', '07:50')] + [self.dropped_off(self.NAKLO, t, 'BUS') for t in ('07:35', '07:45')]
        with mock.patch('prestop_api.parking.near', side_effect=lots):
            out = journeys.with_extras({'planConnection': {'edges': []}}, self.request(modes=['walk', 'bus', 'carPark']), lambda q, v: {'planConnection': {'edges': edges}})
        firsts = [e['node']['legs'][2]['trip']['gtfsId'] for e in out['planConnection']['edges']]
        self.assertEqual(firsts, ['T07:30', 'T07:35', 'T07:40', 'T07:45'])  # Podnart, Naklo, Podnart, Naklo; the third Podnart one left out

    def test_driving_all_the_way_from_a_car_free_zone_starts_at_a_car_park(self):
        garage = {'name': 'Garažna hiša Kongresni trg', 'lat': 46.0005, 'lon': 14.5040}
        req = self.request(modes=['walk', 'car'])

        def behave(q, v):
            self.asked.append(v)
            found = v['modes'].get('direct') == ['CAR'] and v['origin']['location']['coordinate']['latitude'] == 46.0005
            legs = [{'mode': 'CAR', 'start': {'scheduledTime': '2026-10-20T07:00:00+02:00'}, 'end': {'scheduledTime': '2026-10-20T07:40:00+02:00'}, 'to': {}}]
            return {'planConnection': {'edges': [{'node': {'legs': legs}}] if found else []}}
        with mock.patch('prestop_api.parking.nearest_drivable', return_value=garage):
            out = journeys.with_extras({'planConnection': {'edges': []}}, req, behave)
        self.assertEqual([v['modes']['direct'] for v in self.asked], [['CAR'], ['CAR']])  # from the garage before OTP's car parks
        legs = out['planConnection']['edges'][0]['node']['legs']
        self.assertEqual([l['mode'] for l in legs], ['WALK', 'CAR'])
        self.assertEqual(legs[0]['start']['scheduledTime'], '2026-10-20T07:00:00+02:00')  # leaves home at the time asked

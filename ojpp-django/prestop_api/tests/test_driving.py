from datetime import datetime, timezone
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import driving, journeys, mapping, pricing
from prestop_api.tests.test_mapping import PLACE

START = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc).timestamp()
FUEL = {'petrol': 1.742, 'diesel': 1.881, 'valid': 'od 13. 10. do 19. 10. 2026'}
at = lambda m: mapping.iso(START + m * 60)


def car_leg(km=20.0, motorway=False, parking=None, minute=0):
    car = {'distanceMeters': round(km * 1000), 'fuelLitres': None, 'fuelCents': None, 'motorway': motorway}
    if parking:
        car['parking'] = {'name': parking, 'feeCents': None, 'parkAndRide': 'P+R' in parking, 'lat': 46.04, 'lon': 14.46}
    return {'id': f'leg:c{minute}', 'mode': 'car', 'tripId': None, 'geometry': [], 'effectiveDeparture': at(minute), 'effectiveArrival': at(minute + 20), 'car': car}


def bus(minute, feed='LPP'):
    return {'id': f'leg:b{minute}', 'mode': 'bus', 'tripId': f'{feed}:t{minute}', 'routeId': f'{feed}:r', 'operatorId': 'LPP:lpp', 'routeName': '6',
            'geometry': [[14.46, 46.04], [14.50, 46.05]], 'effectiveDeparture': at(minute), 'effectiveArrival': at(minute + 15)}


def price(*legs, car=None):
    profile = {'cards': [], 'bikeMemberships': [], 'scooterPasses': [], **({'car': car} if car else {})}
    with mock.patch.object(driving, 'fuel', return_value=FUEL):
        return pricing.price_journey({'legs': list(legs)}, profile, 'en')


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
        self.assertIsNone(lpg['price']['totalCents'])

    def test_ljubljana_park_and_ride_includes_two_bus_rides(self):
        j = price(car_leg(15, parking='P+R Dolgi most'), bus(30), bus(50), bus(200))
        self.assertEqual((j['legs'][0]['car']['parking']['feeCents'], j['legs'][0]['car']['parking']['fee']), (150, 'paid'))
        self.assertEqual([l['price']['amountCents'] for l in j['legs'][1:]], [0, 0, 150])
        self.assertEqual(j['legs'][1]['price']['basis'], 'Included in the P+R parking ticket')

    def test_an_unknown_car_park_makes_the_total_unknown(self):
        j = price(car_leg(15, parking='Parkirišče pri postaji'))
        self.assertIsNone(j['price']['totalCents'])
        self.assertEqual((j['legs'][0]['car']['parking']['feeCents'], j['legs'][0]['car']['parking']['fee']), (None, 'unknown'))


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
        park = searches['carPark']['modes']['transit']
        self.assertEqual((park['access'], park['egress']), (['CAR_PARKING'], ['WALK']))
        self.assertIn({'mode': 'RAIL'}, park['transit'])  # Car + transit alone still rides buses and trains

    def test_a_drive_to_a_car_free_place_parks_and_walks_within_the_query_budget(self):
        asked = []

        def query(q, v):
            asked.append(v['modes'])
            return {'planConnection': {'edges': [] if v['modes'].get('direct') == ['CAR'] else [{'node': {'legs': [
                {'mode': 'CAR', 'trip': None, 'start': {'scheduledTime': '08:00'}}, {'mode': 'WALK', 'trip': None, 'start': {'scheduledTime': '08:20'}}]}}]}}
        journeys._extra_cache.clear()
        req = self.request(modes=['walk', 'car'], dateTime='2026-10-19T07:41:00Z')
        out = journeys.with_extras({'planConnection': {'edges': []}}, req, query, budget=2)
        self.assertEqual([m['direct'] for m in asked], [['CAR'], ['CAR_PARKING']])
        self.assertEqual(len(out['planConnection']['edges']), 1)
        journeys._extra_cache.clear()
        asked.clear()
        journeys.with_extras({'planConnection': {'edges': []}}, req, query, budget=1)  # no query left for the second try
        self.assertEqual(len(asked), 1)

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
    """Drive + park + ride at our own places (journeys.park_and_ride, spec 2026-10-19 A5b)."""
    PODNART = {'kind': 'rail', 'stop': {'name': 'Podnart'}, 'parking': {'name': 'Podnart', 'lat': 46.2939, 'lon': 14.2585, 'osmFee': ''}}
    CITY = {'kind': 'bus', 'stop': {'name': 'Slovenija avto'}, 'parking': {'name': 'Slovenija avto', 'lat': 46.0733, 'lon': 14.4851, 'osmFee': 'no'}}

    def setUp(self):
        journeys._extra_cache.clear()
        journeys._drive_cache.clear()
        self.asked = []

    def request(self, **overrides):
        body = {'origin': {**PLACE, 'name': 'Kropa'}, 'destination': {**PLACE, 'name': 'Ljubljana', 'latitude': 46.05}, 'via': [],
                'dateTime': '2026-10-20T07:00:00+02:00', 'timeMode': 'departAt', 'minTransferSeconds': 180,
                'modes': ['walk', 'bus', 'rail', 'carPark'], 'riskMode': 'normal', **overrides}
        return journeys.parse_request(body, insane_enabled=False)

    def query(self, q, v, drive_found=True, walk_only=False):
        self.asked.append(v)
        if v['modes'].get('direct') == ['CAR']:
            legs = [{'mode': 'CAR', 'duration': 720, 'start': {'scheduledTime': '2026-10-20T07:00:00+02:00'}, 'end': {'scheduledTime': '2026-10-20T07:12:00+02:00'},
                     'to': {'name': 'x', 'lat': v['destination']['location']['coordinate']['latitude'], 'lon': v['destination']['location']['coordinate']['longitude']}}]
            return {'planConnection': {'edges': [{'node': {'legs': legs}}] if drive_found else []}}
        walk = {'mode': 'WALK', 'transitLeg': False, 'start': {'scheduledTime': '2026-10-20T07:20:00+02:00'}, 'end': {'scheduledTime': '2026-10-20T07:23:00+02:00'}}
        rail = {'mode': 'RAIL', 'transitLeg': True, 'trip': {'gtfsId': 'SZ:2409'}, 'start': {'scheduledTime': '2026-10-20T07:23:00+02:00'}, 'end': {'scheduledTime': '2026-10-20T08:00:00+02:00'}}
        return {'planConnection': {'edges': [{'node': {'legs': [walk] if walk_only else [walk, rail]}}]}}

    def run_extras(self, req, places, budget=4, **behaviour):
        with mock.patch('prestop_api.parking.candidates', return_value=places), \
                mock.patch('prestop_api.sources.stops') as stops:
            stops.get.return_value.value = {'list': [], 'routes': {}}
            return journeys.with_extras({'planConnection': {'edges': []}}, req, lambda q, v: self.query(q, v, **behaviour), budget=budget)

    def test_drives_to_the_station_parks_and_rides_on(self):
        out = self.run_extras(self.request(), [self.PODNART])
        legs = out['planConnection']['edges'][0]['node']['legs']
        self.assertEqual([l['mode'] for l in legs], ['CAR', 'WALK', 'RAIL'])
        # Parked two minutes before walking off; the drive keeps its 12 minutes.
        self.assertEqual((legs[0]['start']['scheduledTime'], legs[0]['end']['scheduledTime']), ('2026-10-20T07:06:00+02:00', '2026-10-20T07:18:00+02:00'))
        self.assertEqual((legs[0]['to']['vehicleParking'], legs[0]['to']['lat']), ({'name': 'Podnart'}, 46.2939))
        ride = self.asked[1]
        self.assertEqual(ride['dateTime'], {'earliestDeparture': '2026-10-20T07:14:00+02:00'})  # 07:00 + 12 min drive + 2 min to park
        self.assertEqual(ride['origin']['location']['coordinate'], {'latitude': 46.2939, 'longitude': 14.2585})  # from the car park

    def test_arriving_by_a_time_rides_to_it_and_drives_before(self):
        self.run_extras(self.request(timeMode='arriveBy', dateTime='2026-10-20T08:10:00+02:00'), [self.PODNART])
        self.assertEqual(self.asked[1]['dateTime'], {'latestArrival': '2026-10-20T08:10:00+02:00'})

    def test_two_places_within_the_query_budget_and_drives_cached_for_hours(self):
        out = self.run_extras(self.request(), [self.PODNART, self.CITY], budget=2)
        self.assertEqual((len(self.asked), len(out['planConnection']['edges'])), (2, 1))  # the second place: no query left
        self.asked.clear()
        self.run_extras(self.request(dateTime='2026-10-20T09:00:00+02:00'), [self.PODNART, self.CITY], budget=3)
        # Two hours later: the drive to Podnart is reused, its ride and the second place are asked.
        self.assertEqual([v['modes'].get('direct') for v in self.asked], [['WALK'], ['CAR'], ['WALK']])

    def test_no_place_on_the_way_falls_back_to_otps_car_parks(self):
        self.run_extras(self.request(), [])
        self.assertEqual(self.asked[0]['modes']['transit']['access'], ['CAR_PARKING'])

    def test_walking_on_from_the_car_park_is_not_a_park_and_ride(self):
        out = self.run_extras(self.request(), [self.PODNART], walk_only=True)
        self.assertEqual(out['planConnection']['edges'], [])

    def test_a_start_in_a_car_free_zone_walks_to_the_nearest_car_park_first(self):
        garage = {'name': 'Garažna hiša Kongresni trg', 'lat': 46.0005, 'lon': 14.5040}
        drives = iter([False, True])  # from Prešernov trg: no drive; from the garage: one
        behave = lambda q, v: self.query(q, v, drive_found=next(drives)) if v['modes'].get('direct') == ['CAR'] else self.query(q, v)
        with mock.patch('prestop_api.parking.nearest_drivable', return_value=garage), \
                mock.patch('prestop_api.parking.candidates', return_value=[self.PODNART]), mock.patch('prestop_api.sources.stops') as stops:
            stops.get.return_value.value = {'list': [], 'routes': {}}
            out = journeys.with_extras({'planConnection': {'edges': []}}, self.request(), behave)
        legs = out['planConnection']['edges'][0]['node']['legs']
        self.assertEqual([l['mode'] for l in legs], ['WALK', 'CAR', 'WALK', 'RAIL'])
        self.assertEqual(legs[0]['to']['name'], garage['name'])
        self.assertEqual(legs[0]['end']['scheduledTime'], legs[1]['start']['scheduledTime'])
        self.assertEqual(self.asked[1]['origin']['location']['coordinate'], {'latitude': 46.0005, 'longitude': 14.5040})

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
        self.assertEqual([v['modes']['direct'] for v in self.asked], [['CAR'], ['CAR_PARKING'], ['CAR']])
        legs = out['planConnection']['edges'][0]['node']['legs']
        self.assertEqual([l['mode'] for l in legs], ['WALK', 'CAR'])
        self.assertEqual(legs[0]['start']['scheduledTime'], '2026-10-20T07:00:00+02:00')  # leaves home at the time asked

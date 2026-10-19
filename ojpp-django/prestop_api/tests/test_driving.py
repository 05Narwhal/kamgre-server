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

"""Car parks from OpenStreetMap and what parking costs (parking.py, driving.parking_fee; spec 2026-10-19 A5)."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import parking, pricing
from prestop_api.tests.test_driving import car_leg, price

PRESEREN = (46.0514, 14.5060)  # Ljubljana's centre, where the LPT zones are measured from
KROPA = (46.2914, 14.2055)
KRANJ = (46.2389, 14.3556)


def lot(lat, lon, name='', fee='', pr=False, capacity=0):
    return {'lat': lat, 'lon': lon, 'name': name, 'osmFee': fee, 'parkRide': pr, 'capacity': capacity}


def mapped(*lots):
    grid = {}
    for p in lots:
        grid.setdefault((int(p['lat'] / parking.CELL), int(p['lon'] / parking.CELL)), []).append(p)
    return mock.patch.object(parking, '_all', return_value=(list(lots), grid))


def parked_at(lat, lon, name='Parkirišče'):
    leg = car_leg(15, parking=name)
    leg['car']['parking'].update(lat=lat, lon=lon)
    return leg


class FeeTests(SimpleTestCase):
    rules = pricing.tariffs()['driving']

    def fee(self, osm_fee, at, name=''):
        found = parking.fee(name, osm_fee, *at, self.rules)
        return found['fee'], found['feeCents'], found['basis']

    def test_a_known_park_and_ride_tariff_is_paid(self):
        self.assertEqual(self.fee('', PRESEREN, 'P+R Dolgi most'), ('paid', 150, 'pr'))

    def test_fee_no_is_free_also_in_the_countryside(self):
        self.assertEqual(self.fee('no', KROPA), ('free', 0, 'osm'))
        self.assertEqual(self.fee('no', PRESEREN), ('free', 0, 'osm'))

    def test_fee_yes_in_ljubljana_costs_an_hour_of_its_lpt_zone(self):
        self.assertEqual(self.fee('yes', PRESEREN), ('paid', 170, 'hourly'))
        self.assertEqual(self.fee('yes', (PRESEREN[0] + 0.0135, PRESEREN[1])), ('paid', 100, 'hourly'))  # 1.5 km north
        self.assertEqual(self.fee('yes', (PRESEREN[0] + 0.027, PRESEREN[1])), ('paid', 70, 'hourly'))   # 3 km
        self.assertEqual(self.fee('yes', (PRESEREN[0] + 0.045, PRESEREN[1])), ('unknown', None, None))  # 5 km: no zone

    def test_otherwise_unknown_never_free(self):
        self.assertEqual(self.fee('yes', KRANJ), ('unknown', None, None))  # paid, no tariff known
        self.assertEqual(self.fee('', PRESEREN), ('unknown', None, None))  # OSM says nothing


class LookupTests(SimpleTestCase):
    def test_near_puts_park_and_ride_first_then_free_then_the_biggest(self):
        lots = [lot(46.1, 14.5, 'big paid', 'yes', capacity=300), lot(46.1001, 14.5, 'free', 'no', capacity=20),
                lot(46.1002, 14.5, 'P+R', 'yes', pr=True), lot(46.1003, 14.5, 'small paid', 'yes', capacity=5), lot(46.12, 14.5, 'far')]
        with mapped(*lots):
            self.assertEqual([p['name'] for p in parking.near(46.1, 14.5, 300)], ['P+R', 'free', 'big paid', 'small paid'])

    def test_a_car_parks_at_the_nearest_mapped_car_park(self):
        with mapped(lot(46.1, 14.5, 'a'), lot(46.1003, 14.5, 'b')):
            self.assertEqual(parking.at(46.10028, 14.5)['name'], 'b')
            self.assertIsNone(parking.at(46.102, 14.5))  # 220 m away: not there

    def test_the_data_file_holds_slovenias_car_parks(self):
        rows, _ = parking._all()
        self.assertGreater(len(rows), 5000)
        self.assertEqual({p['osmFee'] for p in rows}, {'yes', 'no', ''})
        self.assertTrue(any(p['parkRide'] for p in rows))


class CarLegTests(SimpleTestCase):
    def test_a_free_mapped_car_park_costs_nothing_and_keeps_the_total(self):
        with mapped(lot(46.3, 14.2, fee='no')):
            j = price(parked_at(46.3, 14.2))
        park = j['legs'][0]['car']['parking']
        self.assertEqual((park['fee'], park['feeCents']), ('free', 0))
        self.assertIsNotNone(j['legs'][0]['price']['amountCents'])
        self.assertIn('parking Parkirišče (free)', j['legs'][0]['price']['basis'])

    def test_a_paid_car_park_in_ljubljanas_centre_counts_an_hour(self):
        with mapped(lot(*PRESEREN, fee='yes')):
            j = price(parked_at(*PRESEREN))
        park = j['legs'][0]['car']['parking']
        self.assertEqual((park['fee'], park['feeCents']), ('paid', 170))
        self.assertIn('parking Parkirišče, first hour', j['legs'][0]['price']['basis'])

    def test_an_unmapped_or_untariffed_car_park_is_unknown(self):
        for lots in ([], [lot(*KRANJ, fee='yes')]):
            with mapped(*lots):
                j = price(parked_at(*KRANJ))
            self.assertEqual((j['legs'][0]['car']['parking']['fee'], j['legs'][0]['price']['amountCents']), ('unknown', None))

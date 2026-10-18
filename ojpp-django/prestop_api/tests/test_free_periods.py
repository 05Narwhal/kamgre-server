from contextlib import contextmanager
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import sharing

START = '2026-10-19T10:00:00+02:00'


def at(minutes: float) -> str:
    from prestop_api import mapping
    return mapping.iso(sharing._ts(START) + minutes * 60)


def ride(minutes: float, network='jcdecaux_ljubljana') -> dict:
    """A BicikeLJ ride east along a straight street (about 11.6 km)."""
    return {'id': 'leg:x-1', 'mode': 'bike', 'tripId': None, 'geometry': [[14.45, 46.05], [14.60, 46.05]],
            'origin': {'name': 'Vič', 'latitude': 46.05, 'longitude': 14.45}, 'destination': {'name': 'Fužine', 'latitude': 46.05, 'longitude': 14.60},
            'scheduledDeparture': START, 'effectiveDeparture': START, 'scheduledArrival': at(minutes), 'effectiveArrival': at(minutes),
            'rental': {'network': network, 'operator': 'BicikeLJ', 'formFactor': 'bicycle', 'fromStationId': f'{network}:1', 'toStationId': f'{network}:2'}}


def journey(*legs) -> dict:
    return {'legs': list(legs), 'scheduledDeparture': legs[0]['scheduledDeparture'], 'effectiveDeparture': legs[0]['effectiveDeparture'],
            'scheduledArrival': legs[-1]['scheduledArrival'], 'effectiveArrival': legs[-1]['effectiveArrival']}


def station(lon=14.5433, lat=46.0520, bikes=5, docks=5, sid='jcdecaux_ljubljana:7', name='Tivoli'):
    return {'id': sid, 'name': name, 'latitude': lat, 'longitude': lon, 'availableCount': bikes, 'docksAvailable': docks, 'canPickup': bikes > 0, 'canReturn': docks > 0}


@contextmanager
def no_wait():
    """BicikeLJ as if a new bike could be taken at once (the real network makes riders wait 5 minutes)."""
    real = sharing.rules()
    with mock.patch.object(sharing, 'rules', return_value={**real, 'jcdecaux_ljubljana': {**real['jcdecaux_ljubljana'], 'waitSeconds': 0}}):
        yield


class RideCentsTests(SimpleTestCase):
    """Worked examples from the operators' price lists (data/tariffs.json)."""

    def cents(self, network, minutes):
        return sharing.ride_cents(sharing.rules()[network], minutes * 60)

    def test_bicikelj_first_hour_free_then_1_2_and_4_euros_an_hour(self):
        self.assertEqual([self.cents('jcdecaux_ljubljana', m) for m in (60, 61, 120, 150, 200, 241)], [0, 100, 100, 300, 700, 1100])
        self.assertIsNone(self.cents('jcdecaux_ljubljana', 25 * 60))  # longer than the 24-hour limit

    def test_kolesce_half_hour_free_then_50_cents_a_started_half_hour_capped_at_20_euros(self):
        self.assertEqual([self.cents('nextbike_cn', m) for m in (30, 31, 60, 61, 24 * 60)], [0, 50, 50, 100, 2000])

    def test_gorenjska_bike_free_up_to_its_two_hour_limit(self):
        self.assertEqual(self.cents('scbikes_gbike', 100), 0)
        self.assertIsNone(self.cents('scbikes_gbike', 130))

    def test_unknown_charges_are_no_price_never_zero(self):
        self.assertEqual(self.cents('jcdecaux_maribor', 50), 0)
        self.assertIsNone(self.cents('jcdecaux_maribor', 70))  # charges after the free hour are not published
        self.assertIsNone(self.cents('bolt_359', 10))  # unlock fee not published


class FreePeriodTests(SimpleTestCase):
    def test_a_ride_within_the_free_hour_only_says_when_it_ends(self):
        j = sharing.free_periods(journey(ride(45)), [station()])
        self.assertEqual(len(j['legs']), 1)
        self.assertEqual(j['legs'][0]['rental']['freeUntil'], at(60))
        self.assertNotIn('swapAt', j['legs'][0]['rental'])

    def test_a_90_minute_bicikelj_ride_says_when_the_free_hour_ends_but_the_5_minute_wait_rules_out_a_swap(self):
        j = sharing.free_periods(journey(ride(90)), [station()])
        self.assertEqual(len(j['legs']), 1)
        self.assertEqual(j['legs'][0]['rental']['freeUntil'], at(60))
        self.assertNotIn('swapAt', j['legs'][0]['rental'])
        self.assertEqual(j['effectiveArrival'], at(90))

    def test_without_a_wait_a_90_minute_ride_swaps_bikes_before_the_hour_and_stays_free(self):
        with no_wait():
            j = sharing.free_periods(journey(ride(90)), [station(), station(lon=14.47, sid='jcdecaux_ljubljana:8', name='Far')])
        first, second = j['legs']
        swap = first['rental']['swapAt']
        self.assertEqual((swap['stationId'], swap['name']), ('jcdecaux_ljubljana:7', 'Tivoli'))
        self.assertLess(sharing._ts(swap['at']), sharing._ts(first['rental']['freeUntil']))
        self.assertEqual((first['rental']['toStationId'], second['rental']['fromStationId']), ('jcdecaux_ljubljana:7', 'jcdecaux_ljubljana:7'))
        self.assertEqual((first['destination']['name'], second['origin']['name']), ('Tivoli', 'Tivoli'))
        # The second bike's free hour starts when it is taken, and the ride ends within its free hour.
        self.assertEqual(second['rental']['freeUntil'], sharing.mapping.iso(sharing._ts(second['effectiveDeparture']) + 3600))
        self.assertLess(sharing._ts(second['effectiveArrival']), sharing._ts(second['rental']['freeUntil']))
        added = sharing._ts(j['effectiveArrival']) - sharing._ts(at(90))
        self.assertTrue(0 < added <= sharing.SWAP_MAX_ADDED, added)
        self.assertEqual(sharing.ride_cents(sharing.rules()['jcdecaux_ljubljana'], 56 * 60), 0)
        self.assertGreater(sharing.ride_cents(sharing.rules()['jcdecaux_ljubljana'], 90 * 60), 0)

    def test_no_swap_at_a_full_or_empty_station_or_one_too_far_from_the_ride(self):
        self.enterContext(no_wait())
        for s in (station(docks=0), station(bikes=0), station(lat=46.06)):
            with self.subTest(station=s):
                j = sharing.free_periods(journey(ride(90)), [s])
                self.assertEqual(len(j['legs']), 1)
                self.assertNotIn('swapAt', j['legs'][0]['rental'])

    def test_no_swap_when_it_would_miss_the_next_train(self):
        self.enterContext(no_wait())
        train = {'id': 'leg:x-2', 'mode': 'rail', 'tripId': 'SZ:1', 'geometry': [], 'scheduledDeparture': at(91), 'effectiveDeparture': at(91),
                 'scheduledArrival': at(120), 'effectiveArrival': at(120)}
        j = sharing.free_periods(journey(ride(90), train), [station()])
        self.assertEqual(len(j['legs']), 2)
        self.assertEqual(j['effectiveArrival'], at(120))

    def test_a_walk_after_the_ride_moves_with_the_swap(self):
        self.enterContext(no_wait())
        walk = {'id': 'leg:x-2', 'mode': 'walk', 'tripId': None, 'geometry': [], 'scheduledDeparture': at(90), 'effectiveDeparture': at(90),
                'scheduledArrival': at(95), 'effectiveArrival': at(95)}
        j = sharing.free_periods(journey(ride(90), walk), [station()])
        self.assertEqual(len(j['legs']), 3)
        self.assertEqual(j['effectiveArrival'], j['legs'][-1]['effectiveArrival'])
        self.assertGreater(sharing._ts(j['effectiveArrival']), sharing._ts(at(95)))

    def test_networks_without_a_free_period_are_left_alone(self):
        scooter = ride(30, network='bolt_359')
        j = sharing.free_periods(journey(scooter), [])
        self.assertNotIn('freeUntil', j['legs'][0]['rental'])

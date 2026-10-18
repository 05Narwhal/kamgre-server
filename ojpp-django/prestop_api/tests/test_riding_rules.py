import os
import unittest
from unittest import mock

from django.test import SimpleTestCase

STEPS_Q = '''query($o: PlanLabeledLocationInput!, $d: PlanLabeledLocationInput!, $modes: PlanModesInput) {
  planConnection(origin: $o, destination: $d, modes: $modes, first: 1) { edges { node { legs { steps { streetName distance } } } } } }'''


def _streets(mode: str, origin: tuple, destination: tuple) -> set[str]:
    from prestop_api.upstream import otp
    loc = lambda p: {'location': {'coordinate': {'latitude': p[0], 'longitude': p[1]}}}
    data = otp().query(STEPS_Q, {'o': loc(origin), 'd': loc(destination), 'modes': {'direct': [mode]}})
    return {s['streetName'] for e in data['planConnection']['edges'] for l in e['node']['legs'] for s in l['steps']}


@unittest.skipUnless(os.environ.get('PRESTOP_LIVE_OTP'), 'asks the public OTP; set PRESTOP_LIVE_OTP=1')
class LiveBikeRulesTests(SimpleTestCase):
    """OTP's OSM rules keep bikes off motorways and expressways (bicycle=no): checked on the live planner."""

    def test_koper_to_izola_by_bike_avoids_the_expressway_tunnel_cars_take(self):
        koper, izola = (45.5480, 13.7300), (45.5370, 13.6600)
        self.assertIn('Predor Markovec / Galleria monte S. Marco', _streets('CAR', koper, izola))  # the H6 expressway
        self.assertNotIn('Predor Markovec / Galleria monte S. Marco', _streets('BICYCLE', koper, izola))


class ScooterRulesTests(SimpleTestCase):
    """E-scooters ride on cycle lanes and paths, else only on roads up to 50 km/h (ZPrCP 97.a; data/no_scooter.json)."""

    def ride(self, minutes=10.0):
        from prestop_api import mapping, sharing
        start = sharing._ts('2026-10-19T10:00:00+02:00')
        at = lambda m: mapping.iso(start + m * 60)
        return {'id': 'leg:s-1', 'mode': 'scooter', 'tripId': None, 'geometry': [[14.500, 46.050], [14.520, 46.050]],  # about 1.5 km east
                'origin': {'name': 'A', 'latitude': 46.05, 'longitude': 14.50}, 'destination': {'name': 'B', 'latitude': 46.05, 'longitude': 14.52},
                'scheduledDeparture': at(0), 'effectiveDeparture': at(0), 'scheduledArrival': at(minutes), 'effectiveArrival': at(minutes),
                'rental': {'network': 'bolt_359', 'operator': 'Bolt', 'formFactor': 'scooter'}}, at

    def journey(self, *legs):
        return {'legs': list(legs), 'scheduledArrival': legs[-1]['scheduledArrival'], 'effectiveArrival': legs[-1]['effectiveArrival']}

    def test_the_motorway_ring_is_closed_and_the_old_town_is_not(self):
        from prestop_api import sharing
        self.assertTrue(sharing.closed_at(14.4429, 46.0342))   # A1/A2 ring at Kozarje
        self.assertFalse(sharing.closed_at(14.5064, 46.0513))  # Prešernov trg

    def test_a_closed_stretch_is_walked_beside_the_scooter(self):
        from prestop_api import sharing
        leg, at = self.ride()
        # A closed road from 14.508 to 14.512 (about 300 m) in the middle of the ride.
        with mock.patch.object(sharing, 'closed_at', side_effect=lambda lon, lat: 14.508 <= lon <= 14.512):
            j = sharing.scooter_rules(self.journey(leg))
        self.assertEqual([l['mode'] for l in j['legs']], ['scooter', 'walk', 'scooter'])
        self.assertNotIn('rental', j['legs'][1])
        self.assertEqual(j['legs'][2]['rental']['network'], 'bolt_359')
        self.assertEqual(j['legs'][0]['destination'], j['legs'][1]['origin'])
        walked = sharing._ts(j['legs'][1]['effectiveArrival']) - sharing._ts(j['legs'][1]['effectiveDeparture'])
        self.assertAlmostEqual(walked, 300 / sharing.PUSH_SPEED, delta=40)
        self.assertGreater(sharing._ts(j['effectiveArrival']), sharing._ts(at(10)))

    def test_a_ride_on_open_streets_is_unchanged_and_one_that_would_miss_its_train_is_dropped(self):
        from prestop_api import sharing
        leg, at = self.ride()
        with mock.patch.object(sharing, 'closed_at', return_value=False):
            self.assertEqual(len(sharing.scooter_rules(self.journey(leg))['legs']), 1)
        train = {'id': 'leg:s-2', 'mode': 'rail', 'tripId': 'SZ:1', 'geometry': [], 'scheduledDeparture': at(11), 'effectiveDeparture': at(11),
                 'scheduledArrival': at(40), 'effectiveArrival': at(40)}
        with mock.patch.object(sharing, 'closed_at', side_effect=lambda lon, lat: 14.508 <= lon <= 14.512):
            self.assertIsNone(sharing.scooter_rules(self.journey(self.ride()[0], train)))

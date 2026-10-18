from django.test import SimpleTestCase

from prestop_api import journeys, sharing
from prestop_api.tests.test_mapping import PLACE, leg


def bike_leg():
    raw = leg('BICYCLE', '10:05:00', '10:35:00', transit=False, duration=1800)
    raw['rentedBike'] = True
    raw['from']['vehicleRentalStation'] = {'stationId': 'jcdecaux_ljubljana:12', 'rentalNetwork': {'networkId': 'jcdecaux_ljubljana'}}
    raw['to']['vehicleRentalStation'] = {'stationId': 'jcdecaux_ljubljana:40', 'rentalNetwork': {'networkId': 'jcdecaux_ljubljana'}}
    return raw


class LegRentalTests(SimpleTestCase):
    def test_a_station_bike_names_its_system_and_both_stations(self):
        self.assertEqual(sharing.leg_rental(bike_leg()), {'network': 'jcdecaux_ljubljana', 'operator': 'BicikeLJ', 'formFactor': 'bicycle',
                                                         'fromStationId': 'jcdecaux_ljubljana:12', 'toStationId': 'jcdecaux_ljubljana:40'})

    def test_a_free_floating_scooter_has_no_stations(self):
        raw = leg('SCOOTER', '10:00:00', '10:10:00', transit=False)
        raw['rentedBike'] = True
        raw['from']['rentalVehicle'] = {'vehicleId': 'kvik:396', 'vehicleType': {'formFactor': 'SCOOTER_STANDING'}, 'rentalNetwork': {'networkId': 'kvik'}}
        self.assertEqual(sharing.leg_rental(raw), {'network': 'kvik', 'operator': 'Kvik', 'formFactor': 'scooter'})

    def test_walking_and_own_bikes_are_not_rentals(self):
        self.assertIsNone(sharing.leg_rental(leg('WALK', '10:00:00', '10:05:00', transit=False)))
        own = bike_leg()
        own['rentedBike'] = False
        self.assertIsNone(sharing.leg_rental(own))

    def test_smart_city_networks_are_named_by_town(self):
        self.assertEqual(sharing.leg_rental({**bike_leg(), 'from': {'vehicleRentalStation': {'stationId': 'scbikes_gbike:1', 'rentalNetwork': {'networkId': 'scbikes_gbike'}}}})['operator'], 'Gorenjska.bike (Kranj)')

    def test_planned_rental_leg_carries_it(self):
        body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Fužine'}, 'via': [], 'dateTime': '2026-10-09T10:00:00Z', 'timeMode': 'departAt',
                'minTransferSeconds': 180, 'modes': ['walk', 'bus', 'bike'], 'searchScope': 'all', 'riskMode': 'normal'}
        data = {'planConnection': {'edges': [{'node': {'walkTime': 300, 'legs': [leg('WALK', '10:00:00', '10:05:00', transit=False, duration=300), bike_leg()]}}]}}
        [j] = journeys.build_journeys(data, journeys.parse_request(body, insane_enabled=False), [])
        self.assertEqual([l['mode'] for l in j['legs']], ['walk', 'bike'])
        self.assertNotIn('rental', j['legs'][0])
        self.assertEqual(j['legs'][1]['rental']['operator'], 'BicikeLJ')

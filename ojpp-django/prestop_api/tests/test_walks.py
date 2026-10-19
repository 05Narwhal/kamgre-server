"""Walks that follow the streets and last as long as the walking (spec 2026-10-19 A2).

The paths are OTP's walk legs as the local API planned them on 2026-10-19 for 20 October: Kropa -> Ljubljana
(bus to Podnart, walk to SŽ's replacement bus), Lesce-Bled <-> Ljubljana Zalog, Ljubljana's station to the city bus.
"""
from datetime import datetime, timedelta
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import geometry, journeys

DAY = '2026-10-20'
PODNART_BUS_STOP = {'name': 'Podnart', 'latitude': 46.2927822, 'longitude': 14.2588882, 'kind': 'station', 'stopId': 'IJPP:1128543'}
PODNART_STATION = {'name': 'Podnart', 'latitude': 46.29389, 'longitude': 14.25847, 'kind': 'station', 'stopId': 'IJPP:1122812'}
PODNART_REPLACEMENT = {'lat': 46.293361, 'lon': 14.258421, 'replacementLabel': 'Zunanja stran železniške postaje'}
# OTP: from the bus stop on the road up to the station (the replacement stop is beside this path, ~15 m off).
PODNART_PATH = [[14.25888, 46.29278], [14.25895, 46.29281], [14.25893, 46.29283], [14.2585, 46.29322], [14.25826, 46.29362],
                [14.25798, 46.29397], [14.25817, 46.29404], [14.25822, 46.29399], [14.25825, 46.294], [14.25831, 46.29402],
                [14.25832, 46.29402], [14.25834, 46.29403], [14.25842, 46.29393], [14.25846, 46.29389], [14.25847, 46.29389]]
LESCE_STATION = {'name': 'Lesce-Bled', 'latitude': 46.3603241, 'longitude': 14.1578647, 'kind': 'station', 'stopId': 'IJPP:1122816'}
LESCE_ZP = {'name': 'Lesce ŽP', 'latitude': 46.3607483, 'longitude': 14.157908, 'kind': 'station', 'stopId': 'IJPP:1126806'}
# OTP: the station's link runs 100 m down the road and back to the stop in front of the station (47 m away).
LESCE_PATH = [[14.15786, 46.36032], [14.15787, 46.36032], [14.15845, 46.3594], [14.15847, 46.35941], [14.15838, 46.3596],
              [14.15823, 46.35989], [14.15803, 46.3602], [14.15805, 46.36021], [14.15807, 46.36022], [14.1581, 46.36023],
              [14.15827, 46.3603], [14.15832, 46.36032], [14.1583, 46.36034], [14.15816, 46.36053], [14.15814, 46.36056],
              [14.15807, 46.36064], [14.15803, 46.36071], [14.15797, 46.36077], [14.1579, 46.36074]]
LJUBLJANA = {'name': 'Ljubljana', 'latitude': 46.0585089, 'longitude': 14.5129236, 'kind': 'station', 'stopId': 'IJPP:1122804'}
KOLODVOR = {'name': 'Kolodvor', 'latitude': 46.0575531, 'longitude': 14.5112809, 'kind': 'station', 'stopId': 'IJPP:1167300'}
KOLODVOR_PATH = [[14.51292, 46.0585], [14.51294, 46.05826], [14.51209, 46.05823], [14.51209, 46.05812], [14.51235, 46.05788],
                 [14.51128, 46.05755]]


def at(hhmm: str) -> str:
    return f'{DAY}T{hhmm}:00+02:00'


def shift(stamp: str, seconds: float) -> str:
    return (datetime.fromisoformat(stamp) + timedelta(seconds=seconds)).isoformat()


def ride(frm: dict, to: dict, dep: str, arr: str, name='A6405', replacement=False, **extra) -> tuple[dict, dict]:
    leg = {'id': f'leg:x-{name}', 'mode': 'bus' if replacement or name.startswith('A') else 'rail', 'operatorId': 'IJPP:1', 'routeId': 'IJPP:r',
           'tripId': f'IJPP:{name}', 'routeName': name, 'headsign': None, 'origin': frm, 'destination': to,
           'scheduledDeparture': at(dep), 'scheduledArrival': at(arr), 'effectiveDeparture': at(dep), 'effectiveArrival': at(arr),
           'geometry': [[frm['longitude'], frm['latitude']], [to['longitude'], to['latitude']]], 'delaySeconds': None,
           'delayProvenance': None, 'canceled': False, 'alertIds': [], **({'replacement': True} if replacement else {}), **extra}
    return leg, {'transit': True, 'interline': False, 'duration': 0, 'realtime': False, 'platform': None}


def walk(frm: dict, to: dict, start: str, path: list, seconds: float) -> tuple[dict, dict]:
    leg = {'id': 'leg:x-w', 'mode': 'walk', 'operatorId': None, 'routeId': None, 'tripId': None, 'routeName': '', 'headsign': None,
           'origin': frm, 'destination': to, 'scheduledDeparture': start, 'scheduledArrival': shift(start, seconds),
           'effectiveDeparture': start, 'effectiveArrival': shift(start, seconds), 'geometry': path, 'delaySeconds': None,
           'delayProvenance': None, 'canceled': False, 'alertIds': []}
    return leg, {'transit': False, 'interline': False, 'duration': seconds, 'realtime': False, 'platform': None}


def plan(*pairs) -> tuple[list[dict], list[dict]]:
    with mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]):  # only the stops the legs know
        legs, meta = journeys.replacement_walks([p[0] for p in pairs], [p[1] for p in pairs])
    journeys.sane_walks(legs, meta)
    return legs, meta


def straight(leg: dict) -> float:
    return geometry.distance([leg['origin']['longitude'], leg['origin']['latitude']], [leg['destination']['longitude'], leg['destination']['latitude']])


def path(leg: dict) -> float:
    return geometry.cumulative(leg['geometry'])[-1]


def minutes(leg: dict) -> float:
    return (datetime.fromisoformat(leg['effectiveArrival']) - datetime.fromisoformat(leg['effectiveDeparture'])).total_seconds() / 60


class PodnartTests(SimpleTestCase):
    """Kropa -> Ljubljana: bus A6405 reaches Podnart at 05:44, SŽ's replacement bus 2403 leaves beside the station at 06:02."""

    def legs(self):
        return plan(ride({'name': 'Kropa/Rad.', 'latitude': 46.2907, 'longitude': 14.2048, 'kind': 'station'}, PODNART_BUS_STOP, '05:35', '05:44'),
                    walk(PODNART_BUS_STOP, PODNART_STATION, at('05:44'), PODNART_PATH, 210),
                    ride(PODNART_STATION, LJUBLJANA, '06:02', '07:18', name='BUS 2403', replacement=True, _boardAt=PODNART_REPLACEMENT))

    def test_the_walk_goes_straight_to_the_replacement_stop_not_through_the_station(self):
        legs, _ = self.legs()
        self.assertEqual([l['mode'] for l in legs], ['bus', 'walk', 'bus'])
        w = legs[1]
        self.assertEqual(w['destination']['name'], 'Podnart · Zunanja stran železniške postaje')
        self.assertEqual(w['geometry'][-1], [PODNART_REPLACEMENT['lon'], PODNART_REPLACEMENT['lat']])
        self.assertLessEqual(path(w), 3 * straight(w), (path(w), straight(w)))  # before: 268 m for 74 m

    def test_the_walk_lasts_as_long_as_the_walking_and_the_wait_comes_after_it(self):
        legs, meta = self.legs()
        w = legs[1]
        self.assertEqual(w['effectiveDeparture'], at('05:44'))  # when the bus from Kropa arrives
        self.assertLess(minutes(w), 3)  # before: 18 min, the whole wait for the 06:02 bus
        self.assertAlmostEqual(meta[1]['duration'], minutes(w) * 60, delta=1)
        self.assertEqual(legs[2]['effectiveDeparture'], at('06:02'))


class LesceTests(SimpleTestCase):
    def test_otps_detour_round_the_station_link_is_snapped_to_the_stop_in_front(self):
        legs, meta = plan(ride(LJUBLJANA, LESCE_STATION, '06:20', '07:05', name='LPV 2402'),
                          walk(LESCE_STATION, LESCE_ZP, at('07:05'), LESCE_PATH, 240),
                          ride(LESCE_ZP, {'name': 'Bled', 'latitude': 46.367, 'longitude': 14.11, 'kind': 'station'}, '07:39', '07:50'))
        w = legs[1]
        self.assertGreater(path({**w, 'geometry': LESCE_PATH}), 6 * straight(w))  # OTP: 298 m for 47 m
        self.assertEqual(len(w['geometry']), 2)
        self.assertEqual((w['effectiveDeparture'], round(meta[1]['duration'])), (at('07:05'), 55))
        self.assertLess(minutes(w), 1)

    def test_a_walk_from_the_replacement_stop_on_to_a_stop_beside_it_is_not_sent_round_the_station(self):
        replacement_stop = {'lat': 46.360748, 'lon': 14.157908, 'replacementLabel': 'Avtobusno postajališče Lesce ŽP, zunanja stran železniške postaje'}
        legs, _ = plan(ride(LJUBLJANA, LESCE_STATION, '06:03', '07:36', name='BUS 2402', replacement=True, _alightAt=replacement_stop),
                       walk(LESCE_STATION, LESCE_ZP, at('07:36'), LESCE_PATH, 240),
                       ride(LESCE_ZP, {'name': 'Bled', 'latitude': 46.367, 'longitude': 14.11, 'kind': 'station'}, '07:50', '08:00'))
        self.assertEqual([l['mode'] for l in legs], ['bus', 'walk', 'bus'])
        self.assertLess(path(legs[1]), 20)  # the stop the bus leaves you at is the one the next bus leaves from
        self.assertLess(minutes(legs[1]), 1)


class CityTransferTests(SimpleTestCase):
    def test_a_normal_walk_keeps_otps_path(self):
        legs, meta = plan(ride(LESCE_STATION, LJUBLJANA, '07:06', '07:49', name='EN 415'),
                          walk(LJUBLJANA, KOLODVOR, at('07:49'), KOLODVOR_PATH, 240),
                          ride(KOLODVOR, {'name': 'Polje', 'latitude': 46.0538, 'longitude': 14.5827, 'kind': 'station'}, '07:58', '08:15', name='A25'))
        self.assertEqual((legs[1]['geometry'], meta[1]['duration'], legs[1]['effectiveArrival']), (KOLODVOR_PATH, 240, at('07:53')))

    def test_a_long_detour_between_far_points_is_left_to_otp(self):
        far = {'name': 'Ljubljana Zalog', 'latitude': 46.0594091, 'longitude': 14.6153758, 'kind': 'station'}
        near = {'name': 'Center Zalog', 'latitude': 46.061085, 'longitude': 14.613663, 'kind': 'station'}
        loop = [[near['longitude'], near['latitude']], [14.6139, 46.0606], [14.6160, 46.0605], [far['longitude'], far['latitude']]]
        legs, _ = plan(ride({'name': 'Polje', 'latitude': 46.0538, 'longitude': 14.5827, 'kind': 'station'}, near, '08:20', '08:25', name='A11'),
                       walk(near, far, at('08:25'), loop, 360))
        self.assertEqual(legs[1]['geometry'], loop)

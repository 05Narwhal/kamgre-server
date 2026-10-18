"""A replacement bus has no railway track (B7).

A journey's bus piece is cut from the train's leg, which carries the track predicted from the train number
(tracks.py: "13-A", usual). The piece used to keep it, so "BUS 2402" said "Usually platform 13-A" in the planner. It
keeps only a bus-station bay, when its stop has one.
"""
from django.test import SimpleTestCase

from prestop_api import journey_legs

LIKE = '2026-10-19T06:00:00+02:00'
T0 = 1_792_380_000.0  # 2026-10-19 06:00 +02:00


def stop(name: str, i: int, **extra) -> dict:
    return {'name': name, 'gtfsId': f'IJPP:{i}', 'lat': 46.05 + i / 10, 'lon': 14.5 - i / 10, **extra}


def train_leg(**extra) -> dict:
    return {'id': 'leg1', 'mode': 'rail', 'routeName': 'LPV 2402', 'scheduledDeparture': LIKE, 'geometry': [],
            'platform': '13-A', 'platformUsual': True, **extra}


def train(*stops: dict) -> dict:
    return {'stops': list(stops), 'departures': [T0 + 600 * i for i in range(len(stops))], 'arrivals': [T0 + 600 * i for i in range(len(stops))],
            'delays': [None] * len(stops)}


def bus(*stops: dict) -> dict:
    times = [T0 + 600 * i for i in range(len(stops))]
    return {'id': 'sub-1', 'synthetic': True, 'route': {'gtfsId': 'IJPP:sub-r', 'shortName': 'BUS 2402'}, 'headsign': stops[-1]['name'],
            'stops': list(stops), 'departures': times, 'arrivals': times, 'scheduledDepartures': times, 'scheduledArrivals': times, 'trainName': 'LPV 2402'}


def no_road(_part):
    return None


class ReplacementBusPlatformTests(SimpleTestCase):
    def test_a_bus_cut_from_a_train_leg_has_no_track(self):
        a, b = stop('Ljubljana', 1), stop('Kranj', 2)
        piece = journey_legs._bus_piece(train_leg(), bus(a, b), train(a, b), 0, 1, no_road, 'bus')
        self.assertEqual(piece['mode'], 'bus')
        self.assertNotIn('platform', piece)
        self.assertNotIn('platformUsual', piece)

    def test_it_keeps_the_bay_it_leaves_from(self):
        a, b = stop('Ljubljana', 1, bay='37', bayUsual=False), stop('Kranj', 2)
        piece = journey_legs._bus_piece(train_leg(), bus(a, b), train(a, b), 0, 1, no_road, 'bus')
        self.assertEqual(piece['platform'], '37')
        self.assertNotIn('platformUsual', piece)

    def test_a_bay_that_is_only_the_usual_one_says_so(self):
        a, b = stop('Ljubljana', 1, bay='38', bayUsual=True), stop('Kranj', 2)
        piece = journey_legs._bus_piece(train_leg(), bus(a, b), train(a, b), 0, 1, no_road, 'bus')
        self.assertEqual((piece['platform'], piece['platformUsual']), ('38', True))

    def test_a_timetable_bus_ride_has_no_track_either(self):
        a, b = stop('Ljubljana', 1), stop('Kranj', 2)
        piece = journey_legs._bus_ride(train_leg(), bus(a, b), 0, 1, no_road, 'bus')
        self.assertNotIn('platform', piece)
        self.assertNotIn('platformUsual', piece)
        piece = journey_legs._bus_ride(train_leg(), bus({**a, 'bay': '39', 'bayUsual': False}, b), 0, 1, no_road, 'bus')
        self.assertEqual(piece['platform'], '39')

    def test_the_train_piece_keeps_its_track(self):
        a, b = stop('Ljubljana', 1), stop('Kranj', 2)
        leg = train_leg(origin={'stopId': a['gtfsId'], 'name': 'Ljubljana'}, destination={'stopId': b['gtfsId'], 'name': 'Kranj'},
                        scheduledArrival=LIKE, effectiveDeparture=LIKE, effectiveArrival=LIKE)
        piece = journey_legs._train_piece(leg, train(a, b), 0, 1, 'train')
        self.assertEqual((piece['mode'], piece['platform'], piece['platformUsual']), ('rail', '13-A', True))

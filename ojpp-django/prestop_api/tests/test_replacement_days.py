"""Replacement buses on boards, lines and journeys, each by its own service day (scheduled.day_plan)."""
from datetime import date, datetime
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import closures, journey_legs, journeys, mapping, replacement, scheduled
from prestop_api.tests.test_closures import DAY, JESENICE, T0, notice, station, train


def plan_of(trips, buses):
    """A day plan as scheduled.day_plan builds it."""
    real = replacement.sections(trips)
    sections = {k: list(v) for k, v in real.items()}
    for k, v in closures.sections(buses).items():
        sections.setdefault(k, []).extend(v)
    by_trip = {}
    for t in trips:
        by_trip.setdefault(t['id'], []).append(t)
    return {'sections': sections, 'synthetic': buses, 'by_id': {b['id']: b for b in buses}, 'trips': by_trip}


def synthesize(trips, alerts):
    with mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]):
        return closures.synthesize(trips, {}, alerts, [], {}, [])


def row(t, i, kind='departure'):
    stop = t['stops'][i]
    at = t['departures'][i] if kind == 'departure' else t['arrivals'][i]
    return {'id': f'{t["id"]}@{DAY}/{i}', 'stopId': stop['gtfsId'], 'tripId': t['id'], 'routeId': t['route']['gtfsId'],
            'operatorId': 'IJPP:1161', 'routeName': t['route']['shortName'], 'mode': 'rail',
            'destination': t['stops'][-1]['name'] if kind == 'departure' else t['stops'][0]['name'],
            'scheduledAt': mapping.iso(at), 'effectiveAt': None, 'updatedAt': None, 'quality': None, 'canceled': False,
            'platform': None, 'alertIds': []}


NAMES = {station(n)['gtfsId']: n for n in ['Ljubljana', 'Ljubljana Šiška', 'Medvode', 'Kranj', 'Lesce-Bled', 'Jesenice', 'Bled Jezero']}


class BoardTests(SimpleTestCase):
    def setUp(self):
        self.t = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice', 'Bled Jezero'])
        self.closed = notice('Vozni red nadomestnega prevoza: Ljubljana - Jesenice in obratno (26. 9. - 11. 10.).', ['IJPP:r-a'])

    def test_a_replaced_train_shows_as_its_bus_with_the_buses_line_and_end(self):
        [bus] = synthesize([self.t], [self.closed])
        plan = plan_of([self.t], [bus])
        [shown] = replacement.board_rows([row(self.t, 0)], 'departure', NAMES, lambda when: plan)
        self.assertEqual((shown['routeName'], shown['mode'], shown['tripId'], shown['routeId']), ('BUS 2400', 'bus', bus['id'], 'IJPP:sub-r-r-a'))
        self.assertEqual((shown['destination'], shown['replacesTrain'], shown['replacement']), ('Jesenice', 'LPV 2400', True))
        # From the end of the closed stretch the train runs as usual.
        [after] = replacement.board_rows([row(self.t, 2)], 'departure', NAMES, lambda when: plan)
        self.assertEqual((after['routeName'], after['mode']), ('LPV 2400', 'rail'))

    def test_arrivals_inside_the_stretch_come_by_bus(self):
        [bus] = synthesize([self.t], [self.closed])
        plan = plan_of([self.t], [bus])
        [arriving] = replacement.board_rows([row(self.t, 2, 'arrival')], 'arrival', NAMES, lambda when: plan)
        self.assertEqual((arriving['routeName'], arriving['destination']), ('BUS 2400', 'Ljubljana'))
        [first] = replacement.board_rows([row(self.t, 0, 'arrival')], 'arrival', NAMES, lambda when: plan)
        self.assertEqual(first['mode'], 'rail')

    def test_the_day_after_the_notice_ends_the_train_runs(self):
        # The notice ends the day before this run: that day's plan has no bus, so the train stays a train.
        ended = notice(self.closed['title'], ['IJPP:r-a'], start=DAY - 86400 * 10, end=DAY - 1)
        self.assertEqual(synthesize([self.t], [ended]), [])
        plan = plan_of([self.t], [])
        [shown] = replacement.board_rows([row(self.t, 0)], 'departure', NAMES, lambda when: plan)
        self.assertEqual((shown['routeName'], shown['mode']), ('LPV 2400', 'rail'))

    def test_a_real_bus_on_the_board_stands_for_its_train(self):
        bus = train('b', 'BUS 24001', ['Ljubljana', 'Kranj', 'Jesenice'], mode='BUS')
        plan = plan_of([self.t, bus], [])
        rows = replacement.board_rows([row(self.t, 0), {**row(bus, 0), 'mode': 'bus', 'replacement': True}], 'departure', NAMES, lambda when: plan)
        self.assertEqual([r['routeName'] for r in rows], ['BUS 24001'])


class SyntheticLineTests(SimpleTestCase):
    def test_the_line_is_the_bus_on_the_roads_between_its_stops(self):
        t = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice'])
        [bus] = synthesize([t], [notice(JESENICE, ['IJPP:r-a'])])
        road = [[14.5, 46.05], [14.48, 46.08], [14.47, 46.11], [14.44, 46.11]]
        served = datetime.fromtimestamp(DAY + 43200, closures.LOCAL).date()
        with mock.patch.object(scheduled, 'day_plan', return_value=plan_of([t], [bus])), \
                mock.patch.object(scheduled, '_road_shape', return_value={'coords': road, 'cum': [0, 1, 2, 3], 'distances': [0, 1, 2], 'complete': True}):
            line = scheduled.synthetic_line('IJPP:sub-r-r-a', served)
        self.assertEqual((line['name'], line['mode'], line['replacement'], line['replacesTrain']), ('BUS 2400', 'bus', True, 'LPV 2400'))
        [pattern] = line['patterns']
        self.assertEqual(pattern['geometry'], road)
        self.assertEqual([d['tripId'] for d in pattern['departures']], [bus['id']])
        self.assertEqual([s['name'] for s in pattern['stops']], ['Ljubljana', 'Kranj', 'Jesenice'])

    def test_ids(self):
        self.assertEqual(closures.synthetic_day('IJPP:sub-20261012-453228-0'), date(2026, 10, 12))
        self.assertIsNone(closures.synthetic_day('IJPP:sub-r-r-a'))
        self.assertTrue(closures.is_synthetic_line('IJPP:sub-r-r-a'))
        self.assertFalse(closures.is_synthetic_line('IJPP:sub-20261012-453228-0'))


def otp_leg(t, a, b):
    """A built train leg (journeys.build_journeys) from stop `a` to `b` of train `t`."""
    stamp = lambda epoch: datetime.fromtimestamp(epoch, closures.LOCAL).isoformat()
    place = lambda s: {'name': s['name'], 'latitude': s['lat'], 'longitude': s['lon'], 'kind': 'station', 'stopId': s['gtfsId'], 'id': s['gtfsId']}
    return {'id': 'leg:x-1', 'mode': 'rail', 'operatorId': 'IJPP:1161', 'routeId': t['route']['gtfsId'], 'tripId': t['id'],
            'routeName': t['route']['shortName'], 'headsign': t['stops'][-1]['name'],
            'origin': place(t['stops'][a]), 'destination': place(t['stops'][b]),
            'scheduledDeparture': stamp(t['departures'][a]), 'scheduledArrival': stamp(t['arrivals'][b]),
            'effectiveDeparture': stamp(t['departures'][a]), 'effectiveArrival': stamp(t['arrivals'][b]),
            'geometry': [[s['lon'], s['lat']] for s in t['stops'][a:b + 1]], 'delaySeconds': None, 'delayProvenance': None,
            'canceled': False, 'stopCount': b - a, 'alertIds': ['alert:x']}


META = {'transit': True, 'interline': False, 'duration': 0, 'realtime': False, 'platform': '2'}


class JourneyTests(SimpleTestCase):
    def setUp(self):
        self.t = train('a', 'LPV 2400', ['Ljubljana', 'Kranj', 'Jesenice', 'Bled Jezero'])
        self.road = lambda stops: {'coords': [[s['lon'], s['lat']] for s in stops] + [[14.0, 46.0]], 'complete': True}
        # Real buses are moved to their replacement stops (closures.relocate reads hand-checked tables): not here.
        relocate = mock.patch.object(closures, 'relocate', side_effect=lambda stops, *a, **k: stops)
        relocate.start()
        self.addCleanup(relocate.stop)

    def test_a_train_leg_over_the_closed_stretch_rides_the_bus_there(self):
        [bus] = synthesize([self.t], [notice('Vozni red nadomestnega prevoza: Ljubljana - Jesenice in obratno (26. 9. - 11. 10.).', ['IJPP:r-a'])])
        plan = plan_of([self.t], [bus])
        legs, meta = journey_legs.rewrite([otp_leg(self.t, 0, 3)], [META], lambda when: plan, self.road)
        self.assertEqual([(l['mode'], l['routeName'], l['origin']['name'], l['destination']['name']) for l in legs],
                         [('bus', 'BUS 2400', 'Ljubljana', 'Jesenice'), ('rail', 'LPV 2400', 'Jesenice', 'Bled Jezero')])
        ride, rest = legs
        self.assertEqual((ride['tripId'], ride['routeId'], ride['replacement'], ride['replacesTrain']), (bus['id'], 'IJPP:sub-r-r-a', True, 'LPV 2400'))
        self.assertEqual(ride['geometry'][-1], [14.0, 46.0])  # the roads, not the railway
        self.assertEqual(ride['effectiveDeparture'], otp_leg(self.t, 0, 3)['effectiveDeparture'])
        self.assertEqual(rest['effectiveArrival'], otp_leg(self.t, 0, 3)['effectiveArrival'])
        self.assertEqual(ride['alertIds'], ['alert:x'])
        # One ride for the transfers: the train waits for the bus.
        self.assertEqual([m['interline'] for m in meta], [False, True])
        walked, _ = journeys.replacement_walks(legs, meta)
        self.assertTrue(all('_boardAt' not in l and '_alightAt' not in l for l in walked))

    def test_a_ride_inside_the_stretch_is_all_bus_and_one_outside_it_all_train(self):
        [bus] = synthesize([self.t], [notice('Vozni red nadomestnega prevoza: Kranj - Jesenice in obratno (26. 9. - 11. 10.).', ['IJPP:r-a'])])
        plan = plan_of([self.t], [bus])
        legs, _ = journey_legs.rewrite([otp_leg(self.t, 1, 2)], [META], lambda when: plan, self.road)
        self.assertEqual([l['mode'] for l in legs], ['bus'])
        legs, _ = journey_legs.rewrite([otp_leg(self.t, 2, 3)], [META], lambda when: plan, self.road)
        self.assertEqual([l['mode'] for l in legs], ['rail'])

    def test_a_day_without_the_closure_keeps_the_train(self):
        legs, _ = journey_legs.rewrite([otp_leg(self.t, 0, 3)], [META], lambda when: plan_of([self.t], []), self.road)
        self.assertEqual([l['mode'] for l in legs], ['rail'])

    def test_a_real_bus_that_would_not_connect_leaves_the_leg_as_planned(self):
        late = train('b', 'BUS 24001', ['Ljubljana', 'Kranj', 'Jesenice'], start=T0 + 1800, mode='BUS')
        plan = plan_of([self.t, late], [])
        after = {**otp_leg(self.t, 0, 3), 'id': 'leg:x-2', 'mode': 'bus', 'tripId': 'X:other',
                 'effectiveDeparture': otp_leg(self.t, 0, 3)['effectiveArrival']}
        legs, _ = journey_legs.rewrite([otp_leg(self.t, 0, 2), after], [META, META], lambda when: plan, self.road)
        self.assertEqual([l['mode'] for l in legs], ['rail', 'bus'])

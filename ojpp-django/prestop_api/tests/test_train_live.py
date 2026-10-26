"""Trains and replacement buses move by the live delay of the train number (trainlive.py): a report against the train's
timetable moves whichever vehicle runs that stretch, a delay at the change station carries on, and the map, boards,
trip view and journeys show the same delay."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import geometry, journey_legs, mapping, replacement, scheduled, sz, trainlive

T0 = 1_760_000_000
SZ = {'gtfsId': 'IJPP:1161'}
NAMES = ['Ljubljana', 'Kranj', 'Podnart', 'Lesce-Bled', 'Jesenice']


def trip(id_, name, stations, times, mode='RAIL'):
    return {'id': f'IJPP:{id_}', 'pattern': id_, 'headsign': None, 'delays': [None] * len(stations),
            'route': {'gtfsId': f'IJPP:r-{id_}', 'shortName': name, 'mode': mode, 'agency': SZ},
            'stops': [{'gtfsId': f'IJPP:{s}', 'name': s, 'lat': 46.0 + NAMES.index(s) * 0.05, 'lon': 14.3} for s in stations],
            'arrivals': list(times), 'departures': list(times), 'scheduledArrivals': list(times), 'scheduledDepartures': list(times),
            'serviceDay': T0 - 36_000}


def timetable_bus(train, times, stations=NAMES, label=None):
    """A bus of SŽ's replacement timetable for `train` (closures.timetable_bus, trimmed): its own, slower times."""
    stops = [{'gtfsId': f'IJPP:bus-{s}', 'name': f'{s} AP', 'lat': 46.0 + NAMES.index(s) * 0.05, 'lon': 14.31} for s in stations]
    a, b = NAMES.index(stations[0]), NAMES.index(stations[-1])
    return {'id': f'IJPP:sub-{label or train["id"][5:]}', 'synthetic': True, 'source': 'timetable', 'trainTripId': train['id'],
            'fromIndex': a, 'toIndex': b,
            'replaces': [{'trainTripId': train['id'], 'fromIndex': a, 'toIndex': b, 'start': times[0], 'end': times[-1]}],
            'route': {'gtfsId': 'IJPP:sub-r', 'shortName': f'BUS {label or "2428"}', 'mode': 'BUS', 'agency': SZ},
            'trainName': mapping.route_name(train['route']), 'pattern': f'tt-{label}', 'headsign': stations[-1],
            'stops': stops, 'stations': [dict(s) for s in train['stops'][a:b + 1]], 'serviceDay': train['serviceDay'], 'serviceDate': '20251009',
            'arrivals': list(times), 'departures': list(times), 'delays': [None] * len(times),
            'scheduledArrivals': list(times), 'scheduledDepartures': list(times), 'alertIds': []}


def plan_of(trips, buses=()):
    sections = replacement.sections(trips)
    from prestop_api import closures
    for train, extra in closures.sections(list(buses)).items():
        sections.setdefault(train, []).extend(extra)
    return {'key': None, 'sections': sections, 'synthetic': list(buses), 'by_id': {b['id']: b for b in buses},
            'trips': {t['id']: [t] for t in trips}, 'suppressed': {}, 'decided': {}}


def update(train, at_station, delay, stamp=T0):
    """A GTFS-RT trip update of the combined feed for `train` (ids as IJPP:SZ-<trip>), at one station."""
    return {train['id']: {'updates': [{'stopId': f'IJPP:{at_station}', 'departure': {'delay': delay}}], 'timestamp': stamp, 'trip': {}}}


def board_row(t, k):
    """OTP's board row of trip `t` leaving its stop `k`, by the timetable."""
    return {'id': f'{t["id"]}@{t["serviceDay"]}/{k}', 'stopId': t['stops'][k]['gtfsId'], 'tripId': t['id'], 'routeId': t['route']['gtfsId'],
            'operatorId': SZ['gtfsId'], 'routeName': t['route']['shortName'], 'mode': t['route']['mode'].lower(),
            'destination': t['stops'][-1]['name'], 'scheduledAt': mapping.iso(t['departures'][k]), 'effectiveAt': None,
            'updatedAt': None, 'quality': None, 'canceled': False, 'platform': None, 'alertIds': [],
            **({'replacement': True} if t['route']['mode'] == 'BUS' else {})}


def shape_for(t):
    coords = [[s['lon'], s['lat']] for s in t['stops']]
    return {'coords': coords, 'cum': geometry.cumulative(coords), 'distances': geometry.cumulative(coords), 'stops': t['stops'],
            'complete': True}


def run_map(plan, trips, now, live=None, updates=None):
    shapes = {t['pattern']: shape_for(t) for t in trips}
    with mock.patch.object(scheduled.timetable, 'get', return_value=mock.Mock(value=trips)), \
            mock.patch.object(scheduled.shapes, 'get', return_value=mock.Mock(value=shapes)), \
            mock.patch.object(scheduled, '_derive', return_value=plan), \
            mock.patch.object(scheduled, '_road_shape', side_effect=lambda stops: shape_for({'stops': stops})):
        return {v['tripId']: v for v in scheduled.vehicles(now, live=live or {}, updates=updates or {})}


# LPV 2428 on 19 Oct 2026, all of it run by BUS 2428: the train is due at Lesce-Bled at T0+1800, the bus at T0+2700.
TRAIN = trip('2428', 'LPV 2428', NAMES, [T0, T0 + 600, T0 + 1200, T0 + 1800, T0 + 2400])
BUS = timetable_bus(TRAIN, [T0, T0 + 900, T0 + 1800, T0 + 2700, T0 + 3600])


class WholeTrainByBusTests(SimpleTestCase):
    def test_a_report_against_the_train_timetable_moves_the_bus_by_its_own(self):
        # +20 min at Lesce-Bled against the train (T0+1800 + 1200 = T0+3000): 5 min late by the bus's timetable.
        plan = plan_of([TRAIN], [BUS])
        live = trainlive.of(plan, BUS, update(TRAIN, 'Lesce-Bled', 1200), {})
        self.assertEqual(live['delays'], [None, None, None, 300, 300])
        self.assertEqual(live['source'], 'gtfs-rt')
        shown = run_map(plan, [TRAIN], T0 + 2800, updates=update(TRAIN, 'Lesce-Bled', 1200))
        self.assertEqual(list(shown), [BUS['id']])  # the train is not drawn on the stretch its bus runs
        v = shown[BUS['id']]
        self.assertEqual((v['delaySeconds'], v['delaySource'], v['quality'], v['nextStop']), (300, 'gtfs-rt', 'scheduled', 'Lesce-Bled AP'))
        self.assertEqual(v['replacesTrain'], 'LPV 2428')  # the sheet names the train it runs for
        self.assertFalse(v['stopped'])  # by the timetable it would stand at Lesce-Bled now; it is 5 min behind

    def test_a_bus_is_never_early_by_a_train_delay(self):
        # SŽ's least delay is 0: "on time" against the train is no reason to draw the slower bus ahead of its timetable.
        live = trainlive.of(plan_of([TRAIN], [BUS]), BUS, update(TRAIN, 'Kranj', 0), {})
        self.assertEqual(live['delays'], [None, 0, 0, 0, 0])

    def test_sz_report_moves_the_bus_but_its_coordinates_are_not_the_bus(self):
        report = {'2428': {'number': '2428', 'category': 'LPV', 'delay': 1200, 'next': 'LESCE-BLED', 'coords': (46.30, 14.18), 'at': T0 + 2790}}
        v = run_map(plan_of([TRAIN], [BUS]), [TRAIN], T0 + 2800, live=report)[BUS['id']]
        self.assertEqual((v['delaySeconds'], v['delaySource'], v['quality']), (300, 'sz', 'inferred'))
        self.assertNotEqual((v['latitude'], v['longitude']), (46.30, 14.18))
        self.assertEqual(v['nextStop'], 'Lesce-Bled AP')

    def test_one_delay_on_the_map_the_board_the_trip_and_the_journey(self):
        plan = plan_of([TRAIN], [BUS])
        feed = update(TRAIN, 'Lesce-Bled', 1200)
        with mock.patch.object(trainlive, 'trip_updates', return_value=feed):
            v = run_map(plan, [TRAIN], T0 + 2800, updates=feed)[BUS['id']]
            [row] = replacement.timetable_rows(plan, 'departure', {'IJPP:bus-Lesce-Bled'}, T0, T0 + 4000, {}, merged=False)
            with mock.patch.object(scheduled, 'synthetic_bus', return_value=(BUS, plan)), mock.patch.object(scheduled, '_road_shape', return_value=None):
                entry = scheduled.synthetic_entry(BUS['id'])
            leg = {'id': 'leg:x-0', 'scheduledDeparture': mapping.iso(T0), 'routeName': 'LPV 2428', 'mode': 'rail'}
            piece = journey_legs._with_live(journey_legs._bus_ride(leg, BUS, 3, 4, lambda stops: None, 'bus0', plan))
        at = mapping.iso(T0 + 2700 + 300)
        self.assertEqual(v['delaySeconds'], 300)
        self.assertEqual((row['scheduledAt'], row['effectiveAt'], row['quality'], row['delaySource']), (mapping.iso(T0 + 2700), at, 'predicted', 'gtfs-rt'))
        self.assertEqual(entry['times'][3]['realtimeDeparture'] - entry['times'][3]['scheduledDeparture'], 300)
        self.assertTrue(entry['times'][3]['realtime'])
        self.assertEqual((piece['delaySeconds'], journey_legs._ts(piece['effectiveDeparture']), piece['delayProvenance']), (300, T0 + 3000, 'predicted'))
        self.assertNotIn('_live', piece)

    def test_buses_side_by_side_on_one_stretch_keep_their_timetable(self):
        first = timetable_bus(TRAIN, [T0, T0 + 900, T0 + 1800, T0 + 2700, T0 + 3600], label='2428/1')
        second = timetable_bus(TRAIN, [T0 + 300, T0 + 1200, T0 + 2100, T0 + 3000, T0 + 3900], label='2428/2')
        plan = plan_of([TRAIN], [first, second])
        self.assertIsNone(trainlive.of(plan, first, update(TRAIN, 'Lesce-Bled', 1200), {}))
        self.assertIsNone(trainlive.of(plan, second, update(TRAIN, 'Lesce-Bled', 1200), {}))


class PartlyReplacedTests(SimpleTestCase):
    def test_a_late_train_makes_its_bus_leave_late(self):
        # The train runs Ljubljana - Podnart, a feed bus Podnart - Jesenice, leaving 5 min after the train is due.
        train = trip('2002', 'LPV 2002', NAMES, [T0, T0 + 600, T0 + 1200, T0 + 1800, T0 + 2400])
        bus = trip('bus', 'BUS 20029', NAMES[2:], [T0 + 1500, T0 + 2400, T0 + 3300], mode='BUS')
        plan = plan_of([train, bus])
        live = trainlive.of(plan, bus, update(train, 'Kranj', 600), {})
        # Due at Podnart T0+1200 + 10 min = T0+1800: the bus leaves 5 min late, and stays so.
        self.assertEqual(live['delays'], [300, 300, 300])
        self.assertIsNone(live['reported'])
        shown = run_map(plan, [train, bus], T0 + 2000, updates=update(train, 'Kranj', 600))
        self.assertEqual((shown['IJPP:bus']['delaySeconds'], shown['IJPP:bus']['delaySource']), (300, 'gtfs-rt'))

    def test_the_train_after_its_bus_carries_the_bus_delay(self):
        # A bus Ljubljana - Podnart, then the same train on to Jesenice; SŽ reports the number at Kranj (the bus).
        train = trip('1896', 'LPV 1896', NAMES, [T0, T0 + 600, T0 + 1200, T0 + 1800, T0 + 2400])
        bus = trip('bus', 'BUS 18969', NAMES[:3], [T0, T0 + 900, T0 + 1800], mode='BUS')
        plan = plan_of([train, bus])
        report = {'1896': {'number': '1896', 'category': 'LPV', 'delay': 600, 'next': 'Kranj', 'coords': (46.05, 14.29), 'at': T0 + 700}}
        bus_live, train_live = trainlive.of(plan, bus, {}, report), trainlive.of(plan, train, {}, report)
        # Kranj: train T0+600 + 600 = T0+1200, the bus's T0+900: 5 min late, so at Podnart T0+2100; the train was due
        # to leave there at T0+1200: 15 min late from Podnart on.
        self.assertEqual(bus_live['delays'], [None, 300, 300])
        self.assertEqual(train_live['delays'], [None, None, 900, 900, 900])
        self.assertIsNone(train_live['reported'])
        shown = run_map(plan, [train, bus], T0 + 800, live=report)
        self.assertEqual(list(shown), ['IJPP:bus'])  # the report is the bus's: the train is not drawn at Kranj
        v = shown['IJPP:bus']
        self.assertEqual((v['delaySeconds'], v['quality'], v['delaySource']), (300, 'inferred', 'sz'))
        self.assertNotEqual((v['latitude'], v['longitude']), (46.05, 14.29))
        after = run_map(plan, [train, bus], T0 + 2400, live={'1896': {**report['1896'], 'at': T0 + 2390}})
        self.assertEqual((after['IJPP:1896']['delaySeconds'], after['IJPP:1896']['nextStop']), (900, 'Lesce-Bled'))

    def test_a_bus_on_from_where_the_feed_ends_the_train_names_it_and_takes_its_delay(self):
        # ICS 31 on 20 Oct 2026: the feed's train runs Maribor - Celje only, BUS 31006 on from Celje to Ljubljana.
        train = trip('31', 'ICS 31', NAMES[:3], [T0, T0 + 600, T0 + 1200])
        bus = trip('bus', 'BUS 31006', NAMES[2:], [T0 + 1500, T0 + 2400, T0 + 3300], mode='BUS')
        plan = plan_of([train, bus])
        feed = update(train, 'Kranj', 600)
        # Due at Podnart T0+1200 + 10 min = T0+1800: the bus leaves 5 min late.
        self.assertEqual(trainlive.carried(trainlive.of(plan, bus, feed, {})['delays']), [300, 300, 300])
        v = run_map(plan, [train, bus], T0 + 2000, updates=feed)['IJPP:bus']
        self.assertEqual((v['replacesTrain'], v['delaySeconds'], v['delaySource']), ('ICS 31', 300, 'gtfs-rt'))
        # Its own row on a board (OTP has no live time for it) shows the same.
        with mock.patch.object(trainlive, 'trip_updates', return_value=feed):
            [row] = replacement.board_rows([board_row(bus, 1)], 'departure', {'IJPP:Lesce-Bled': 'Lesce-Bled'}, lambda when: plan)
        self.assertEqual((row['effectiveAt'], row['quality'], row['delaySource'], row['replacesTrain']),
                         (mapping.iso(T0 + 2700), 'predicted', 'gtfs-rt', 'ICS 31'))

    def test_a_bus_before_where_the_feed_starts_the_train_names_it_and_keeps_its_timetable(self):
        # ICS 14: BUS 14006 Ljubljana - Celje, then the train on to Maribor. Its updates are the train's, not the bus's.
        bus = trip('bus', 'BUS 14006', NAMES[:3], [T0, T0 + 900, T0 + 1800], mode='BUS')
        train = trip('14', 'ICS 14', NAMES[2:], [T0 + 2100, T0 + 2700, T0 + 3300])
        plan = plan_of([train, bus])
        feed = update(train, 'Podnart', 300)
        self.assertIsNone(trainlive.of(plan, bus, feed, {}))
        v = run_map(plan, [train, bus], T0 + 1000, updates=feed)['IJPP:bus']
        self.assertEqual((v['replacesTrain'], v['delaySeconds']), ('ICS 14', None))
        self.assertNotIn('delaySource', v)
        with mock.patch.object(trainlive, 'trip_updates', return_value=feed):
            [row] = replacement.board_rows([board_row(bus, 1)], 'departure', {'IJPP:Kranj': 'Kranj'}, lambda when: plan)
        self.assertEqual((row['effectiveAt'], row['replacesTrain']), (None, 'ICS 14'))
        self.assertNotIn('delaySource', row)

    def test_a_notice_bus_has_the_train_timetable_and_its_delay(self):
        from prestop_api import closures
        train = trip('2400', 'LPV 2400', NAMES, [T0, T0 + 600, T0 + 1200, T0 + 1800, T0 + 2400])
        bus = {**trip('sub-x', 'BUS 2400', NAMES[1:4], train['arrivals'][1:4], mode='BUS'), 'synthetic': True,
               'trainTripId': train['id'], 'fromIndex': 1, 'toIndex': 3, 'serviceDate': '20251009'}
        plan = plan_of([train], [bus])
        self.assertEqual(closures.sections([bus])[train['id']][0]['busTripId'], bus['id'])
        shown = run_map(plan, [train], T0 + 1000, updates=update(train, 'Podnart', 240))
        self.assertEqual(list(shown), [bus['id']])
        self.assertEqual((shown[bus['id']]['delaySeconds'], shown[bus['id']]['delaySource']), (240, 'gtfs-rt'))


class NoLiveDataTests(SimpleTestCase):
    def test_no_report_keeps_the_timetable(self):
        v = run_map(plan_of([TRAIN], [BUS]), [TRAIN], T0 + 2800)[BUS['id']]
        self.assertEqual((v['quality'], v['delaySeconds'], 'delaySource' in v), ('scheduled', None, False))
        self.assertEqual(v['replacesTrain'], 'LPV 2428')
        [row] = replacement.timetable_rows(plan_of([TRAIN], [BUS]), 'departure', {'IJPP:bus-Lesce-Bled'}, T0, T0 + 4000, {}, merged=False)
        self.assertEqual((row['effectiveAt'], 'delaySource' in row), (None, False))
        self.assertEqual(v['nextStop'], 'Jesenice AP')  # by its timetable it has left Lesce-Bled

    def test_a_stale_report_is_no_live_data(self):
        trains = sz.LiveTrains()
        trains._items = {'2428': {'number': '2428', 'delay': 1200, 'next': 'Lesce-Bled', 'coords': None, 'at': T0 + 2800 - sz.FRESH - 1}}
        with self.settings(PRESTOP_SZ_LIVE_URL=''):
            reports = trains.get(T0 + 2800)
        self.assertEqual(reports, {})
        v = run_map(plan_of([TRAIN], [BUS]), [TRAIN], T0 + 2800, live=reports)[BUS['id']]
        self.assertEqual((v['quality'], v['delaySeconds']), ('scheduled', None))

    def test_another_days_update_or_an_unconfirmed_huge_delay_is_no_live_data(self):
        plan = plan_of([TRAIN], [BUS])
        self.assertIsNone(trainlive.of(plan, BUS, update(TRAIN, 'Lesce-Bled', 1200, stamp=T0 - 86_400), {}))
        self.assertIsNone(trainlive.of(plan, BUS, update(TRAIN, 'Lesce-Bled', 3 * 3600), {}))

    def test_a_train_without_a_bus_moves_by_its_update_and_says_so(self):
        train = trip('2904', 'LPV 2904', NAMES, [T0, T0 + 600, T0 + 1200, T0 + 1800, T0 + 2400])
        v = run_map(plan_of([train]), [train], T0 + 700, updates=update(train, 'Kranj', 120))['IJPP:2904']
        self.assertEqual((v['delaySeconds'], v['delaySource'], v['quality'], v['nextStop']), (120, 'gtfs-rt', 'scheduled', 'Kranj'))

"""Trains a replacement bus stands in for: matched, hidden on the replaced stretch, marked on boards;
every replacement trip is drawn; walks to replacement stops beside the station."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import geometry, journeys, mapping, replacement, scheduled

T0 = 1_760_000_000
SZ = {'gtfsId': 'IJPP:1161'}
NAMES = ['Ljubljana', 'Brezovica', 'Borovnica', 'Logatec', 'Postojna']


def trip(id_, name, stations, start, step=600, mode='RAIL'):
    n = len(stations)
    return {'id': f'IJPP:{id_}', 'pattern': id_, 'headsign': None, 'delays': [None] * n,
            'route': {'gtfsId': f'IJPP:r-{id_}', 'shortName': name, 'mode': mode, 'agency': SZ},
            'stops': [{'gtfsId': f'IJPP:{s}', 'name': s, 'lat': 46.0, 'lon': 14.3 + NAMES.index(s) * 0.05} for s in stations],
            'arrivals': [start + i * step for i in range(n)], 'departures': [start + i * step + 60 * (0 < i < n - 1) for i in range(n)]}


def shape_for(t):
    coords = [[s['lon'], s['lat']] for s in t['stops']]
    return {'coords': coords, 'cum': geometry.cumulative(coords), 'distances': geometry.cumulative(coords), 'stops': t['stops']}


class MatchTests(SimpleTestCase):
    def test_bus_numbers_carry_the_train_number(self):
        self.assertEqual(replacement.train_numbers('BUS 18969'), ['1896', '189', '18'])
        self.assertEqual(replacement.train_numbers('BUS 52606'), ['5260', '526', '52'])
        # ICS 14's bus Ljubljana – Celje: the number filled to five digits with 006.
        self.assertIn('14', replacement.train_numbers('BUS 14006'))

    def test_an_ics_bus_is_matched_to_its_train(self):
        bus = trip('bus', 'BUS 14006', ['Ljubljana', 'Logatec'], T0, mode='BUS')
        train = trip('ics', 'ICS 14', ['Logatec', 'Postojna'], T0 + 1500)
        found = replacement.sections([bus, train])
        self.assertEqual((found['IJPP:ics'][0]['fromIndex'], found['IJPP:ics'][0]['toIndex']), (None, 0))

    def test_a_train_trip_lists_the_stretch_its_bus_runs(self):
        train = trip('1896', 'LPV 1896', NAMES, T0)
        bus = trip('bus', 'BUS 18969', ['Brezovica', 'Borovnica', 'Logatec'], T0 + 600, mode='BUS')
        plan = {'sections': replacement.sections([bus, train]), 'trips': {train['id']: [train], bus['id']: [bus]}, 'by_id': {}}
        built = {'id': train['id'], 'stops': [{'name': s, 'scheduledDeparture': mapping.iso(train['departures'][i])} for i, s in enumerate(NAMES)]}
        self.assertEqual(replacement.trip_sections(built, plan), [{'fromIndex': 1, 'toIndex': 3, 'busTripId': bus['id'], 'busName': 'BUS 18969'}])
        # Another day's run of the train is not this trip's.
        late = {**built, 'stops': [{**s, 'scheduledDeparture': mapping.iso(train['departures'][i] + 86_400)} for i, s in enumerate(built['stops'])]}
        self.assertEqual(replacement.trip_sections(late, {**plan, 'trips': {train['id']: [{**train, 'departures': [d + 86_400 for d in train['departures']], 'arrivals': [a + 86_400 for a in train['arrivals']]}], bus['id']: [bus]}}), [])

    def test_car_trains_are_trains(self):
        self.assertFalse(mapping.is_replacement({'shortName': 'AVT 853', 'mode': 'RAIL', 'agency': SZ}))

    def test_split_train_and_through_train_are_matched(self):
        bus = trip('bus', 'BUS 18969', ['Ljubljana', 'Brezovica', 'Logatec'], T0, mode='BUS')
        split = trip('split', 'LPV 1896', ['Logatec', 'Postojna'], T0 + 1500)
        through = trip('through', 'IC 2752', ['Ljubljana', 'Brezovica', 'Borovnica', 'Logatec', 'Postojna'], T0)
        other = trip('other', 'IC 509', ['Ljubljana', 'Logatec'], T0)  # another number: never matched by times alone
        bus2 = trip('bus2', 'BUS 27521', ['Ljubljana', 'Logatec'], T0, mode='BUS')
        found = replacement.sections([bus, split, through, other, bus2])
        self.assertEqual(found['IJPP:split'][0]['fromIndex'], None)
        self.assertEqual(found['IJPP:split'][0]['toIndex'], 0)
        self.assertEqual((found['IJPP:through'][0]['fromIndex'], found['IJPP:through'][0]['toIndex']), (0, 3))
        self.assertNotIn('IJPP:other', found)


class SuppressionTests(SimpleTestCase):
    def run_at(self, trips, now, live=None):
        shapes = {t['pattern']: shape_for(t) for t in trips}
        with mock.patch.object(scheduled.timetable, 'get', return_value=mock.Mock(value=trips)), \
                mock.patch.object(scheduled.shapes, 'get', return_value=mock.Mock(value=shapes)), \
                mock.patch.object(scheduled, '_road_shape', side_effect=lambda stops: shape_for({'stops': stops})):
            return scheduled.vehicles(now, live=live or {})

    def test_a_through_train_is_hidden_on_the_replaced_stretch_and_shown_after_it(self):
        bus = trip('bus', 'BUS 27521', ['Ljubljana', 'Brezovica', 'Logatec'], T0, step=900, mode='BUS')
        train = trip('train', 'IC 2752', ['Ljubljana', 'Brezovica', 'Borovnica', 'Logatec', 'Postojna'], T0)
        during = self.run_at([bus, train], T0 + 700)
        self.assertEqual([v['tripId'] for v in during], ['IJPP:bus'])
        self.assertTrue(during[0]['replacement'])
        after = self.run_at([bus, train], T0 + 2000)  # bus arrived (T0 + 1800); the train runs on beyond Logatec
        self.assertIn('IJPP:train', [v['tripId'] for v in after])

    def test_live_reports_of_the_number_are_ignored_while_the_bus_runs(self):
        bus = trip('bus', 'BUS 18969', ['Ljubljana', 'Brezovica', 'Logatec'], T0, mode='BUS')
        split = trip('split', 'LPV 1896', ['Logatec', 'Postojna'], T0 + 1500)
        report = {'1896': {'number': '1896', 'category': 'LPV', 'delay': 0, 'next': 'Logatec', 'coords': (46.0, 14.36), 'at': T0 + 590}}
        shown = self.run_at([bus, split], T0 + 600, live=report)
        self.assertEqual([v['tripId'] for v in shown], ['IJPP:bus'])

    def test_every_replacement_trip_of_the_day_is_drawn_while_it_runs(self):
        buses = [trip(f'b{i}', f'BUS 1000{i}', ['Ljubljana', 'Logatec'], T0 + i * 3600, mode='BUS') for i in range(5)]
        seen = set()
        for b in buses:
            seen |= {v['tripId'] for v in self.run_at(buses, b['departures'][0] + 300) if v.get('replacement')}
        self.assertEqual(seen, {b['id'] for b in buses})


class BoardTests(SimpleTestCase):
    def test_trains_leaving_on_a_replaced_stretch_say_so(self):
        bus = trip('bus', 'BUS 27521', ['Ljubljana', 'Logatec'], T0, mode='BUS')
        train = trip('train', 'IC 2752', ['Ljubljana', 'Brezovica', 'Logatec', 'Postojna'], T0)
        found = replacement.sections([bus, train])
        names = {'IJPP:Brezovica': 'Brezovica', 'IJPP:Logatec': 'Logatec'}
        rows = [{'mode': 'rail', 'tripId': 'IJPP:train', 'stopId': 'IJPP:Brezovica', 'scheduledAt': mapping.iso(T0 + 660)},
                {'mode': 'rail', 'tripId': 'IJPP:train', 'stopId': 'IJPP:Logatec', 'scheduledAt': mapping.iso(T0 + 1260)}]
        replacement.mark_board(rows, names, [bus, train], found)
        self.assertEqual([r.get('replacedByBus') for r in rows], [True, None])


def leg(start, end, frm, to, replacement_=False):
    return {'id': f'leg:x-{start}', 'mode': 'bus' if replacement_ else 'rail', 'operatorId': 'IJPP:1161', 'routeId': 'IJPP:r', 'tripId': 'IJPP:t',
            'routeName': 'X', 'headsign': None, 'origin': frm, 'destination': to,
            'scheduledDeparture': start, 'scheduledArrival': end, 'effectiveDeparture': start, 'effectiveArrival': end,
            'geometry': [[frm['longitude'], frm['latitude']], [to['longitude'], to['latitude']]], 'delaySeconds': None,
            'delayProvenance': None, 'canceled': False, 'alertIds': [], **({'replacement': True} if replacement_ else {})}


class WalkTests(SimpleTestCase):
    def test_the_walk_to_a_replacement_stop_beside_the_station_is_its_own_leg(self):
        siska = {'name': 'Ljubljana Šiška', 'latitude': 46.060837, 'longitude': 14.501054, 'kind': 'station', 'stopId': 'IJPP:1167093'}
        lj = {'name': 'Ljubljana', 'latitude': 46.0585089, 'longitude': 14.5129236, 'kind': 'station', 'stopId': 'IJPP:1122804'}
        kranj = {'name': 'Kranj', 'latitude': 46.24, 'longitude': 14.35, 'kind': 'station', 'stopId': 'IJPP:k'}
        legs = [leg('2026-10-10T10:00:00+02:00', '2026-10-10T10:20:00+02:00', kranj, siska),
                leg('2026-10-10T10:30:00+02:00', '2026-10-10T10:45:00+02:00', siska, lj, replacement_=True)]
        meta = [{'transit': True, 'interline': False, 'duration': 1200, 'realtime': False, 'platform': None}] * 2
        stops = {'IJPP:1167093': [{'lat': 46.0610393, 'lon': 14.5002318, 'label': 'Avtobusno postajališče SŽ Šiška', 'stationId': 'IJPP:1167093'}],
                 'IJPP:1122804': [{'lat': 46.0578823, 'lon': 14.5120725, 'label': 'Avtobusna postaja Ljubljana', 'stationId': 'IJPP:1122804'}]}
        with mock.patch('prestop_api.stopfix.replacement_stops', side_effect=lambda ids: [r for i in ids for r in stops.get(i, [])]), \
                mock.patch('prestop_api.sources.stop_group', side_effect=lambda i: [i]):
            out, out_meta = journeys.replacement_walks(legs, meta)
        self.assertEqual([l['mode'] for l in out], ['rail', 'walk', 'bus', 'walk'])
        self.assertEqual(out[1]['destination']['name'], 'Avtobusno postajališče SŽ Šiška')
        self.assertEqual(out[2]['origin']['name'], 'Avtobusno postajališče SŽ Šiška')
        self.assertEqual(out[1]['effectiveArrival'], '2026-10-10T10:30:00+02:00')
        self.assertEqual(out[3]['destination']['name'], 'Ljubljana')
        self.assertTrue(all(m['duration'] > 0 for m in out_meta[1::2]))


class JourneyNoticeTests(SimpleTestCase):
    NOTICE = {'id': 'alert:lc', 'kind': 'replacement', 'title': 'Buses replace trains: Ljubljana - Logatec and vice versa (14/12/2025 - 12/12/2026).'}
    INFO = {'id': 'alert:info', 'kind': 'info', 'title': 'NOTICE: Merged trains.'}

    def leg(self, trip_id):
        return {'mode': 'rail', 'tripId': trip_id, 'scheduledDeparture': '2025-10-09T10:00:00+02:00', 'alertIds': ['alert:lc', 'alert:info']}

    def test_a_train_that_runs_loses_the_notice_about_the_buses_that_replace_other_trains(self):
        from prestop_api import journey_legs
        bus = trip('bus', 'BUS 14006', ['Ljubljana', 'Logatec'], T0, mode='BUS')
        plan = {'sections': {'IJPP:ics14': [{}]}, 'trips': {'IJPP:bus': [bus]}, 'synthetic': []}
        alerts = {a['id']: a for a in (self.NOTICE, self.INFO)}
        running, replaced = self.leg('IJPP:ics20'), self.leg('IJPP:ics14')
        journey_legs.unreplaced_notices([running, replaced], lambda when: plan, alerts)
        self.assertEqual(running['alertIds'], ['alert:info'])
        self.assertEqual(replaced['alertIds'], ['alert:lc', 'alert:info'])

    def test_the_notice_stays_where_no_bus_is_known_on_its_section(self):
        from prestop_api import journey_legs
        plan = {'sections': {}, 'trips': {}, 'synthetic': []}
        leg = self.leg('IJPP:ics20')
        journey_legs.unreplaced_notices([leg], lambda when: plan, {a['id']: a for a in (self.NOTICE, self.INFO)})
        self.assertEqual(leg['alertIds'], ['alert:lc', 'alert:info'])

    def test_a_feed_bus_says_which_train_it_replaces(self):
        from prestop_api import journey_legs
        bus = trip('bus', 'BUS 14006', ['Ljubljana', 'Logatec'], T0, mode='BUS')
        train = trip('ics', 'ICS 14', ['Logatec', 'Postojna'], T0 + 1500)
        plan = {'sections': replacement.sections([bus, train]), 'trips': {'IJPP:bus': [bus], 'IJPP:ics': [train]}, 'synthetic': []}
        leg = {'mode': 'bus', 'replacement': True, 'tripId': 'IJPP:bus', 'scheduledDeparture': '2025-10-09T10:00:00+02:00', 'alertIds': []}
        journey_legs.name_replaced_trains([leg], lambda when: plan)
        self.assertEqual(leg['replacesTrain'], 'ICS 14')


class StopNameTests(SimpleTestCase):
    def test_a_replacement_stop_says_which_station_it_is_at(self):
        from prestop_api import stopfix
        self.assertEqual(stopfix.stop_name('Zunanja stran železniške postaje', 'Črnomelj'), 'Črnomelj · Zunanja stran železniške postaje')
        self.assertEqual(stopfix.stop_name('Nova Avtobusna postaja Ljubljana (peroni 37, 38 in 39).', 'Ljubljana'), 'Nova Avtobusna postaja Ljubljana (peroni 37, 38 in 39).')
        self.assertEqual(stopfix.stop_name('Avtobusno postajališče Lesce ŽP', 'Lesce-Bled'), 'Avtobusno postajališče Lesce ŽP')
        self.assertEqual(stopfix.stop_name('', 'Kranj'), 'Kranj')

"""Replacement buses from SŽ's replacement timetables (sztimetables.py, closures.plan), on a snapshot of the feed.

The feed snapshot (fixtures/sztimetables/feed-trips.json) holds the SŽ trains of the days below as OTP had
them on 2026-10-14, and the feed's own Ljubljana - Logatec buses. The timetables are the hand-written
contract files beside it.
"""
import base64
import json
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

import copy

from prestop_api import closures, journey_legs, journeys, mapping, replacement, scheduled, sources, sztimetables, warm
from prestop_api.tests.test_replacement_days import META, otp_leg

LOCAL = ZoneInfo('Europe/Ljubljana')
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'sztimetables'
FEED = json.loads((FIXTURES / 'feed-trips.json').read_text(encoding='utf-8'))
SZ = {'gtfsId': 'IJPP:1161'}

NOTICES = {  # SŽ notice: its OTP alert's title and days (none of them lists its trains, or the trains do not matter here)
    '11147': ('Vozni red nad. prevoza: Ljubljana - Jesenice - Beljak (A) in obratno (12. - 18. 10.).', '2026-10-12', '2026-10-18'),
    '11248': ('Vozni red nadomestnega prevoza: Lesce Bled - Jesenice / Beljak (A) in obratno (12. - 18. 10.).', '2026-10-12', '2026-10-18'),
    '11056': ('Vozni red nadomestnega prevoza: Vintgar - Jesenice in obratno (23. 9. - 25. 10.).', '2026-09-23', '2026-10-25'),
    '11198': ('Vozni red nadomestnega prevoza: Ljubljana - Kranj / Jesenice / Beljak in obratno (19. - 23. 10.).', '2026-10-19', '2026-10-23'),
    '10088': ('Vozni red nadomestnega prevoza: Ljubljana - Logatec in obratno (do 12. decembra).', '2026-04-07', '2026-12-12'),
    # Made up, without a timetable: guessed as before.
    '99001': ('Vozni red nadomestnega prevoza: Ljubljana Šiška - Kranj in obratno (14. 10.).', '2026-10-14', '2026-10-14'),
    '99002': ('Vozni red nadomestnega prevoza: Ljubljana - Lesce Bled in obratno (14. 10.).', '2026-10-14', '2026-10-14'),
}


def epoch(day: str, hhmm: str = '00:00') -> float:
    return datetime.fromisoformat(f'{day}T{hhmm}').replace(tzinfo=LOCAL).timestamp()


def alert(number: str, routes=()) -> dict:
    title, start, end = NOTICES[number]
    raw = base64.b64encode(f'Alert:IJPP:SZ-OVIRA-{number}'.encode()).decode().rstrip('=')
    return {'id': f'alert:{raw}', '_aliases': [f'alert:{raw}'], 'title': title, 'message': '', 'kind': 'replacement',
            'routeIds': list(routes), 'stopIds': [], 'operatorId': 'IJPP:1161', '_from': epoch(start), '_to': epoch(end, '23:59')}


ALERTS = [alert(n) for n in NOTICES if not n.startswith('99')]
UNTIMED = [alert('99001'), alert('99002')]


def feed(day: str) -> list[dict]:
    """The snapshot's trips of service day `day` (YYYYMMDD) as scheduled.py holds them."""
    out = []
    for t in FEED[day]:
        base, n = t['serviceDay'], len(t['stops'])
        arrivals = [base + s[4] for s in t['stops']]
        departures = [base + s[5] for s in t['stops']]
        out.append({'id': t['id'], 'route': {'gtfsId': t['route'], 'shortName': t['name'], 'longName': '', 'mode': t['mode'], 'agency': SZ},
                    'pattern': t['pattern'], 'headsign': None, 'serviceDay': base,
                    'stops': [{'gtfsId': s[0], 'name': s[1], 'lat': s[2], 'lon': s[3]} for s in t['stops']],
                    'arrivals': arrivals, 'departures': departures, 'delays': [None] * n,
                    'scheduledArrivals': list(arrivals), 'scheduledDepartures': list(departures)})
    return out


def stop_index(trips: list[dict]) -> dict:
    """The stop index of these trips. The feed's SŽ buses call at railway stations (whose trains the snapshot
    leaves out between Ljubljana and Logatec), so their stops are railway stations too."""
    stops: dict[str, dict] = {}
    for t in trips:
        mode = 'rail' if t['route']['mode'] == 'RAIL' or t['route']['agency'] == SZ else 'bus'
        for s in t['stops']:
            entry = stops.setdefault(s['gtfsId'], {'id': s['gtfsId'], 'name': s['name'], 'latitude': s['lat'], 'longitude': s['lon'], 'modes': []})
            if mode not in entry['modes']:
                entry['modes'].append(mode)
    return {'list': list(stops.values()), 'all': list(stops.values())}


TABLES = sztimetables.read(FIXTURES)


def build(day: str, tables=TABLES, extra=(), alerts=ALERTS) -> dict:
    """closures.plan for service day `day`, as scheduled.day_plan works it out."""
    trips = feed(day) + list(extra)
    with mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]):
        return closures.plan(trips, replacement.sections(trips), alerts, [], {}, stop_index(trips), tables)


def timetabled(plan: dict) -> dict[str, dict]:
    return {b['route']['shortName']: b for b in plan['buses'] if b.get('source') == 'timetable'}


def times(bus: dict) -> list[str]:
    """Departure from the first stop, arrival at the others, local HH:MM."""
    stamps = [bus['departures'][0]] + bus['arrivals'][1:]
    return [datetime.fromtimestamp(t, LOCAL).strftime('%H:%M') for t in stamps]


def names(bus: dict) -> list[str]:
    return [s['name'] for s in bus['stops']]


def trip_id(day: str, name: str) -> str:
    return next(t['id'] for t in FEED[day] if t['name'] == name)


class WednesdayTests(SimpleTestCase):
    """2026-10-14, notice 11248 (and 11147, which links the same timetable)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = build('20261014')
        cls.buses = timetabled(cls.plan)
        cls.sections = closures.sections(cls.plan['buses'])

    def test_train_2400_is_a_train_to_lesce_bled_then_a_bus_to_jesenice(self):
        bus = self.buses['BUS 2400']
        self.assertEqual(names(bus), ['Lesce-Bled', 'Žirovnica', 'Slovenski Javornik', 'Jesenice'])
        self.assertEqual(times(bus), ['05:40', '05:47', '05:52', '05:57'])
        train = trip_id('20261014', 'LPV 2400')
        [section] = self.sections[train]
        self.assertEqual((section['fromIndex'], section['toIndex'], section['busTripId']), (12, 15, bus['id']))
        self.assertEqual(bus['id'], f'IJPP:sub-20261014-{train.split(":")[1]}-p0')
        self.assertEqual((bus['trainTripId'], bus['trainName']), (train, 'LPV 2400'))
        self.assertEqual(len([b for b in self.plan['buses'] if b.get('trainTripId') == train]), 1)  # no guessed bus beside it

    def test_train_318_is_three_buses_with_the_timetables_times(self):
        first, second, third = self.buses['BUS 318/1'], self.buses['BUS 318/2'], self.buses['BUS 318/3']
        self.assertEqual((names(first), times(first)), (['Ljubljana', 'Litostroj', 'Jesenice'], ['07:42', '07:51', '08:32']))
        self.assertEqual((names(second), times(second)),
                         (['Ljubljana', 'Litostroj', 'Kranj', 'Lesce-Bled'], ['07:42', '07:51', '08:22', '08:47']))
        self.assertEqual((names(third), times(third)), (['Kranj', 'Lesce-Bled', 'Jesenice'], ['07:47', '08:12', '08:32']))
        self.assertEqual({b['route']['gtfsId'] for b in (first, second, third)}, {closures.synthetic_line_id('IJPP:64427')})
        self.assertEqual(len({b['id'] for b in (first, second, third)}), 3)
        # The train counts as replaced on the union of its buses' stretches: Ljubljana (13) to Jesenice (17).
        train = trip_id('20261014', 'RG 318')
        found = self.sections[train]
        self.assertEqual(sorted((s['fromIndex'], s['toIndex']) for s in found), [(13, 16), (13, 17), (15, 17)])
        self.assertTrue(all(any(replacement.inside(s, i) for s in found) for i in range(14, 18)))
        self.assertFalse(any(replacement.inside(s, i) for s in found for i in range(1, 14)))  # Dobova - Ljubljana by train

    def test_a_train_the_timetable_does_not_list_runs_as_a_train(self):
        # Notice 11248's OTP alert names no trains, and every train it could mean is in the timetable on this day;
        # notice 11147 (Ljubljana - Jesenice, also no trains named) links the same timetable. LPV 2442
        # (Ljubljana Šiška - Kranj) is in no column: it runs, though both notices used to give it a bus.
        train = trip_id('20261014', 'LPV 2442')
        self.assertNotIn(train, self.sections)
        self.assertFalse([b for b in self.plan['buses'] if b.get('trainTripId') == train])
        guessed = build('20261014', tables=None)
        self.assertTrue([b for b in guessed['buses'] if b.get('trainTripId') == train])

    def test_stations_abroad_are_left_out(self):
        self.assertEqual(names(self.buses['BUS 414'])[-1], 'Jesenice')
        self.assertEqual(names(self.buses['BUS 415'])[0], 'Jesenice')
        self.assertEqual(times(self.buses['BUS 415']), ['07:00', '07:20', '07:45', '08:25'])

    def test_every_bus_carries_the_notices_that_link_its_timetable(self):
        ids = {a['id'] for a in ALERTS if closures.notice_id(a) in ('11147', '11248')}
        self.assertEqual(set(self.buses['BUS 2400']['alertIds']), ids)


class SundayTests(SimpleTestCase):
    def test_footnotes_choose_the_buses_of_the_day(self):
        buses = timetabled(build('20261018'))  # Sunday 18 October
        for workdays in ('BUS 2400', 'BUS 2402', 'BUS 2424'):  # footnote 2
            self.assertNotIn(workdays, buses)
        for weekends in ('BUS 4290', 'BUS 2494'):  # footnote 3
            self.assertIn(weekends, buses)
        self.assertEqual(times(buses['BUS 2494']), ['18:52', '18:59', '19:04', '19:09'])

    def test_one_train_two_notices(self):
        # LP 4290 on Sunday: Lesce Bled - Jesenice (11248), then Jesenice - Vintgar (11056).
        plan = build('20261018')
        train = trip_id('20261018', 'LP 4290')
        mine = sorted((b for b in plan['buses'] if b.get('trainTripId') == train), key=lambda b: b['departures'][0])
        self.assertEqual([(names(b)[0], names(b)[-1]) for b in mine], [('Lesce-Bled', 'Jesenice'), ('Jesenice', 'Vintgar')])
        self.assertEqual(len({b['id'] for b in mine}), 2)


class MondayTests(SimpleTestCase):
    def test_on_the_day_footnote_98_names_the_trains_run(self):
        plan = build('20261019')  # Monday 19 October, notice 11198
        buses = timetabled(plan)
        sections = closures.sections(plan['buses'])
        for number in ('2400', '2402', '2401', '2403'):  # footnote 98 (and the extra buses with it)
            self.assertNotIn(f'BUS {number}', buses)
            train = trip_id('20261019', f'LPV {number}')
            self.assertNotIn(train, sections)
            self.assertFalse([b for b in plan['buses'] if b.get('trainTripId') == train])
        self.assertEqual(times(buses['BUS 316'])[:2], ['09:35', '09:44'])
        self.assertEqual(names(buses['BUS 415']), ['Jesenice', 'Lesce-Bled', 'Kranj', 'Ljubljana'])

    @staticmethod
    def next_day_plan() -> dict:
        """Tuesday 20 October: Monday's trains a day later, as a day plan."""
        trips = [{**t, 'serviceDay': t['serviceDay'] + 86400, 'arrivals': [x + 86400 for x in t['arrivals']],
                  'departures': [x + 86400 for x in t['departures']], 'scheduledArrivals': [x + 86400 for x in t['arrivals']],
                  'scheduledDepartures': [x + 86400 for x in t['departures']]} for t in feed('20261019')]
        with mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]):
            built = closures.plan(trips, {}, ALERTS, [], {}, stop_index(trips), TABLES)
        by_trip = {}
        for t in trips:
            by_trip.setdefault(t['id'], []).append(t)
        return {'buses': built['buses'], 'synthetic': built['buses'], 'by_id': {b['id']: b for b in built['buses']},
                'sections': closures.sections(built['buses']), 'trips': by_trip, 'suppressed': built['suppressed']}

    def test_the_day_after_the_buses_run(self):
        plan = self.next_day_plan()
        buses = timetabled(plan)
        self.assertEqual(times(buses['BUS 2400'])[:3], ['04:40', '04:49', '04:52'])
        self.assertEqual(names(buses['BUS 2402'])[0], 'Ljubljana')
        # The red columns: extra buses on their own lines, replacing no train (the starred one on workdays).
        extra = [b for b in plan['buses'] if b.get('source') == 'timetable' and b.get('additional')]
        self.assertEqual(sorted((names(b)[0], names(b)[-1]) for b in extra), [('Škofja Loka', 'Jesenice'), ('Škofja Loka', 'Ljubljana')])
        self.assertTrue(all(b['trainTripId'] is None and b['route']['gtfsId'] != closures.synthetic_line_id('IJPP:63756') for b in extra))
        self.assertNotIn(None, closures.sections(plan['buses']))


class SaturdayTests(SimpleTestCase):
    def test_bus_4292_runs_and_4208_does_not(self):
        plan = build('20261017')  # Saturday 17 October, notice 11056
        buses = timetabled(plan)
        self.assertEqual((names(buses['BUS 4292']), times(buses['BUS 4292'])), (['Vintgar', 'Kočna', 'Jesenice'], ['09:23', '09:25', '09:31']))
        self.assertNotIn('BUS 4208', buses)  # footnote 2
        # The feed has train 4292 twice that day: both are replaced.
        sections = closures.sections(plan['buses'])
        self.assertEqual({t['id'] for t in feed('20261017') if t['route']['shortName'] == '4292'} - set(sections), set())


def feed_bus(name, stations, at, step=420):
    """A feed bus (BUS nnnnn of the SŽ agency) through the stations of the 14 October snapshot."""
    known = {s['name']: s for t in feed('20261014') for s in t['stops']}
    base = epoch('2026-10-14')
    start = epoch('2026-10-14', at)
    stamps = [start + i * step for i in range(len(stations))]
    return {'id': f'IJPP:feed-{name}', 'route': {'gtfsId': f'IJPP:r-{name}', 'shortName': name, 'mode': 'BUS', 'agency': SZ},
            'pattern': 'p', 'headsign': None, 'serviceDay': base, 'stops': [known[n] for n in stations],
            'arrivals': stamps, 'departures': stamps, 'delays': [None] * len(stations),
            'scheduledArrivals': stamps, 'scheduledDepartures': stamps}


BUS_24009 = feed_bus('BUS 24009', ['Lesce-Bled', 'Žirovnica', 'Slovenski Javornik', 'Jesenice'], '05:41', step=300)


class PrecedenceTests(SimpleTestCase):
    def setUp(self):
        closures._told.clear()  # each difference is told once per process

    def test_the_timetables_bus_wins_over_the_feeds_and_the_difference_is_logged(self):
        bus = BUS_24009
        with self.assertLogs('prestop_api.closures', 'INFO') as logs:
            plan = build('20261014', extra=[bus])
        mine = timetabled(plan)['BUS 2400']
        self.assertEqual(plan['suppressed'].get(bus['id']), mine['id'])
        train = trip_id('20261014', 'LPV 2400')
        self.assertEqual([s['busTripId'] for s in closures.sections(plan['buses'])[train]], [mine['id']])
        said = '\n'.join(logs.output)
        self.assertIn('2400', said)
        self.assertIn('05:41', said)
        self.assertIn('05:40', said)

    def test_an_unsure_timetable_is_used_for_its_good_columns_only(self):
        # Ljubljana - Logatec: the feed has the buses itself; the timetable is unsure ("17::00" in 26639).
        plan = build('20261014')
        by_name = {t['route']['shortName']: t['id'] for t in feed('20261014') if t['route']['mode'] == 'BUS'}
        buses = timetabled(plan)
        self.assertEqual(plan['suppressed'][by_name['BUS 26729']], buses['BUS 26729']['id'])
        self.assertEqual(buses['BUS 26729']['trainName'], 'LPV 2672')
        self.assertNotIn(by_name['BUS 26639'], plan['suppressed'])
        self.assertNotIn('BUS 26639', buses)
        # Its train (2663) keeps the feed's buses altogether: the timetable's picture of it is incomplete.
        self.assertNotIn(by_name['BUS 26638'], plan['suppressed'])
        self.assertNotIn('BUS 26638', buses)

    def test_a_failed_or_missing_timetable_changes_nothing(self):
        failed = sztimetables.Timetables(TABLES.notices, {sha: {**f, 'status': 'failed'} for sha, f in TABLES.files.items()})
        for tables in (failed, None, sztimetables.Timetables({}, {})):
            plan = build('20261014', tables=tables)
            self.assertFalse(timetabled(plan))
            self.assertEqual(plan['suppressed'], {})
            old = build('20261014', tables=None)
            self.assertEqual([b['id'] for b in plan['buses']], [b['id'] for b in old['buses']])


class DayPlanTests(SimpleTestCase):
    """scheduled.day_plan: the timetables' buses in a service day's plan, refreshed in the background."""

    def derive(self, slot, trips, tables, **kwargs):
        if getattr(self, '_trips', None) is not trips:  # the inputs as the caches hold them: the same objects until reloaded
            self._trips, self._loaded = trips, ([], [], {}, stop_index(trips))
        loaded = self._loaded
        with mock.patch.object(closures, 'inputs', return_value=loaded),                 mock.patch.object(closures.mapping, 'build_alerts', return_value=ALERTS),                 mock.patch.object(sztimetables, 'current', return_value=tables),                 mock.patch('prestop_api.stopfix.replacement_stops', return_value=[]):
            return scheduled._derive_into(slot, trips, **kwargs)

    def test_a_plan_has_the_timetables_buses_instead_of_the_feeds(self):
        trips = feed('20261014') + [BUS_24009]
        slot = self.derive({'key': None}, trips, TABLES)
        train = trip_id('20261014', 'LPV 2400')
        mine = next(b for b in slot['synthetic'] if b['route']['shortName'] == 'BUS 2400')
        self.assertEqual([s['busTripId'] for s in slot['sections'][train]], [mine['id']])
        self.assertEqual(slot['suppressed'][BUS_24009['id']], mine['id'])
        self.assertIs(slot['by_id'][mine['id']], mine)

    def test_new_timetables_reach_todays_plan_in_the_background(self):
        trips = feed('20261014')
        slot = self.derive({'key': None}, trips, None)
        self.assertFalse([b for b in slot['synthetic'] if b.get('source') == 'timetable'])
        # A request does not rebuild the plan for new timetables (the warmer does, warm.plans) ...
        self.derive(slot, trips, TABLES, defer_timetables=True)
        self.assertFalse([b for b in slot['synthetic'] if b.get('source') == 'timetable'])
        # ... but anything else that changed rebuilds it with them.
        self.derive(slot, list(trips), TABLES, defer_timetables=True)
        self.assertTrue([b for b in slot['synthetic'] if b.get('source') == 'timetable'])
        slot = self.derive({'key': None}, trips, None)
        self.derive(slot, trips, TABLES)
        self.assertTrue([b for b in slot['synthetic'] if b.get('source') == 'timetable'])

    def test_the_warmer_reads_new_timetables_and_rebuilds_todays_and_tomorrows_plans(self):
        today = datetime(2026, 10, 14).date()
        with mock.patch.object(sztimetables, 'load') as load, mock.patch.object(scheduled, 'day_plan') as day_plan,                 mock.patch.object(scheduled, 'service_day', return_value=today):
            warm.plans()
        load.assert_called_once()
        self.assertEqual([(c.args[0], c.kwargs.get('refresh')) for c in day_plan.call_args_list],
                         [(today, True), (today.replace(day=15), True)])


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self


def plan_for(day: str, extra=()) -> dict:
    """A day plan (scheduled.day_plan) of the snapshot's trips with the fixture timetables."""
    trips = feed(day) + list(extra)
    return DayPlanTests().derive({'key': None}, trips, TABLES)


class MapTests(SimpleTestCase):
    def shown(self, derived, at):
        trips = [t for runs in derived['trips'].values() for t in runs]
        with mock.patch.object(scheduled, 'timetable', _Value(trips)), mock.patch.object(scheduled, 'shapes', _Value({})),                 mock.patch.object(scheduled, '_derive', return_value=derived), mock.patch.object(scheduled, '_road_shape', return_value=None):
            return {v['tripId'] for v in scheduled.vehicles(now=epoch('2026-10-14', at), live={})}

    def test_the_timetables_bus_is_drawn_and_not_the_feeds_or_the_train(self):
        derived = plan_for('20261014', [BUS_24009])
        mine = next(b['id'] for b in derived['synthetic'] if b['route']['shortName'] == 'BUS 2400')
        shown = self.shown(derived, '05:45')
        self.assertIn(mine, shown)
        self.assertNotIn(BUS_24009['id'], shown)
        self.assertNotIn(trip_id('20261014', 'LPV 2400'), shown)
        self.assertIn(trip_id('20261014', 'LPV 2400'), self.shown(derived, '05:20'))  # still a train before Lesce Bled

    def test_a_split_train_stays_hidden_on_its_whole_replaced_stretch(self):
        # At 08:40 train 318's timetable has it between Lesce Bled and Jesenice, where it does not run that day,
        # though its buses 318/1 and 318/3 are already at Jesenice.
        derived = plan_for('20261014')
        self.assertNotIn(trip_id('20261014', 'RG 318'), self.shown(derived, '08:40'))
        self.assertIn(trip_id('20261014', 'RG 318'), self.shown(derived, '07:20'))  # Dobova - Ljubljana by train


def board_row(trip: dict, station: str, kind: str = 'departure') -> dict:
    """A board row (mapping.build_board) of `trip` at `station`."""
    i = next(n for n, s in enumerate(trip['stops']) if s['name'] == station)
    at = trip['departures'][i] if kind == 'departure' else trip['arrivals'][i]
    end = trip['stops'][-1] if kind == 'departure' else trip['stops'][0]
    row = {'id': f'{trip["id"]}@{trip["serviceDay"]}/{i}', 'stopId': trip['stops'][i]['gtfsId'], 'tripId': trip['id'],
           'routeId': trip['route']['gtfsId'], 'operatorId': 'IJPP:1161', 'routeName': trip['route']['shortName'],
           'mode': 'rail' if trip['route']['mode'] == 'RAIL' else 'bus', 'destination': end['name'], 'scheduledAt': mapping.iso(at),
           'effectiveAt': None, 'updatedAt': None, 'quality': None, 'canceled': False, 'platform': None, 'alertIds': []}
    if trip['route']['mode'] != 'RAIL':
        row['replacement'] = True
    return row


class BoardTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = plan_for('20261014', [BUS_24009])
        cls.trips = {t['route']['shortName']: t for t in feed('20261014') + [BUS_24009]}
        cls.names = {s['gtfsId']: s['name'] for t in cls.trips.values() for s in t['stops']}
        cls.ids = {name: sid for sid, name in cls.names.items()}

    def board(self, station, kind, frm, to, entries):
        return replacement.board_rows(entries, kind, self.names, lambda when: self.plan, stop_ids=[self.ids[station]],
                                      start=epoch('2026-10-14', frm), end=epoch('2026-10-14', to))

    def at(self, row):
        return datetime.fromisoformat(row['scheduledAt'].replace('Z', '+00:00')).astimezone(LOCAL).strftime('%H:%M')

    def test_the_train_leaves_lesce_bled_as_its_bus_and_the_feeds_bus_is_gone(self):
        rows = self.board('Lesce-Bled', 'departure', '05:00', '06:00',
                          [board_row(self.trips['LPV 2400'], 'Lesce-Bled'), board_row(BUS_24009, 'Lesce-Bled')])
        self.assertEqual([(r['routeName'], self.at(r), r['destination'], r.get('replacesTrain')) for r in rows],
                         [('BUS 2400', '05:40', 'Jesenice', 'LPV 2400')])
        [row] = rows
        self.assertEqual((row['mode'], row['replacement'], row['stopId'], row['tripId']),
                         ('bus', True, self.ids['Lesce-Bled'], next(b['id'] for b in self.plan['synthetic'] if b['route']['shortName'] == 'BUS 2400')))
        # It still arrives there as a train.
        rows = self.board('Lesce-Bled', 'arrival', '05:00', '06:00', [board_row(self.trips['LPV 2400'], 'Lesce-Bled', 'arrival')])
        # (with the buses from Jesenice that end there: 2441 and 2403)
        self.assertEqual([(r['routeName'], self.at(r)) for r in rows], [('BUS 2441', '05:12'), ('LPV 2400', '05:37'), ('BUS 2403', '05:44')])

    def test_each_of_a_trains_buses_has_its_own_row(self):
        train = self.trips['RG 318']
        rows = self.board('Ljubljana', 'departure', '07:30', '08:00', [board_row(train, 'Ljubljana')])
        self.assertEqual(sorted((r['routeName'], self.at(r), r['destination']) for r in rows),
                         [('BUS 318/1', '07:42', 'Jesenice'), ('BUS 318/2', '07:42', 'Lesce-Bled')])
        rows = self.board('Kranj', 'departure', '07:30', '08:30', [board_row(train, 'Kranj')])
        self.assertEqual([(r['routeName'], self.at(r), r['destination']) for r in rows],
                         [('BUS 415', '07:45', 'Ljubljana'), ('BUS 318/3', '07:47', 'Jesenice'), ('BUS 318/2', '08:22', 'Lesce-Bled')])
        rows = self.board('Kranj', 'arrival', '07:30', '08:30', [board_row(train, 'Kranj', 'arrival')])
        self.assertEqual([(r['routeName'], self.at(r), r['destination']) for r in rows],
                         [('BUS 415', '07:45', 'Jesenice'), ('BUS 318/2', '08:22', 'Ljubljana')])
        # Arriving in Ljubljana from Dobova it is a train.
        rows = self.board('Ljubljana', 'arrival', '07:30', '08:00', [board_row(train, 'Ljubljana', 'arrival')])
        self.assertEqual([(r['routeName'], r['mode']) for r in rows], [('RG 318', 'rail')])

    def test_buses_outside_the_boards_time_are_left_out(self):
        rows = self.board('Kranj', 'departure', '07:50', '08:30', [board_row(self.trips['RG 318'], 'Kranj')])
        self.assertEqual([r['routeName'] for r in rows], ['BUS 318/2'])

    def test_an_extra_bus_replaces_no_train(self):
        plan = MondayTests.next_day_plan()
        names = {s['gtfsId']: s['name'] for b in plan['synthetic'] for s in b['stops']}
        loka = next(i for i, n in names.items() if n == 'Škofja Loka')
        start = epoch('2026-10-20', '06:00')
        rows = replacement.board_rows([], 'departure', names, lambda when: plan, stop_ids=[loka], start=start, end=start + 3600)
        extra = [r for r in rows if r['routeName'] == 'BUS 2402' and self.at(r) == '06:31']
        self.assertEqual(len(extra), 1)
        self.assertNotIn('replacesTrain', extra[0])
        self.assertEqual(extra[0]['destination'], 'Jesenice')


class StationBoardTests(SimpleTestCase):
    def test_a_station_board_lists_the_timetable_buses_leaving_before_the_train_would(self):
        # Kranj at 07:40: the train 318 row (08:14) is all OTP lists for it; its bus 318/3 leaves at 07:47.
        plan = plan_for('20261014')
        train = next(t for t in feed('20261014') if t['route']['shortName'] == 'RG 318')
        kranj = next(s['gtfsId'] for s in train['stops'] if s['name'] == 'Kranj')
        names = {s['gtfsId']: s['name'] for s in train['stops']}
        with mock.patch.object(sources, '_member_board', return_value=[board_row(train, 'Kranj')]), \
                mock.patch.object(sources, 'alerts', return_value=[]), mock.patch.object(sources, 'stop_group', return_value=[kranj]), \
                mock.patch.object(sources, 'stop_names', return_value=names), mock.patch.object(scheduled, 'plan_at', return_value=plan):
            rows = sources.board(kranj, 'departure', int(epoch('2026-10-14', '07:40')), 'sl')
        self.assertEqual([r['routeName'] for r in rows[:3]], ['BUS 415', 'BUS 318/3', 'BUS 318/2'])


def leg_on(trip: dict, frm: str, to: str) -> dict:
    """A built leg (journeys.build_journeys) riding `trip` from station `frm` to `to`."""
    names = [s['name'] for s in trip['stops']]
    return otp_leg(trip, names.index(frm), names.index(to))


def walk(to_leg: dict, seconds: int = 300, before: bool = True) -> dict:
    """A walk leg ending where (and when) `to_leg` starts, or starting where it ends."""
    at = to_leg['origin'] if before else to_leg['destination']
    edge = datetime.fromisoformat(to_leg['scheduledDeparture'] if before else to_leg['scheduledArrival']).timestamp()
    start, end = (edge - seconds, edge) if before else (edge, edge + seconds)
    stamp = lambda e: datetime.fromtimestamp(e, LOCAL).isoformat()  # noqa: E731
    return {'id': 'leg:x-w', 'mode': 'walk', 'operatorId': None, 'routeId': None, 'tripId': None, 'routeName': '', 'headsign': None,
            'origin': {**at, 'name': 'Doma'} if before else at, 'destination': at if before else {**at, 'name': 'Doma'},
            'scheduledDeparture': stamp(start), 'scheduledArrival': stamp(end), 'effectiveDeparture': stamp(start), 'effectiveArrival': stamp(end),
            'geometry': [[at['longitude'], at['latitude']]] * 2, 'delaySeconds': None, 'delayProvenance': None, 'canceled': False, 'alertIds': []}


WALK = {'transit': False, 'interline': False, 'duration': 300, 'realtime': False, 'platform': None}


def hhmm(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(LOCAL).strftime('%H:%M')


def rides(legs: list[dict]) -> list[tuple]:
    return [(l['routeName'], l['origin']['name'], hhmm(l['effectiveDeparture']), l['destination']['name'], hhmm(l['effectiveArrival']))
            for l in legs if l['mode'] != 'walk']


ROAD = lambda stops: {'coords': [[s['lon'], s['lat']] for s in stops], 'complete': True}  # noqa: E731


class JourneyTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = plan_for('20261014', [BUS_24009])
        cls.trips = {t['route']['shortName']: t for t in feed('20261014')}

    def rewrite(self, legs, metas, plan=None):
        plan = plan or self.plan
        return journey_legs.rewrite(legs, metas, lambda when: plan, ROAD)

    def test_ljubljana_to_jesenice_on_318_rides_its_first_bus(self):
        legs, meta = self.rewrite([leg_on(self.trips['RG 318'], 'Ljubljana', 'Jesenice')], [META])
        self.assertEqual(rides(legs), [('BUS 318/1', 'Ljubljana', '07:42', 'Jesenice', '08:32')])
        self.assertEqual((legs[0]['replacement'], legs[0]['replacesTrain'], legs[0]['mode']), (True, 'RG 318', 'bus'))

    def test_ljubljana_to_lesce_bled_on_318_rides_its_second_bus(self):
        legs, _ = self.rewrite([leg_on(self.trips['RG 318'], 'Ljubljana', 'Lesce-Bled')], [META])
        self.assertEqual(rides(legs), [('BUS 318/2', 'Ljubljana', '07:42', 'Lesce-Bled', '08:47')])

    def test_from_dobova_the_train_then_the_bus(self):
        legs, meta = self.rewrite([leg_on(self.trips['RG 318'], 'Dobova', 'Jesenice')], [META])
        self.assertEqual(rides(legs), [('RG 318', 'Dobova', '05:41', 'Ljubljana', '07:37'), ('BUS 318/1', 'Ljubljana', '07:42', 'Jesenice', '08:32')])
        self.assertEqual([m.get('held') for m in meta], [False, True])

    def test_train_2400_to_lesce_bled_then_its_bus(self):
        legs, _ = self.rewrite([leg_on(self.trips['LPV 2400'], 'Ljubljana', 'Jesenice')], [META])
        self.assertEqual(rides(legs), [('LPV 2400', 'Ljubljana', '04:40', 'Lesce-Bled', '05:37'),
                                       ('BUS 2400', 'Lesce-Bled', '05:40', 'Jesenice', '05:57')])

    def test_a_bus_leaving_before_the_train_would_moves_the_walk_to_it(self):
        ride = leg_on(self.trips['RG 318'], 'Kranj', 'Jesenice')  # the train would leave Kranj at 08:14
        legs, meta = self.rewrite([walk(ride), ride], [WALK, META])
        self.assertEqual(rides(legs), [('BUS 318/3', 'Kranj', '07:47', 'Jesenice', '08:32')])
        self.assertEqual((legs[0]['mode'], hhmm(legs[0]['effectiveArrival']), hhmm(legs[0]['effectiveDeparture'])), ('walk', '07:47', '07:42'))

    def test_a_bus_that_left_before_the_rider_arrives_leaves_the_leg_as_planned(self):
        ride = leg_on(self.trips['RG 318'], 'Kranj', 'Jesenice')
        before = leg_on(self.trips['LPV 2442'], 'Ljubljana Stegne', 'Kranj')  # arrives in Kranj at 09:22
        before = {**before, 'effectiveArrival': ride['effectiveDeparture'], 'scheduledArrival': ride['scheduledDeparture']}
        legs, _ = self.rewrite([before, ride], [META, META])
        self.assertEqual([l['routeName'] for l in legs], ['LPV 2442', 'RG 318'])

    def test_two_buses_of_one_train_change_where_they_meet(self):
        # 318 without its direct bus, and 318/3 leaving Kranj before 318/2 comes but Lesce Bled after it.
        tables = copy.deepcopy(TABLES.files)
        lesce = tables[next(iter(sha for sha in tables if '11248' in tables[sha]['notices']))]
        cols = lesce['tables'][0]['columns']
        cols[:] = [c for c in cols if c['label'] != '318/1']
        third = next(c for c in cols if c['label'] == '318/3')
        third['calls'] = [{'station': 'KRANJ', 'dep': '08:20'}, {'station': 'LESCE BLED', 'arr': '08:50', 'dep': '08:50'}, {'station': 'JESENICE', 'arr': '09:10'}]
        trips = feed('20261014')
        plan = DayPlanTests().derive({'key': None}, trips, sztimetables.Timetables(TABLES.notices, tables))
        legs, meta = self.rewrite([leg_on(self.trips['RG 318'], 'Ljubljana', 'Jesenice')], [META], plan)
        self.assertEqual(rides(legs), [('BUS 318/2', 'Ljubljana', '07:42', 'Lesce-Bled', '08:47'),
                                       ('BUS 318/3', 'Lesce-Bled', '08:50', 'Jesenice', '09:10')])
        self.assertFalse(meta[1].get('held'))  # a change between two buses is a real one

    def test_a_feed_bus_leg_rides_the_timetables_bus_instead(self):
        planned = {**leg_on(BUS_24009, 'Lesce-Bled', 'Jesenice'), 'mode': 'bus', 'replacement': True}
        legs, _ = self.rewrite([planned], [META])
        self.assertEqual(rides(legs), [('BUS 2400', 'Lesce-Bled', '05:40', 'Jesenice', '05:57')])
        self.assertEqual(legs[0]['tripId'], next(b['id'] for b in self.plan['synthetic'] if b['route']['shortName'] == 'BUS 2400'))

    def test_a_running_train_loses_the_notice_its_timetable_does_not_replace_it_by(self):
        ride = leg_on(self.trips['LPV 2442'], 'Ljubljana Šiška', 'Kranj')
        notice = next(a for a in ALERTS if closures.notice_id(a) == '11147')
        ride['alertIds'] = [notice['id']]
        journey_legs.unreplaced_notices([ride], lambda when: self.plan, {a['id']: a for a in ALERTS})
        self.assertEqual(ride['alertIds'], [])
        replaced = leg_on(self.trips['LPV 2400'], 'Ljubljana', 'Jesenice')
        replaced['alertIds'] = [notice['id']]
        journey_legs.unreplaced_notices([replaced], lambda when: self.plan, {a['id']: a for a in ALERTS})
        self.assertEqual(replaced['alertIds'], [notice['id']])

    def test_walks_to_the_replacement_stop_follow(self):
        legs, meta = self.rewrite([leg_on(self.trips['RG 318'], 'Ljubljana', 'Jesenice')], [META])
        walked, _ = journeys.replacement_walks(legs, meta)
        self.assertTrue(all('_boardAt' not in l and '_alightAt' not in l for l in walked))


class LineAndTripTests(SimpleTestCase):
    def test_the_line_of_a_trains_buses_has_each_bus_as_a_variant(self):
        plan = plan_for('20261014')
        route = closures.synthetic_line_id('IJPP:64427')  # RG 318
        road = {'coords': [[14.5, 46.05], [14.1, 46.4]], 'cum': [0, 1], 'distances': [0, 1, 2, 3], 'complete': True}
        with mock.patch.object(scheduled, 'day_plan', return_value=plan), mock.patch.object(scheduled, '_road_shape', return_value=road):
            line = scheduled.synthetic_line(route, datetime(2026, 10, 14).date())
        self.assertEqual((line['name'], line['replacesTrain'], line['replacement']), ('BUS 318', 'RG 318', True))
        self.assertEqual(sorted((p['stops'][0]['name'], p['stops'][-1]['name']) for p in line['patterns']),
                         [('Kranj', 'Jesenice'), ('Ljubljana', 'Jesenice'), ('Ljubljana', 'Lesce-Bled')])

    def test_a_trip_page_tells_where_the_bus_leaves_earlier_than_published(self):
        plan = MondayTests.next_day_plan()  # 20 October, notice 11198
        bus = next(b for b in plan['synthetic'] if b['route']['shortName'] == 'BUS 316')
        with mock.patch.object(scheduled, 'synthetic_bus', return_value=bus), mock.patch.object(scheduled, '_road_shape', return_value=None):
            entry = scheduled.synthetic_entry(bus['id'])
        podnart = next(s for s in entry['static']['stops'] if s['name'] == 'Podnart')
        self.assertIn('5 minut pred objavljenim voznim redom', podnart['note'])
        self.assertNotIn('note', next(s for s in entry['static']['stops'] if s['name'] == 'Kranj'))


class UntimedNoticeTests(SimpleTestCase):
    def test_a_notice_without_a_timetable_guesses_but_not_for_trains_a_timetable_replaces(self):
        plan = build('20261014', alerts=ALERTS + UNTIMED)
        guessed = {b['trainName'] for b in plan['buses'] if b.get('source') != 'timetable'}
        self.assertIn('LPV 2442', guessed)       # 99001: Ljubljana Šiška - Kranj, no timetable
        self.assertNotIn('LPV 2400', guessed)    # 99002 would, but its timetable bus Lesce Bled - Jesenice decides it
        self.assertNotIn('RG 318', guessed)

    def test_the_report_says_where_each_notices_buses_come_from(self):
        plan = build('20261014', alerts=ALERTS + UNTIMED)
        rows = {r['notice']: r for r in closures.report(plan, ALERTS + UNTIMED, '20261014')}
        self.assertEqual(rows['11248']['source'], 'timetable (ok)')
        self.assertEqual(rows['10088']['source'], 'timetable (unsure)')
        self.assertEqual(rows['99001']['source'], 'guessed')
        self.assertNotIn('11198', rows)  # not in effect on the 14th
        by_train = {}
        for bus in rows['11248']['buses']:
            by_train.setdefault(bus['train'], []).append(bus)
        self.assertEqual([(b['bus'], b['from'], b['to'], b['departs'], b['arrives']) for b in by_train['RG 318']],
                         [('BUS 318/1', 'Ljubljana', 'Jesenice', '07:42', '08:32'), ('BUS 318/2', 'Ljubljana', 'Lesce-Bled', '07:42', '08:47'),
                          ('BUS 318/3', 'Kranj', 'Jesenice', '07:47', '08:32')])
        # 28 feed buses; 26639 (an unreadable cell) and 26638 (the other bus of the same train, 2663) stay.
        self.assertEqual(rows['10088']['feedBusesReplaced'], 26)
        text = closures.format_report(closures.report(plan, ALERTS + UNTIMED, '20261014'))
        self.assertIn('BUS 318/2', text)
        self.assertIn('11248', text)

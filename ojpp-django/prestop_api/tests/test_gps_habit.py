from datetime import date, timedelta
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import gps_habit, mapping, scheduled

DAY = 1795474800  # 2026-11-24 00:00 Ljubljana
ARRIVA, LESCE, A6345 = 'IJPP:arriva', 'IJPP:67295', 'IJPP:67252'


MARPROM, M6, LPP_COPY = 'MARPROM:mp', 'MARPROM:6', 'IJPP:LPP-25'
START = date(2026, 11, 10)  # the 14 days before 24 Nov


def trips(route, days, starts):
    return [(route, START + timedelta(days=d), s) for d in days for s in starts]


# Arriva: A6345 sent live data for all its trips every day; A6343 to Lesce ŽP only on 5 and 6 Nov (before the window).
# Marprom's line 6 every day, but each trip only every other day (only some buses have GPS). LPP's copy never.
LIVE = trips(A6345, range(14), [6 * 3600, 7 * 3600, 8 * 3600]) +     [(M6, START + timedelta(days=d), s) for d in range(14) for s in (6 * 3600, 7 * 3600) if (d + s // 3600) % 2]
OPERATORS = {A6345: ARRIVA, LESCE: ARRIVA, M6: MARPROM, LPP_COPY: 'IJPP:lpp'}
KNOWN = gps_habit.learn((LIVE), OPERATORS, {A6345, LESCE, M6})


def stoptime(trip, route, operator, start, dep, realtime=False):
    return {'serviceDay': DAY, 'scheduledArrival': dep, 'scheduledDeparture': dep, 'realtimeArrival': dep,
            'realtimeDeparture': dep, 'realtime': realtime, 'realtimeState': 'UPDATED' if realtime else 'SCHEDULED',
            'stopPosition': 0, 'pickupType': 'SCHEDULED', 'dropoffType': 'SCHEDULED', 'stop': {'platformCode': None},
            'trip': {'gtfsId': trip, 'route': {'gtfsId': route, 'shortName': 'A6343', 'mode': 'BUS', 'agency': {'gtfsId': operator}},
                     'departureStoptime': {'stop': {'gtfsId': 'IJPP:ap'}, 'scheduledDeparture': start},
                     'arrivalStoptime': {'stop': {'gtfsId': 'IJPP:lesce', 'name': 'Lesce ŽP'}}}}


class LearnTests(SimpleTestCase):
    def test_a_rarely_live_line_of_a_steady_operator_is_expected_live(self):
        self.assertIn(ARRIVA, KNOWN['operators'])
        self.assertIn(A6345, KNOWN['steady'])
        self.assertIn(LESCE, KNOWN['rare'])
        self.assertTrue(gps_habit.expects_live(ARRIVA, LESCE, KNOWN))
        self.assertTrue(gps_habit.expects_live(ARRIVA, A6345, KNOWN))

    def test_a_line_where_only_some_buses_send_live_data_is_never_marked(self):
        self.assertIn(M6, KNOWN['partial'])
        self.assertNotIn(MARPROM, KNOWN['operators'])
        self.assertFalse(gps_habit.expects_live(MARPROM, M6, KNOWN))

    def test_a_line_never_live_keeps_its_timetable_whatever_its_operator(self):
        self.assertFalse(gps_habit.expects_live(ARRIVA, LPP_COPY, KNOWN))
        self.assertFalse(gps_habit.expects_live('SEVNICA:1', 'SEVNICA:r', KNOWN))

    def test_a_steady_line_counts_whatever_its_operator(self):
        known = gps_habit.learn((trips('X:r', range(5), [3600])), {}, set())
        self.assertTrue(gps_habit.expects_live('X:other', 'X:r', known))
        thin = gps_habit.learn((trips('X:s', range(4), [3600])), {'X:s': 'X:o'}, set())
        self.assertFalse(gps_habit.expects_live('X:o', 'X:s', thin))  # too few days, and no steady operator

    def test_weekend_trips_are_judged_against_weekend_days(self):
        weekdays = [d for d in range(14) if (START + timedelta(days=d)).weekday() < 5]
        weekend = [d for d in range(14) if d not in weekdays]
        known = gps_habit.learn((trips('X:r', weekdays, [3600]) + trips('X:r', weekend, [9 * 3600])), {}, set())
        self.assertIn('X:r', known['steady'])

    def test_hours_without_any_live_trip_of_the_line_do_not_count_as_missing(self):
        # the collector was down every afternoon but the first five days: the 16:00 trip is still steady
        gappy = trips('X:r', range(14), [7 * 3600]) + trips('X:r', range(5), [16 * 3600])
        self.assertIn('X:r', gps_habit.learn(gappy, {}, set())['steady'])

    def test_no_live_data_waits_for_the_grace_after_its_first_departure(self):
        start = DAY + 8 * 3600 + 45 * 60
        self.assertFalse(gps_habit.no_live_data(ARRIVA, LESCE, start, False, start + 60, KNOWN))
        self.assertTrue(gps_habit.no_live_data(ARRIVA, LESCE, start, False, start + gps_habit.GRACE, KNOWN))
        self.assertFalse(gps_habit.no_live_data(ARRIVA, LESCE, start, True, start + 3600, KNOWN))
        self.assertFalse(gps_habit.no_live_data('SEVNICA:1', 'SEVNICA:r', start, False, start + 3600, KNOWN))
        self.assertFalse(gps_habit.no_live_data(ARRIVA, LESCE, None, False, start + 3600, KNOWN))

    def test_without_a_database_nobody_is_marked(self):
        gps_habit.reset()
        with mock.patch.object(gps_habit, 'learn_from_db', side_effect=RuntimeError('no database')):
            self.assertEqual(gps_habit.habit(DAY), gps_habit.empty())
        gps_habit.reset()


@override_settings(GHOST_TRIPS='mark')
class BoardTests(SimpleTestCase):
    """24 Nov 2026: A6343 08:45 Ljubljana AP → Lesce ŽP on the AP's departures board, no live data, did not run."""

    def board(self, now, *stoptimes, **kw):
        with mock.patch.object(gps_habit, 'habit', return_value=KNOWN), mock.patch.object(mapping.time, 'time', return_value=now):
            return {r['tripId']: r for r in mapping.build_board('IJPP:ap', stoptimes, 'departure', [], **kw)}

    def test_the_lesce_bus_is_marked_once_it_should_have_left(self):
        dep = 8 * 3600 + 45 * 60
        ghost = stoptime('IJPP:488252', LESCE, ARRIVA, dep, dep)
        self.assertNotIn('noLiveData', self.board(DAY + dep - 600, ghost)['IJPP:488252'])  # before it leaves: as listed
        self.assertTrue(self.board(DAY + dep + 6 * 60, ghost)['IJPP:488252']['noLiveData'])

    def test_a_trip_with_live_data_or_of_a_never_live_line_is_not_marked(self):
        dep = 8 * 3600
        live = stoptime('IJPP:a6345', A6345, ARRIVA, dep, dep, realtime=True)
        town = stoptime('SEVNICA:t', 'SEVNICA:r', 'SEVNICA:1', dep, dep)
        board = self.board(DAY + dep + 3600, live, town)
        self.assertNotIn('noLiveData', board['IJPP:a6345'])
        self.assertNotIn('noLiveData', board['SEVNICA:t'])

    def test_updates_without_a_believable_time_still_count_as_live_data(self):
        dep = 8 * 3600
        quiet = stoptime('IJPP:x', LESCE, ARRIVA, dep, dep)
        board = self.board(DAY + dep + 3600, quiet, updates={'IJPP:x': {}})
        self.assertNotIn('noLiveData', board['IJPP:x'])


@override_settings(GHOST_TRIPS='mark')
class CityBusTests(SimpleTestCase):
    def test_a_timetable_run_of_a_live_operator_without_live_data_is_not_drawn(self):
        now = DAY + 9 * 3600
        run = {'id': 'K:1', 'route': {'gtfsId': A6345, 'agency': {'gtfsId': ARRIVA}}, 'headsign': '', 'shapeKey': 'k', 'shape': [],
               'stops': [{'gtfsId': 'K:a', 'lat': 46.0, 'lon': 14.0, 'name': 'A'}, {'gtfsId': 'K:b', 'lat': 46.1, 'lon': 14.1, 'name': 'B'}],
               'departures': [now - 600, now + 600], 'arrivals': [now - 600, now + 600]}
        drops = []
        with mock.patch.object(gps_habit, 'habit', return_value=KNOWN), \
                mock.patch('prestop_api.supplement.timetable_runs', return_value=[run]):
            self.assertEqual(scheduled.city_buses(now, drops=drops), [])
        self.assertEqual([d['reason'] for d in drops], ['no live data from a live operator'])


# ---------------------------------------------------------------- listed trips that rarely run (part 5)
D0 = date(2026, 10, 27)  # a Tuesday; 28 days of history to 23 Nov
WEEKDAYS = [D0 + timedelta(days=i) for i in range(28) if (D0 + timedelta(days=i)).weekday() < 5]
RUN_DAYS = {date(2026, 11, 5), date(2026, 11, 6)}
# SŽ's full closure Ljubljana – Jesenice ran 2–6 Nov; A6343 ran only on two of those days.
CLOSED = {(ARRIVA, 'A6343'): {date(2026, 11, 2) + timedelta(days=i) for i in range(5)}}
NEW = 'IJPP:67714'


def row(route, operator, name, start, dates, direction=0):
    return {'route': route, 'operator': operator, 'name': name, 'direction': direction, 'start': start, 'dates': set(dates)}


def history(extra=()):
    """Arriva's A6345 runs 08:30 / 13:00 every weekday; A6343 (08:45) only on RUN_DAYS; Marprom's 6 half the days."""
    seen, live = {}, {}
    for d in WEEKDAYS:
        seen[(A6345, d)] = [8 * 3600 + 1800, 13 * 3600]
        if d in RUN_DAYS:
            seen[(LESCE, d)] = [8 * 3600 + 2700]
        if d.day % 2:
            seen[(M6, d)] = [8 * 3600]
    for (route, d), v in [*seen.items(), *extra]:
        op = {A6345: ARRIVA, LESCE: ARRIVA, NEW: ARRIVA, M6: MARPROM}[route]
        live.setdefault((op, d), []).extend(v)
    for v in live.values():
        v.sort()
    return seen, live


LISTED = [row(LESCE, ARRIVA, 'A6343', 8 * 3600 + 2700, WEEKDAYS), row(A6345, ARRIVA, 'A6345', 8 * 3600 + 1800, WEEKDAYS),
          row(M6, MARPROM, '6', 8 * 3600, WEEKDAYS), row(LPP_COPY, 'IJPP:lpp', '25', 8 * 3600, WEEKDAYS)]
EVER = {(ARRIVA, 'A6343'), (ARRIVA, 'A6345'), (MARPROM, '6'), ('IJPP:lpp', '25')}
# Marprom is not steady (part 4's learn), so it is not passed among the operators judged.
OPS = {ARRIVA, 'IJPP:lpp'}


class RarelyRunsTests(SimpleTestCase):
    def judged(self, listed=LISTED, seen_live=None, closed=CLOSED):
        seen, live = seen_live or history()
        ran = gps_habit.ran_ever(listed, seen, WEEKDAYS[0], WEEKDAYS[-1])
        return gps_habit.judge(gps_habit.learn_slots(listed, seen, live, OPS, EVER, WEEKDAYS[0], WEEKDAYS[-1], closed=closed), ran)

    def test_a6343_without_its_closure_days_is_only_irregular(self):
        # Prod backtest 25 Nov: its two runs (5–6 Nov) in ~14 observable weekdays give 0.14–0.17, above GHOST_RATE.
        judged = self.judged(closed=None)
        monday = date(2026, 11, 24)
        self.assertEqual(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, monday), 'irregular')

    def test_on_a_closure_day_a_ghost_is_shown_as_irregular(self):
        judged = self.judged()
        self.assertEqual(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, date(2026, 11, 24), CLOSED), 'ghost')
        self.assertEqual(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, date(2026, 11, 5), CLOSED), 'irregular')

    def test_a6343_is_a_ghost_before_it_leaves_and_a6345_is_not(self):
        judged = self.judged()
        monday = date(2026, 11, 24)
        self.assertEqual(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, monday), 'ghost')
        self.assertEqual(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2760, monday), 'ghost')  # ± SLOP
        self.assertIsNone(gps_habit.verdict(judged, ARRIVA, 'A6345', 0, 8 * 3600 + 1800, monday))
        self.assertIsNone(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, date(2026, 11, 28)))  # Saturday

    def test_a_renumbered_route_keeps_its_history(self):
        judged = self.judged()  # learned on IJPP:67295; the 1 Dec feed lists the same trip as IJPP:67714
        rows = gps_habit.listing({'gtfsId': NEW, 'shortName': 'A6343', 'agency': {'gtfsId': ARRIVA}, 'patterns': [
            {'directionId': 0, 'trips': [{'activeDates': ['20261201'], 'departureStoptime': {'scheduledDeparture': 8 * 3600 + 2700}}]}]})
        t = rows[0]
        self.assertEqual(gps_habit.verdict(judged, t['operator'], t['name'], t['direction'], t['start'], date(2026, 12, 1)), 'ghost')

    def test_a_closure_on_the_rail_between_a_lines_ends_gives_its_closed_days(self):
        # SŽ's full closure Ljubljana – Jesenice / Beljak, 2–6 Nov: Lesce Bled lies on it only through the trains' stops.
        alert = {'kind': 'replacement', 'title': 'Vozni red nadomestnega prevoza: Ljubljana - Jesenice / Beljak (A) in obratno '
                                                 '(2. - 6. november).', '_dates': [f'202611{d:02}' for d in range(2, 7)]}
        train = {'stops': [{'name': n} for n in ('Ljubljana', 'Ljubljana Šiška', 'Kranj', 'Lesce-Bled', 'Žirovnica', 'Jesenice')]}
        other = {'kind': 'replacement', 'title': 'Vozni red nadomestnega prevoza: Divača - Koper in obratno (9. november).',
                 '_dates': ['20261109']}
        extra = {'kind': 'replacement', 'title': 'DODATNO: Avtobusni prevoz za vezo (NG - LJ): Lesce Bled - Bled Jezero',
                 '_dates': ['20261124']}
        sections = gps_habit.closure_sections([alert, other, extra], [train])
        self.assertEqual(len(sections), 1)  # Divača – Koper has no train here, the connecting bus is no closure
        route = {'gtfsId': LESCE, 'shortName': 'A6343', 'agency': {'gtfsId': ARRIVA}, 'patterns': [
            {'directionId': 0, 'stops': [{'name': 'Ljubljana AP'}, {'name': 'Kranj AP'}, {'name': 'Lesce ŽP'}],
             'trips': [{'activeDates': ['20261105'], 'departureStoptime': {'scheduledDeparture': 8 * 3600 + 2700}}]}]}
        koper = {'gtfsId': A6345, 'shortName': 'A1000', 'agency': {'gtfsId': ARRIVA}, 'patterns': [
            {'directionId': 0, 'stops': [{'name': 'Ljubljana AP'}, {'name': 'Koper AP'}],
             'trips': [{'activeDates': ['20261105'], 'departureStoptime': {'scheduledDeparture': 9 * 3600}}]}]}
        closed = gps_habit.closed_lines(gps_habit.listing(route) + gps_habit.listing(koper), sections)
        self.assertEqual(closed, {(ARRIVA, 'A6343'): {date(2026, 11, d) for d in range(2, 7)}})
        self.assertEqual(gps_habit.stop_key('Ljubljana AP'), 'ljubljana')
        self.assertFalse(gps_habit.on_corridor('Ljubljana Šiška', {'ljubljana'}))

    def test_closure_days_are_stored_merged_and_pruned_and_long_closures_left_out(self):
        import json
        import tempfile
        from pathlib import Path
        train = {'stops': [{'name': n} for n in ('Ljubljana', 'Kranj', 'Lesce-Bled', 'Jesenice')]}
        works = {'kind': 'replacement', 'title': 'Vozni red nadomestnega prevoza: Ljubljana - Jesenice in obratno (2. - 6. november).',
                 '_dates': [f'202611{d:02}' for d in range(2, 7)]}
        standing = {'kind': 'replacement', 'title': 'Vozni red nadomestnega prevoza: Kranj - Jesenice in obratno (do 12. decembra).',
                    '_dates': [(date(2026, 1, 1) + timedelta(days=i)).strftime('%Y%m%d') for i in range(40)]}
        sections = gps_habit.closure_sections([works, standing], [train])
        self.assertEqual(len(sections), 1)  # 40 days of a standing closure: how the line runs, not ghost days
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'ghost.json')
            old = [(sections[0][0], {date(2026, 9, 1)})]  # older than LONG days: dropped
            gps_habit.save_closures(old, path, date(2026, 9, 2))
            self.assertEqual(gps_habit.save_closures(sections, path, date(2026, 11, 25)), 1)
            later = [(sections[0][0], {date(2026, 11, 20)})]
            gps_habit.save_closures(later, path, date(2026, 11, 26))
            stored = gps_habit._sections_from(json.loads(Path(path).read_text(encoding='utf-8')))
            self.assertEqual(stored, [(sections[0][0], {date(2026, 11, d) for d in (2, 3, 4, 5, 6, 20)})])
            Path(path).write_text('not json', encoding='utf-8')
            gps_habit.load_closures(path)  # an unreadable file is no closure days, not an error

    def test_the_shipped_seed_excuses_a6343_on_its_closure_run_days(self):
        # Seeded (--seed) from local copies of SŽ's list and zamudil's daily notices: SŽ's full closure Ljubljana –
        # Jesenice 2–6 Nov, when A6343 ran.
        with override_settings(PRESTOP_GHOST_FILE=''):
            sections = gps_habit.load_closures()
        route = {'gtfsId': LESCE, 'shortName': 'A6343', 'agency': {'gtfsId': ARRIVA}, 'patterns': [
            {'directionId': 0, 'stops': [{'name': 'Ljubljana AP'}, {'name': 'Lesce ŽP'}],
             'trips': [{'activeDates': ['20261105'], 'departureStoptime': {'scheduledDeparture': 8 * 3600 + 2700}}]}]}
        days = gps_habit.closed_lines(gps_habit.listing(route), sections)[(ARRIVA, 'A6343')]
        self.assertTrue({date(2026, 11, 5), date(2026, 11, 6)} <= days)
        self.assertFalse({date(2026, 11, d) for d in range(12, 25)} & days)  # its quiet weekdays stay judged
        self.assertTrue(all(len(d) <= gps_habit.MAX_CLOSURE for _, d in sections))

    def test_notices_read_from_saved_copies(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            listed, daily = Path(tmp) / 'notices.json', Path(tmp) / 'notices-2026-11-03.json'
            listed.write_text(json.dumps({'data': [{'id': '11307', 'from': '2026-11-07', 'to': '2026-11-11', 'text': '',
                                                     'title': 'Vozni red nadomestnega prevoza: Lesce Bled - Jesenice in obratno (7. - 11. november).'}]}), encoding='utf-8')
            daily.write_text(json.dumps({'data': {'serviceDate': '2026-11-03', 'notices': [
                {'summary': 'Vozni red nadomestnega prevoza: Ljubljana - Jesenice / Beljak (A) in obratno (2. - 6. november).'},
                {'summary': 'Povezava: [Vozni red nadomestnega prevoza](https://example.invalid/x.pdf)'}]}}), encoding='utf-8')
            alerts = gps_habit.notices_from_files([listed, daily])
        from prestop_api import closures
        self.assertEqual([sorted(closures._days(a)) for a in alerts],
                         [[f'202611{d:02}' for d in range(7, 12)], [f'202611{d:02}' for d in range(2, 7)]])
        self.assertTrue(all(closures.is_closure(a) for a in alerts))

    def test_a_trip_running_on_some_days_is_irregular(self):
        seen, live = history()
        for d in WEEKDAYS[::2]:
            if d not in RUN_DAYS:
                seen[(LESCE, d)] = [8 * 3600 + 2700]
                live[(ARRIVA, d)] = sorted(live[(ARRIVA, d)] + [8 * 3600 + 2700])
        judged = self.judged(seen_live=(seen, live))
        self.assertEqual(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, date(2026, 11, 24)), 'irregular')

    def test_partial_operators_copies_and_never_live_lines_are_never_judged(self):
        judged = self.judged()
        self.assertFalse([k for k in judged if k[0] in (MARPROM, 'IJPP:lpp')])
        seen, live = history()
        slots = gps_habit.learn_slots(LISTED, seen, live, OPS | {MARPROM}, EVER - {(ARRIVA, 'A6343')}, WEEKDAYS[0], WEEKDAYS[-1])
        self.assertNotIn((ARRIVA, 'A6343', 0, 'w'), slots)

    def test_rule_a_a_slot_never_seen_live_itself_is_never_judged(self):
        # A6343's 14:30 is listed every weekday but never seen live (say a subcontractor's bus without GPS): kept,
        # although its 08:45 (seen on 5–6 Nov) is a ghost and Arriva is steady.
        judged = self.judged(listed=LISTED + [row(LESCE, ARRIVA, 'A6343', 14 * 3600 + 1800, WEEKDAYS)])
        monday = date(2026, 11, 24)
        self.assertEqual(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, monday), 'ghost')
        self.assertIsNone(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 14 * 3600 + 1800, monday))

    def test_rules_b_and_c_replacement_buses_town_feeds_and_lpp_copies_are_never_judged(self):
        # Each is listed every weekday, seen live once (on 5 Nov) under a steady operator: a ghost by its numbers.
        lines = [('Ptuj:1', ARRIVA, '1'), ('Postojna:3', 'IJPP:nomago', '3'), ('Sevnica:2', ARRIVA, '2'),
                 ('Brezice:1', ARRIVA, '1'), ('IJPP:27501', 'IJPP:1161', 'BUS 27501'), ('IJPP:9', ARRIVA, 'BUS 27503'),
                 (LPP_COPY, ARRIVA, '25'), (LESCE, ARRIVA, 'A6343')]
        seen, live = history()
        for route, op, _ in lines:
            seen[(route, date(2026, 11, 5))] = [10 * 3600]
        for d in WEEKDAYS:
            for op in (ARRIVA, 'IJPP:nomago', 'IJPP:1161'):
                live[(op, d)] = sorted(live.get((op, d), []) + [10 * 3600 + 600, 10 * 3600 + 1200])
        listed = [row(r, op, name, 10 * 3600, WEEKDAYS) for r, op, name in lines] + [LISTED[1]]  # + A6345, matched daily
        ever = {(op, name) for _, op, name in lines}
        slots = gps_habit.learn_slots(listed, seen, live, {ARRIVA, 'IJPP:nomago', 'IJPP:1161'}, ever, WEEKDAYS[0], WEEKDAYS[-1],
                                      closed=CLOSED)
        judged = gps_habit.judge(slots, gps_habit.ran_ever(listed, seen, WEEKDAYS[0], WEEKDAYS[-1]))
        self.assertEqual([k[1] for k in judged], ['A6343'])  # the control: the same numbers on a national Arriva line
        for route, op, name in lines[:-1]:
            self.assertFalse(gps_habit.judgeable(route, op, name), route)

    def test_days_the_operator_sent_nothing_do_not_count(self):
        seen, live = history()
        for d in WEEKDAYS[:-3]:  # collector down all day but the last three weekdays
            live.pop((ARRIVA, d), None)
            seen.pop((A6345, d), None)
        judged = self.judged(seen_live=(seen, live))
        self.assertIsNone(gps_habit.verdict(judged, ARRIVA, 'A6343', 0, 8 * 3600 + 2700, date(2026, 11, 24)))  # 3 < MIN_OBSERVABLE

    def test_days_most_of_the_operators_trips_were_not_matched_do_not_count(self):
        # Prod before 10 Nov: Marprom's live buses were matched to ~10 % of its weekday trips (one line a day here),
        # from then on to all; every slot then looked rarely run, and 489 of 499 hidden on 16 Nov ran.
        names = [f'G{i}' for i in range(10)]
        listed = [row(f'MARPROM:{i}', MARPROM, n, 8 * 3600 + 600 * i, WEEKDAYS) for i, n in enumerate(names)]
        seen, live = {}, {}
        for j, d in enumerate(WEEKDAYS):
            for i in range(10):
                if j >= len(WEEKDAYS) - 5 or i == j % 10:
                    seen[(f'MARPROM:{i}', d)] = [8 * 3600 + 600 * i]
            live[(MARPROM, d)] = sorted(s for (_, day), v in seen.items() if day == d for s in v)
        ever = {(MARPROM, n) for n in names}

        def judged():
            slots = gps_habit.learn_slots(listed, seen, live, {MARPROM}, ever, WEEKDAYS[0], WEEKDAYS[-1])
            return gps_habit.judge(slots, gps_habit.ran_ever(listed, seen, WEEKDAYS[0], WEEKDAYS[-1]))

        with mock.patch.object(gps_habit, 'DAY_SHARE', 0):
            self.assertTrue(judged())  # the old rule: the poorly matched days count as missed runs
        self.assertEqual(judged(), {})  # only the 5 well-matched weekdays count: < MIN_OBSERVABLE, nothing judged
        counts = gps_habit.matched(listed, seen, WEEKDAYS[0], WEEKDAYS[-1])
        self.assertFalse(gps_habit.observed(counts, MARPROM, 'G0', WEEKDAYS[0]))
        self.assertTrue(gps_habit.observed(counts, MARPROM, 'G0', WEEKDAYS[-1]))

    def test_backtest_counts_hidden_and_ran_anyway_without_look_ahead(self):
        operator_of = {A6345: ARRIVA, LESCE: ARRIVA, M6: MARPROM}
        seen, live = history()
        # from 11 Nov: history starts 27 Oct and closure days 2–6 Nov do not count, so 10 Nov has 5 < MIN_OBSERVABLE
        nov = [d for d in WEEKDAYS if d >= date(2026, 11, 11)]
        listed = [row(LESCE, ARRIVA, 'A6343', 8 * 3600 + 2700, WEEKDAYS), row(A6345, ARRIVA, 'A6345', 8 * 3600 + 1800, WEEKDAYS)]
        with mock.patch.object(gps_habit, 'learn', return_value={'operators': frozenset({ARRIVA})}):
            result = gps_habit.backtest(date(2026, 11, 24), 14, listed, (seen, live, operator_of), closed=CLOSED)
        self.assertEqual(result['hidden'], len(nov))  # A6343 hidden on every quiet weekday 11–21 Nov
        self.assertEqual(result['ranAnyway'], 0)
        self.assertEqual([x['line'] for x in result['lines']], [f'{ARRIVA} A6343'])
        self.assertEqual(result['lines'][0]['days'], [d.isoformat() for d in nov])
        self.assertLessEqual(result['lines'][0]['rate'], gps_habit.GHOST_RATE)
        with mock.patch.object(gps_habit, 'learn', return_value={'operators': frozenset({ARRIVA})}):
            self.assertEqual(gps_habit.backtest(date(2026, 11, 24), 14, listed, (seen, live, operator_of))['hidden'], 0)

    def test_switch_defaults_to_off(self):
        self.assertEqual(gps_habit.ghost_mode(), 'off')
        with self.settings(GHOST_TRIPS='hide'):
            self.assertEqual(gps_habit.ghost_mode(), 'hide')
        with self.settings(GHOST_TRIPS='bogus'):
            self.assertEqual(gps_habit.ghost_mode(), 'off')

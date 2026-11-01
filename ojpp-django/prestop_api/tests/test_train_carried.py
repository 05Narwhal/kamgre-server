"""The delay of the train before (spec 2026-10-31 H8, trainlive.carried_delay): a train whose set comes from a late
train (a `sure` stay, train_stays.py) leaves late by that delay less the slack in the turn; its own report and SŽ's
forecast for it come first; it chains through `sure` stays only; the map, boards and journeys show the same value."""
from datetime import timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from prestop_api import mapping, predictions, trainlive
from prestop_api.tests.test_train_live import T0, board_row, plan_of, trip, update
from prestop_statistics import train_stays
from prestop_statistics.models import TripDelay

# LPV 3293 Jesenice 09:40 -> Kranj 10:10; LPV 3295 Kranj 10:20 -> Ljubljana 10:50; LPV 3294 Ljubljana 11:00 -> Kranj
C = trip('3293', 'LPV 3293', ['Jesenice', 'Kranj'], [T0 - 2400, T0 - 600])
A = trip('3295', 'LPV 3295', ['Kranj', 'Ljubljana'], [T0, T0 + 1800])
B = trip('3294', 'LPV 3294', ['Ljubljana', 'Kranj'], [T0 + 2400, T0 + 4200])
DAY = T0 - 36_000  # their service day's midnight
LINKS = {'3294': {'from_number': '3295', 'arrival': T0 + 1800 - DAY, 'slack': 360, 'level': 'sure'},
         '3295': {'from_number': '3293', 'arrival': T0 - 600 - DAY, 'slack': 0, 'level': 'sure'}}
PLAN = plan_of([C, A, B])


class links:
    """The learned `sure` stays of LINKS, for sure_link_to and the boards' and journeys' quick look (comes_from)."""

    def __init__(self, table=LINKS):
        self.patches = [mock.patch.object(train_stays, 'sure_link_to', side_effect=lambda number, day: table.get(number)),
                        mock.patch.object(train_stays, 'comes_from', side_effect=lambda number: table.get(number))]

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class Carried(SimpleTestCase):
    def live(self, train, updates, now=T0 + 600):
        with links(), mock.patch.object(trainlive.time, 'time', return_value=now):
            return trainlive.of(PLAN, train, updates, {})

    def test_late_train_before_makes_it_leave_late_less_the_slack(self):
        got = self.live(B, update(A, 'Ljubljana', 900))
        self.assertEqual(got['delays'][0], 540)  # 15 min - 6 min slack
        self.assertEqual((got['kind'], got['source']), ('predicted', 'gtfs-rt'))  # said "expected", like SŽ's forecast

    def test_its_own_report_comes_first(self):
        updates = {**update(A, 'Ljubljana', 900), **update(B, 'Kranj', 120)}
        got = self.live(B, updates)
        self.assertEqual(got['delays'][1], 120)
        self.assertEqual(got['kind'], 'actual')

    def test_slack_absorbs_a_small_delay(self):
        self.assertIsNone(self.live(B, update(A, 'Ljubljana', 300)))  # 5 min late, 6 min slack: on time

    def test_never_earlier_than_the_timetable(self):
        self.assertIsNone(self.live(B, update(A, 'Ljubljana', -120)))

    def test_chains_through_sure_stays(self):
        got = self.live(B, update(C, 'Kranj', 1500))
        self.assertEqual(got['delays'][0], 1140)  # 25 min, 0 slack at Kranj, then 6 min at Ljubljana

    def test_a_likely_stay_carries_nothing(self):
        stay = {'from_number': '3295', 'to_number': '3294', 'station': 'IJPP:Ljubljana', 'station_name': 'Ljubljana', 'level': 'likely',
                'arrival': T0 + 1800 - DAY, 'departure': T0 + 2400 - DAY, 'slack': 360}
        with mock.patch.object(train_stays, 'comes_from', return_value=stay), mock.patch.object(train_stays, 'holds', return_value=True):
            self.assertIsNone(train_stays.sure_link_to('3294', None))
        with mock.patch.object(train_stays, 'comes_from', return_value={**stay, 'level': 'sure'}), mock.patch.object(train_stays, 'holds', return_value=True):
            self.assertEqual(train_stays.sure_link_to('3294', None)['from_number'], '3295')

    def test_only_within_three_hours(self):
        self.assertIsNone(self.live(B, update(A, 'Ljubljana', 900), now=T0 + 2400 - 3 * 3600 - 60))

    def test_board_row_and_journey_leg(self):
        with links(), mock.patch('prestop_api.scheduled.plan_at', return_value=PLAN), \
                mock.patch.object(trainlive, 'trip_updates', return_value=update(A, 'Ljubljana', 900)), \
                mock.patch('prestop_api.sz.reports', return_value={}), mock.patch.object(trainlive.time, 'time', return_value=T0 + 600):
            row = trainlive.carried_rows([board_row(B, 0)])[0]
            leg = {'mode': 'rail', 'tripId': B['id'], 'routeId': B['route']['gtfsId'], 'routeName': 'LPV 3294', 'scheduledDeparture': mapping.iso(T0 + 2400),
                   'delaySeconds': None, 'canceled': False}
            raw = {'end': {'scheduledTime': mapping.iso(T0 + 4200)}, 'trip': {}}
            with override_settings(PRESTOP_PREDICTIONS=True):
                predicted = predictions.predict_leg(leg, raw, now=T0 + 600)
        self.assertEqual(row['effectiveAt'], mapping.iso(T0 + 2400 + 540))
        self.assertEqual((row['delayKind'], row['quality']), ('predicted', 'predicted'))
        self.assertEqual(predicted, (540, 'previous-trip'))

    def test_boards_touch_no_plan_without_a_sure_stay(self):
        with mock.patch('prestop_api.scheduled.plan_at') as plan_at, \
                mock.patch.object(train_stays, 'comes_from', return_value={'level': 'likely', 'from_number': '3295'}):
            row = board_row(B, 0)
            self.assertIs(trainlive.carried_rows([row])[0], row)
        plan_at.assert_not_called()


class Held(SimpleTestCase):
    """I11: A reaches its turn station and drops out of SŽ's feeds, so its delay comes from what the collector stored,
    until B reports itself or 15 min past B's timetable departure."""
    AFTER_A = T0 + 1900  # A is in (10:50), B leaves at 11:00

    def live(self, train=B, stored=None, updates=None, now=AFTER_A, plan=PLAN):
        stored = {A['id']: ({'1': 240, '2': 900}, T0 + 1800)} if stored is None else stored
        with links(), mock.patch.object(trainlive, '_stored_delays', return_value=stored), mock.patch.object(trainlive.time, 'time', return_value=now):
            return trainlive.of(plan, train, updates or {}, {})

    def test_a_dropped_out_and_its_last_delay_is_held(self):
        got = self.live()
        self.assertEqual(got['delays'][0], 540)  # 15 min - 6 min slack, as while A was still reported
        self.assertEqual((got['kind'], got['source'], got['at']), ('predicted', 'gtfs-rt', T0 + 1800))

    def test_nothing_stored_nothing_carried(self):
        self.assertIsNone(self.live(stored={}))

    def test_expires_15_min_after_b_should_have_left(self):
        leaves = T0 + 2400
        self.assertEqual(self.live(now=leaves + 900)['delays'][0], 540)
        self.assertIsNone(self.live(now=leaves + 901))

    def test_b_reporting_itself_ends_it(self):
        got = self.live(updates=update(B, 'Kranj', 120))
        self.assertEqual(got['delays'][1], 120)
        self.assertEqual(got['kind'], 'actual')

    def test_a_still_reported_beats_what_was_stored(self):
        self.assertEqual(self.live(updates=update(A, 'Ljubljana', 1200))['delays'][0], 840)  # 20 min - 6 min, not the stored 15

    def test_slack_absorbs_a_small_held_delay(self):
        self.assertIsNone(self.live(stored={A['id']: ({'2': 300}, T0 + 1800)}))  # 5 min late, 6 min slack

    def test_never_earlier_than_the_timetable(self):
        self.assertIsNone(self.live(stored={A['id']: ({'2': -240}, T0 + 1800)}))

    def test_a_likely_stay_holds_nothing(self):
        stay = {**LINKS['3294'], 'level': 'likely'}
        stored = mock.Mock(return_value={A['id']: ({'2': 900}, T0 + 1800)})
        with mock.patch.object(train_stays, 'comes_from', return_value=stay), mock.patch.object(train_stays, 'holds', return_value=True), \
                mock.patch.object(trainlive, '_stored_delays', stored), mock.patch.object(trainlive.time, 'time', return_value=self.AFTER_A):
            self.assertIsNone(trainlive.of(PLAN, B, {}, {}))
        stored.assert_not_called()

    def test_a_train_lost_far_from_its_end_holds_nothing(self):
        far = trip('3295', 'LPV 3295', ['Jesenice', 'Lesce-Bled', 'Podnart', 'Kranj', 'Ljubljana'], [T0 + 450 * k for k in range(4)] + [T0 + 1800])
        plan = plan_of([C, far, B])
        self.assertIsNone(self.live(stored={far['id']: ({'1': 900, '2': 900}, T0)}, plan=plan))  # Lesce-Bled is not near its end
        self.assertEqual(self.live(stored={far['id']: ({'1': 60, '3': 900}, T0)}, plan=plan)['delays'][0], 540)  # Podnart is

    def test_a_numbering_it_cannot_read_holds_nothing(self):
        self.assertIsNone(self.live(stored={A['id']: ({'12': 900}, T0 + 1800)}))
        self.assertIsNone(self.live(stored={A['id']: ({'0': 900}, T0 + 1800)}))

    def test_holds_through_a_chain_of_sure_stays(self):
        got = self.live(stored={C['id']: ({'2': 1500}, T0 - 600)}, now=T0 + 600)  # C is in at Kranj, A has said nothing yet
        self.assertEqual(got['delays'][0], 1140)

    def test_map_board_and_journey_say_the_same(self):
        stored = {A['id']: ({'2': 900}, T0 + 1800)}
        for now in (self.AFTER_A, T0 + 2400 + 600):  # before B's time, and past it with B still not reported
            with links(), mock.patch('prestop_api.scheduled.plan_at', return_value=PLAN), mock.patch.object(trainlive, 'trip_updates', return_value={}), \
                    mock.patch('prestop_api.sz.reports', return_value={}), mock.patch.object(trainlive, '_stored_delays', return_value=stored), \
                    mock.patch.object(trainlive.time, 'time', return_value=now):
                seen = trainlive.of(PLAN, B)['delays'][0]
                row = trainlive.carried_rows([board_row(B, 0)])[0]
                leg = {'mode': 'rail', 'tripId': B['id'], 'routeId': B['route']['gtfsId'], 'routeName': 'LPV 3294', 'scheduledDeparture': mapping.iso(T0 + 2400),
                       'delaySeconds': None, 'canceled': False}
                raw = {'end': {'scheduledTime': mapping.iso(T0 + 4200)}, 'trip': {}}
                with override_settings(PRESTOP_PREDICTIONS=True):
                    predicted = predictions.predict_leg(leg, raw, now=now)
            self.assertEqual(seen, 540)
            self.assertEqual(row['effectiveAt'], mapping.iso(T0 + 2400 + 540))
            self.assertEqual(predicted, (540, 'previous-trip'))


class HeldStorage(TestCase):
    """I11: one read for all trains however many rows ask (47454d5 fixed per-row work on boards once)."""

    def setUp(self):
        trainlive._held.clear()
        self.addCleanup(trainlive._held.clear)
        table = {'from': {'3295': {'level': 'sure'}, '3293': {'level': 'sure'}, '3294': {'level': 'likely'}}, 'to': {}}
        patch = mock.patch.object(train_stays, 'table', return_value=table)
        patch.start()
        self.addCleanup(patch.stop)
        self.day = trainlive._service_date(A)

    def row(self, run, delays, day=None, canceled=False):
        seen = timezone.now()
        TripDelay.objects.create(service_date=day or self.day, trip_id=run['id'], route_id='IJPP:r', operator_id='IJPP:sz', direction='0', stop_delays=delays,
                                 canceled=canceled, first_seen=seen, last_seen=seen)

    def test_one_read_for_all_rows(self):
        self.row(A, {'2': 900})
        self.row(C, {'2': 60})
        with self.assertNumQueries(1):
            for _ in range(5):
                self.assertEqual(trainlive.held_delay(PLAN, A)[0], 900)
                self.assertEqual(trainlive.held_delay(PLAN, C)[0], 60)

    def test_only_trains_with_a_sure_stay_after_them_are_read(self):
        self.row(B, {'2': 900})  # 3294 only has a `likely` stay after it
        self.assertIsNone(trainlive.held_delay(PLAN, B))

    def test_a_canceled_train_or_another_day_holds_nothing(self):
        self.row(A, {'2': 900}, canceled=True)
        self.row(C, {'2': 900}, day=self.day - timedelta(days=1))
        self.assertIsNone(trainlive.held_delay(PLAN, A))
        self.assertIsNone(trainlive.held_delay(PLAN, C))

    def test_a_failed_read_is_nothing_held_and_is_not_retried_on_every_row(self):
        with mock.patch.object(TripDelay.objects, 'filter', side_effect=RuntimeError('down')) as read:
            self.assertIsNone(trainlive.held_delay(PLAN, A))
            self.assertIsNone(trainlive.held_delay(PLAN, A))
        self.assertEqual(read.call_count, 1)


class Shown(SimpleTestCase):
    """H9: journeys and the train page."""

    def legs(self, walk_end='IJPP:Ljubljana'):
        prev = {'mode': 'rail', 'routeName': 'LPV 3295', 'routeId': 'IJPP:r', 'tripId': A['id'], 'operatorId': 'IJPP:1161',
                'destination': {'stopId': walk_end, 'name': 'Ljubljana'}}
        leg = {'mode': 'rail', 'routeName': 'LPV 3294', 'routeId': 'IJPP:r', 'tripId': B['id'], 'operatorId': 'IJPP:1161',
               'origin': {'stopId': 'IJPP:Ljubljana', 'name': 'Ljubljana'}, 'scheduledDeparture': mapping.iso(T0 + 2400)}
        return prev, leg

    @override_settings(PRESTOP_PREDICTIONS=True)
    def test_two_rail_legs_of_one_set_are_a_stay_without_a_new_ticket(self):
        prev, leg = self.legs()
        with mock.patch.object(train_stays, 'journey_level', return_value='sure') as level, mock.patch('prestop_api.sources.stop_group', return_value=[]):
            self.assertEqual(predictions.stay_level(prev, {}, leg, {}, 0), 'sure')
        self.assertEqual(level.call_args.args[:2], ('3295', '3294'))
        self.assertEqual(predictions.ticket_note(prev, leg, None), 'none')  # SŽ: a ticket is for the relation

    @override_settings(PRESTOP_PREDICTIONS=True)
    def test_another_station_or_a_walk_is_a_change(self):
        prev, leg = self.legs(walk_end='IJPP:Kranj')
        prev['destination']['name'] = 'Kranj'
        with mock.patch.object(train_stays, 'journey_level', return_value='sure'), mock.patch('prestop_api.sources.stop_group', return_value=[]):
            self.assertIsNone(predictions.stay_level(prev, {}, leg, {}, 0))
            prev, leg = self.legs()
            self.assertIsNone(predictions.stay_level(prev, {}, leg, {}, 300))  # five minutes' walk

    def test_train_page_times_as_timestamps(self):
        from prestop_api import trains
        found = {'continuesAs': {'number': '3294', 'name': 'LPV 3294', 'station': 'Ljubljana', 'departure': 40_000, 'destination': 'Kranj',
                                 'level': 'sure', 'kind': 'continues'}}
        with mock.patch.object(train_stays, 'links_of', return_value=found):
            got = trains.stay_links('3295', None, {'serviceDay': DAY})
        self.assertEqual(got['continuesAs']['departure'], mapping.iso(DAY + 40_000))
        found = {'comesFrom': {'number': '3295', 'name': 'LPV 3295', 'station': 'Ljubljana', 'arrival': T0 + 1800 - DAY, 'level': 'sure', 'kind': 'continues'}}
        with mock.patch.object(train_stays, 'links_of', return_value=found),                 mock.patch.object(trainlive, 'carried_for_trip', return_value={'delay': 540, 'source': 'sz', 'at': 0, 'from': '3295'}) as carried:
            got = trains.stay_links('3294', None, B)
        self.assertEqual(got['comesFrom']['delaySeconds'], 540)  # as the board says it
        self.assertEqual(carried.call_args.args, (B['id'], T0 + 2400))
        with mock.patch.object(train_stays, 'links_of', side_effect=RuntimeError('down')):
            self.assertEqual(trains.stay_links('3295', None, {'serviceDay': DAY}), {})  # the page stands without it


class Replaced(SimpleTestCase):
    """A bus running part of either train: not the same set going on (seen locally on 31 Oct: BUS 2427 after RG 18)."""

    def test_no_carried_delay_onto_a_replaced_train(self):
        from prestop_api.tests.test_train_live import timetable_bus
        bus = timetable_bus(B, [T0 + 2400, T0 + 4800], stations=['Ljubljana', 'Kranj'], label='32949')
        plan = plan_of([C, A, B], [bus])
        with links(), mock.patch.object(trainlive.time, 'time', return_value=T0 + 600):
            self.assertIsNone(trainlive.carried_delay(plan, B, update(A, 'Ljubljana', 900), {}))
            self.assertEqual(trainlive.carried_delay(PLAN, B, update(A, 'Ljubljana', 900), {})['delay'], 540)

    def test_a_learned_stay_does_not_hold_on_a_replaced_day(self):
        from prestop_api.tests.test_train_live import timetable_bus
        stay = {'from_number': '3295', 'to_number': '3294', 'station': B['stops'][0]['gtfsId'], 'station_name': 'Ljubljana',
                'arrival': T0 + 1800 - DAY, 'departure': T0 + 2400 - DAY}
        runs = {n: {'trip': t['id'], 'stops': [{'id': s['gtfsId'], 'name': s['name'], 'arr': a - DAY, 'dep': a - DAY} for s, a in zip(t['stops'], t['arrivals'])]}
                for n, t in (('3295', A), ('3294', B))}
        bus = timetable_bus(B, [T0 + 2400, T0 + 4800], stations=['Ljubljana', 'Kranj'], label='32949')
        with mock.patch('prestop_api.zamudil.class_of', return_value=None):
            with mock.patch('prestop_api.scheduled.day_plan', return_value=PLAN):
                self.assertTrue(train_stays.holds(stay, None, runs))
            with mock.patch('prestop_api.scheduled.day_plan', return_value=plan_of([C, A, B], [bus])):
                self.assertFalse(train_stays.holds(stay, None, runs))

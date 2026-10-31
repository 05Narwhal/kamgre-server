"""The delay of the train before (spec 2026-10-31 H8, trainlive.carried_delay): a train whose set comes from a late
train (a `sure` stay, train_stays.py) leaves late by that delay less the slack in the turn; its own report and SŽ's
forecast for it come first; it chains through `sure` stays only; the map, boards and journeys show the same value."""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import mapping, predictions, trainlive
from prestop_api.tests.test_train_live import T0, board_row, plan_of, trip, update
from prestop_statistics import train_stays

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

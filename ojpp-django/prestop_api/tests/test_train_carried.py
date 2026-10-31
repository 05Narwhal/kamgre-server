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


def links(table=LINKS):
    return mock.patch.object(train_stays, 'sure_link_to', side_effect=lambda number, day: table.get(number))


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
            leg = {'mode': 'rail', 'tripId': B['id'], 'routeId': B['route']['gtfsId'], 'scheduledDeparture': mapping.iso(T0 + 2400),
                   'delaySeconds': None, 'canceled': False}
            raw = {'end': {'scheduledTime': mapping.iso(T0 + 4200)}, 'trip': {}}
            with override_settings(PRESTOP_PREDICTIONS=True):
                predicted = predictions.predict_leg(leg, raw, now=T0 + 600)
        self.assertEqual(row['effectiveAt'], mapping.iso(T0 + 2400 + 540))
        self.assertEqual((row['delayKind'], row['quality']), ('predicted', 'predicted'))
        self.assertEqual(predicted, (540, 'previous-trip'))

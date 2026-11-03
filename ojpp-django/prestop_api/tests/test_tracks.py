import time
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import tracks

LJ = 'IJPP:1122804'


def rows(train, stop, *days_tracks):
    return [{'train_id': train, 'ijpp_id': stop, 'platform': track, 'date': day} for day, track in days_tracks]


class UsualTrackTests(SimpleTestCase):
    def test_a_track_the_train_keeps_is_its_usual_one(self):
        usual = tracks.usual_tracks(rows('2606', LJ, ('d1', '11-A'), ('d2', '11-A'), ('d3', '11-A'), ('d4', '11-A'), ('d5', '9')))
        self.assertEqual(usual, {'2606': {LJ: '11-A'}})

    def test_a_train_that_changes_track_has_none(self):
        self.assertEqual(tracks.usual_tracks(rows('518', LJ, ('d1', '3'), ('d2', '4'), ('d3', '3'), ('d4', '4'))), {})

    def test_too_few_days_give_none(self):
        self.assertEqual(tracks.usual_tracks(rows('518', LJ, ('d1', '3'), ('d2', '3'))), {})

    def test_empty_tracks_are_not_observations(self):
        self.assertEqual(tracks.usual_tracks(rows('518', LJ, ('d1', ''), ('d2', ''), ('d3', '3'))), {})


class TrackTests(SimpleTestCase):
    def setUp(self):
        self.t = tracks.Tracks()
        self.t.usual = lambda: {'2606': {LJ: '11-A'}}

    def test_announced_track_wins_today(self):
        with mock.patch.object(self.t, 'today', return_value={'2606': {LJ: '7'}}):
            self.assertEqual(self.t.track('LPV 2606', LJ, time.time()), ('7', False))

    def test_usual_track_when_not_announced(self):
        with mock.patch.object(self.t, 'today', return_value={}):
            self.assertEqual(self.t.track('LPV 2606', LJ, time.time()), ('11-A', True))

    def test_another_day_ignores_todays_announcement(self):
        with mock.patch.object(self.t, 'today', return_value={'2606': {LJ: '7'}}):
            self.assertEqual(self.t.track('LPV 2606', LJ, time.time() + 2 * 86400), ('11-A', True))

    def test_unknown_train_or_station(self):
        with mock.patch.object(self.t, 'today', return_value={}):
            self.assertEqual(self.t.track('LPV 9999', LJ), (None, False))
            self.assertEqual(self.t.track('LPV 2606', 'IJPP:1'), (None, False))
            self.assertEqual(self.t.track('BUS', LJ), (None, False))


class CommonTrackTests(SimpleTestCase):
    """Spec 2026-11-03 L2: a softer rule picks a lane for pairs without a usual track; it is never shown."""

    def test_a_track_with_half_the_days_is_common_not_usual(self):
        data = rows('518', LJ, ('d1', '3'), ('d2', '3'), ('d3', '4'), ('d4', '5'))
        self.assertEqual(tracks.usual_tracks(data), {})
        self.assertEqual(tracks.common_tracks(data), {'518': {LJ: '3'}})

    def test_a_usual_pair_is_not_repeated_as_common(self):
        data = rows('2606', LJ, ('d1', '9'), ('d2', '9'), ('d3', '9'))
        self.assertEqual(tracks.common_tracks(data), {})

    def test_a_scattered_pair_or_too_few_days_have_none(self):
        self.assertEqual(tracks.common_tracks(rows('518', LJ, ('d1', '3'), ('d2', '4'), ('d3', '5'))), {})
        self.assertEqual(tracks.common_tracks(rows('518', LJ, ('d1', '3'), ('d2', '3'))), {})


class LaneAndTerminusTests(SimpleTestCase):
    def setUp(self):
        self.t = tracks.Tracks()
        self.t.usual = lambda: {'2607': {LJ: '4'}}
        self.t.common = lambda: {'518': {LJ: '3'}, '2607': {'IJPP:7': '2'}}
        patcher = mock.patch.object(self.t, 'today', return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stay(self, **over):
        found = {'kind': 'continues', 'level': 'sure', 'to_number': '2607', **over}
        return mock.patch('prestop_statistics.train_stays.continues_as', side_effect=lambda n: found if n == '2606' else None)

    def test_lane_is_the_common_track_and_track_stays_unknown(self):
        self.assertEqual(self.t.track('IC 518', LJ), (None, False))
        self.assertEqual(self.t.lane('IC 518', LJ), '3')
        self.assertIsNone(self.t.lane('IC 518', 'IJPP:1'))
        self.assertIsNone(self.t.lane('BUS', LJ))

    def test_last_station_takes_the_track_of_the_train_the_set_goes_on_as(self):
        with self.stay():
            self.assertEqual(self.t.track('LPV 2606', LJ, last=True), ('4', True))
            self.assertEqual(self.t.track('LPV 2606', LJ), (None, False))  # not its last stop: no such track
            self.assertEqual(self.t.lane('LPV 2606', 'IJPP:7', last=True), '2')

    def test_last_station_track_is_never_announced_even_if_the_next_train_is(self):
        with self.stay(), mock.patch.object(self.t, 'today', return_value={'2607': {LJ: '8'}}):
            self.assertEqual(self.t.track('LPV 2606', LJ, time.time(), last=True), ('8', True))

    def test_no_track_where_the_set_does_not_go_on_or_it_is_only_coupled(self):
        with self.stay(kind='coupled'):
            self.assertEqual(self.t.track('LPV 2606', LJ, last=True), (None, False))
        with self.stay(level='unsure'):
            self.assertEqual(self.t.track('LPV 2606', LJ, last=True), (None, False))
        with self.stay():
            self.assertEqual(self.t.track('LPV 2606', 'IJPP:99', last=True), (None, False))

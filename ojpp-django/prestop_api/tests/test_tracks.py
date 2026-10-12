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

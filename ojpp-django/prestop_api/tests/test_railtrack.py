import json
import math

from django.test import SimpleTestCase

from prestop_api import border, geometry, railtrack

KX = railtrack._KX


def at(x: float, y: float) -> list:
    """Metres east and north of a point near Ljubljana, as [lon, lat]."""
    return [14.5 + x / KX, 46.0 + y / geometry.KY]


def arch(radius: float = 2000) -> list:
    """Track curving north in a half circle from (-radius, 0) to (radius, 0)."""
    return [at(-radius * math.cos(math.pi * k / 60), radius * math.sin(math.pi * k / 60)) for k in range(61)]


def straight(km: float = 6) -> list:
    return [at(0, 0), at(km * 1000, 0)]


def worst(track: railtrack.Track, line: list) -> float:
    return max(track.distance(*railtrack._xy(p), 5000) for p in geometry.densify(line, 10))


class FollowTests(SimpleTestCase):
    def test_a_shape_on_the_track_is_kept_as_it_is(self):
        track = railtrack.Track([straight()])
        line = [at(500, 8), at(5500, 8)]
        self.assertIs(track.follow(line), line)

    def test_stops_joined_by_a_straight_line_are_taken_along_the_curving_track(self):
        track = railtrack.Track([arch()])
        chord = [at(-2000, 0), at(2000, 0)]
        self.assertGreater(worst(track, chord), 1900)
        followed = track.follow(chord)
        self.assertLess(worst(track, followed), railtrack.OFF)
        self.assertGreater(geometry.cumulative(followed)[-1], 6000)  # the half circle, 6.3 km, not the 4 km chord

    def test_a_shape_on_an_abandoned_alignment_is_put_on_the_track_in_use(self):
        # North of Maribor most shapes still run 500 m off the new line, through the old Pekel tunnel.
        track = railtrack.Track([straight()])
        old = [at(0, 0), at(2000, 0), at(2500, 500), at(3500, 500), at(4000, 0), at(6000, 0)]
        followed = track.follow(old)
        self.assertLess(worst(track, followed), railtrack.CLOSE)
        self.assertAlmostEqual(geometry.cumulative(followed)[-1], 6000, delta=30)

    def test_no_hook_where_a_shape_drifting_off_joins_the_track_again(self):
        track = railtrack.Track([straight()])
        drift = [at(0, 0), at(1500, 0), at(2500, 60), at(3500, 60), at(4500, 0), at(6000, 0)]
        line = [railtrack._xy(p) for p in track.follow(drift)]
        for a, b, c in zip(line, line[1:], line[2:]):
            # every step goes on east: none turns back towards where the line came from
            self.assertGreater((b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]), 0)

    def test_where_the_track_has_a_gap_the_shape_stays_and_is_noted(self):
        # A line OpenStreetMap does not have yet: there is no way along the track, so the feed's shape is all there is.
        track = railtrack.Track([[at(0, 0), at(2000, 0)], [at(4000, 0), at(6000, 0)]])
        line = [at(0, 0), at(2000, 0), at(3000, 300), at(4000, 0), at(6000, 0)]
        followed = track.follow(line)
        self.assertGreater(worst(track, followed), 250)
        self.assertEqual(len(track.left), 1)

    def test_a_much_longer_way_round_is_another_line_and_is_not_taken(self):
        # Track only round a 20 km loop: a shape cutting 1 km across it is not put on the loop.
        loop = [at(0, 0), at(0, 10_000), at(1000, 10_000), at(1000, 0)]
        track = railtrack.Track([loop, [at(-3000, 0), at(0, 0)], [at(1000, 0), at(4000, 0)]])
        line = [at(-3000, 0), at(0, 0), at(500, 300), at(1000, 0), at(4000, 0)]
        self.assertLess(geometry.cumulative(track.follow(line))[-1], 8000)

    def test_a_station_beside_the_track_at_the_end_starts_the_line_on_the_track(self):
        track = railtrack.Track([straight()])
        followed = track.follow([at(0, 100), at(3000, 0), at(6000, 0)])
        self.assertLess(worst(track, followed), railtrack.OFF)

    def test_a_shape_starting_far_from_any_track_is_left_as_it_is_there(self):
        track = railtrack.Track([straight()])
        followed = track.follow([at(0, 400), at(3000, 0), at(6000, 0)])
        self.assertGreater(worst(track, followed), 300)


class CheckTests(SimpleTestCase):
    def test_a_long_chord_where_the_track_curves_is_reported(self):
        track = railtrack.Track([arch()])
        chord = [at(-2000, 0), at(2000, 0)]
        self.assertEqual(track.chords(chord), [chord])
        (stray,) = track.strays(chord)
        self.assertGreater(stray['length'], 3000)
        self.assertGreater(stray['worst'], 1900)

    def test_a_long_straight_on_straight_track_is_not_a_chord(self):
        track = railtrack.Track([straight(12)])
        line = [at(0, 5), at(12_000, 5)]  # Pragersko - Hoce runs 11.7 km straight
        self.assertEqual(track.chords(line), [])
        self.assertEqual(track.strays(line), [])

    def test_a_short_wobble_is_not_a_chord_but_a_stray_all_the_same(self):
        track = railtrack.Track([straight()])
        line = [at(0, 0), at(2000, 0), at(2200, 160), at(2400, 0), at(6000, 0)]
        self.assertEqual(track.chords(line), [])
        self.assertEqual(len(track.strays(line)), 1)


class FileTests(SimpleTestCase):
    def test_the_track_file_is_small_credits_openstreetmap_and_stays_in_slovenia(self):
        self.assertLess(railtrack.DATA.stat().st_size, 200 * 1024)
        data = json.loads(railtrack.DATA.read_text(encoding='utf-8'))
        self.assertIn('OpenStreetMap contributors', data['source'])
        points = [p for flat in data['tracks'] for p in railtrack._decode(flat)]
        self.assertGreater(len(points), 5000)
        self.assertEqual([p for p in points if not border.contains(*p)], [])

    def test_the_track_reaches_the_main_stations(self):
        track = railtrack.load()
        for name, lon, lat in [('Ljubljana', 14.5132, 46.0582), ('Zidani Most', 15.1686, 46.0842), ('Maribor', 15.6563, 46.5616),
                               ('Koper', 13.7470, 45.5436), ('Jesenice', 14.0548, 46.4367)]:
            self.assertLess(track.distance(*railtrack._xy([lon, lat]), 500), 300, name)

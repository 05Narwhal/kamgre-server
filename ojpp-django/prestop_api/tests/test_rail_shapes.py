"""Rail shapes without the sideways stub onto the station's point (geometry.trim_spurs)."""
import math

from django.test import SimpleTestCase

from prestop_api import geometry

M = 1 / 111_320  # about a metre of longitude at the equator; the tests only need the proportions
LAT = 1 / 110_574


def east(x, y=0.0):
    """A point x metres east and y metres north of Ljubljana station (14.513, 46.058)."""
    return [14.513 + x * M / 0.6943, 46.058 + y * LAT]  # cos(46.058°) ≈ 0.6943


class TrimSpursTests(SimpleTestCase):
    def test_a_shape_that_starts_on_the_station_point_beside_the_track_starts_on_the_track(self):
        # Ljubljana: the stop is 10 m north of the track, the shape steps down onto it and runs east.
        shape = [east(0, 10), east(0, 0), east(680, 0), east(900, 5)]
        self.assertEqual(geometry.trim_spurs(shape), shape[1:])
        # SŽ's stub comes in short collinear pieces (7.7 m + 2.2 m) before the turn.
        pieces = [east(0, 10), east(0, 2.3), east(0, 0), east(20, 0), east(680, 0)]
        self.assertEqual(geometry.trim_spurs(pieces), pieces[2:])
        # And the same at the end of a shape.
        self.assertEqual(geometry.trim_spurs(shape[::-1]), shape[1:][::-1])

    def test_an_out_and_back_spike_to_a_stop_is_dropped(self):
        shape = [east(-300, 0), east(0, 0), east(0, 12), east(5, 0), east(300, 0)]
        self.assertEqual(geometry.trim_spurs(shape), [east(-300, 0), east(0, 0), east(5, 0), east(300, 0)])

    def test_real_curves_and_long_ends_stay(self):
        curve = [east(0, 0), east(100, 0), east(180, 40), east(230, 110), east(250, 200)]
        self.assertEqual(geometry.trim_spurs(curve), curve)
        long_end = [east(0, 80), east(0, 0), east(500, 0)]  # 80 m: a real branch, not a stub
        self.assertEqual(geometry.trim_spurs(long_end), long_end)
        self.assertEqual(geometry.trim_spurs(long_end[:2]), long_end[:2])


def arc(radius, step, degrees, x0=0.0, y0=0.0):
    """Points every `step` metres along a left-hand curve of `radius`, starting east-bound at (x0, y0)."""
    count = int(math.radians(degrees) * radius / step)
    return [east(x0 + radius * math.sin(k * step / radius), y0 + radius * (1 - math.cos(k * step / radius))) for k in range(count + 1)]


def max_turn(coords):
    pts = geometry._local(coords, coords[0][1])
    pts = [p for i, p in enumerate(pts) if i == 0 or math.dist(p, pts[i - 1]) > 0.5]
    return max((geometry._turn(a, b, c) for a, b, c in zip(pts, pts[1:], pts[2:])), default=0.0)


class KinkTests(SimpleTestCase):
    def test_a_sideways_step_onto_the_station_point_mid_route_is_dropped(self):
        # Zidani Most (RG 1611, metres from the station): the line steps 5 m aside onto the station's point and back.
        through = [(60.0, -48.5), (42.2, -30.2), (24.5, -11.8), (6.7, 6.5), (-0.2, -0.1), (-18.7, 20.5), (-37.1, 41.1), (-55.5, 61.7)]
        # … with 130 m of the straight line either side.
        through = [(60.0 + 17.8 * k, -48.5 - 18.3 * k) for k in range(5, 0, -1)] + through + [(-55.5 - 18.4 * k, 61.7 + 20.6 * k) for k in range(1, 6)]
        out = geometry.trim_spurs([east(x, y) for x, y in through])
        self.assertLess(max_turn(out), 6.0)  # a turnout, not the 90° step
        # The 7 m shift to the other track is spread out: no point turns, and it starts well before the station.
        self.assertGreater(len(through) - len(out), 3)

    def test_a_step_out_and_back_onto_the_same_track_leaves_it_straight(self):
        shape = [east(x, 0) for x in range(-300, 301, 30)]
        shape[10] = east(0, 6)  # the station's point, 6 m beside the track
        out = geometry.trim_spurs(shape)
        self.assertTrue(all(abs(p[1] - 46.058) / LAT < 0.1 for p in out))

    def test_every_station_kink_on_a_long_line_goes(self):
        line = [east(x, 0) for x in range(0, 3000, 30)]
        for at in (600, 1500, 2400):  # three stations, each stepping 6–9 m off the track
            i = at // 30
            line[i] = east(at + 4, 7)
            line[i + 1] = east(at + 9, -1)
        out = geometry.trim_spurs(line)
        self.assertTrue(all(abs(p[1] - 46.058) / LAT < 1.5 for p in out), 'every point back on the track')

    def test_dense_and_sparse_curves_stay(self):
        for curve in (arc(190, 5, 90), arc(300, 30, 120), arc(150, 12, 60)):
            self.assertEqual(geometry.smooth_kinks(curve), curve)
        # A reversal (out and back on one track) is a turn of the route, not a kink.
        reversal = [east(0, 0), east(30, 0), east(60, 0), east(30, 0.5), east(0, 0.5)]
        self.assertEqual(geometry.smooth_kinks(reversal), reversal)

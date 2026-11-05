"""M9: a stop moves onto the road its lines use, at the right-hand kerb; both ways, the centre line."""
import math

from django.test import SimpleTestCase

from prestop_api import geometry, stopfix, stopplace

LAT, LON = 46.0, 15.0
KX = geometry.KY * math.cos(math.radians(LAT))


def east(metres: float) -> float:
    return LON + metres / KX


def north(metres: float) -> float:
    return LAT + metres / geometry.KY


def road(heading_east: bool = True) -> list:
    """A straight road along the parallel LAT, 400 m long, driven east (or west)."""
    coords = [[east(x), LAT] for x in range(-200, 201, 50)]
    return coords if heading_east else coords[::-1]


def passes_at(coords: list, x: float) -> tuple:
    cum = geometry.cumulative(coords)
    along = x + 200 if coords[0][0] < coords[-1][0] else 200 - x
    return stopplace.passing(coords, cum, along)


class PlaceTests(SimpleTestCase):
    def test_one_way_goes_to_the_right_kerb(self):
        # Driving east, the right is south: a pole 20 m south of the centre line is 17 m from the kerb.
        out = stopplace.place(north(-20), LON, [passes_at(road(), 0)])
        self.assertTrue(out['move'])
        self.assertEqual(out['why'], 'right kerb')
        self.assertAlmostEqual((out['lat'] - LAT) * geometry.KY, -stopplace.KERB, delta=0.2)
        self.assertAlmostEqual(out['metres'], 17.0, delta=0.3)

    def test_pole_on_the_left_never_crosses(self):
        out = stopplace.place(north(20), LON, [passes_at(road(), 0)])
        self.assertFalse(out['move'])
        self.assertEqual(out['why'], 'other side')

    def test_two_way_pole_stays_on_the_centre_line(self):
        out = stopplace.place(north(15), LON, [passes_at(road(), 0), passes_at(road(False), 0)])
        self.assertTrue(out['move'])
        self.assertEqual(out['why'], 'two-way centre')
        self.assertAlmostEqual(out['lat'], LAT, places=6)

    def test_close_and_far_are_not_moved(self):
        close = stopplace.place(north(-6), LON, [passes_at(road(), 0)])
        far = stopplace.place(north(-80), LON, [passes_at(road(), 0)])
        self.assertEqual((close['move'], close['why'], close['lat']), (False, 'close', north(-6)))
        self.assertEqual((far['move'], far['why']), (False, 'far'))

    def test_lines_on_different_roads_are_left_for_a_person(self):
        other = [[c[0], north(-30)] for c in road()]  # a parallel road 30 m south
        out = stopplace.place(north(-15), LON, [passes_at(road(), 0), passes_at(other, 0)])
        self.assertEqual((out['move'], out['why']), (False, 'lines disagree'))

    def test_osm_tagged_pole_wins_when_by_the_line_on_the_right(self):
        pole = (north(-5), east(4))
        out = stopplace.place(north(-30), LON, [passes_at(road(), 0)], pole=pole)
        self.assertEqual((out['move'], out['why']), (True, 'osm pole'))
        self.assertEqual((out['lat'], out['lon']), (round(pole[0], 6), round(pole[1], 6)))
        left = stopplace.place(north(-30), LON, [passes_at(road(), 0)], pole=(north(10), LON))
        self.assertEqual(left['why'], 'right kerb')

    def test_no_line_no_move(self):
        self.assertEqual(stopplace.place(LAT, LON, [])['why'], 'no line')


class StopfixPlacesTests(SimpleTestCase):
    def otp_stop(self, stop_id, lat, lon):
        return {'gtfsId': stop_id, 'name': stop_id, 'lat': lat, 'lon': lon}

    def test_place_beats_snap_and_override_beats_place_and_twice_changes_nothing(self):
        key = stopfix.snap_key('A', LAT, LON)
        snaps = {key: [9.0, 9.0, 50.0], stopfix.PLACED: {key: [north(-3), LON, 12.0, 'right kerb']}}
        none = {'stops': {}, 'names': {}}
        [placed] = stopfix.correct([self.otp_stop('A', LAT, LON)], none, snaps)
        self.assertEqual((placed['lat'], placed['feedLat']), (north(-3), LAT))
        self.assertEqual(stopfix.correct([placed], none, snaps), [placed])
        [hand] = stopfix.correct([self.otp_stop('A', LAT, LON)], {'stops': {'A': (1.0, 2.0)}, 'names': {}}, snaps)
        self.assertEqual((hand['lat'], hand['lon']), (1.0, 2.0))

"""A4: the real walk of a change (crossing the road, track to track, bay to bay) and its comfortable / tight rating."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import journeys, platforms, sources, tracks, transfer_walk
from prestop_api.tests.test_insane import plan, request
from prestop_api.tests.test_mapping import leg

AP, LJ = 'IJPP:1126954', transfer_walk.LJUBLJANA_RAIL


def ride(mode, start, end, trip, frm, to, platform=None):
    """A ride from stop `frm` to stop `to`, each (id, name, lat, lon); `platform`: the bay or track it leaves from."""
    raw = leg(mode, start, end, trip=trip)
    for end_, (stop_id, name, lat, lon) in (('from', frm), ('to', to)):
        raw[end_].update(name=name, lat=lat, lon=lon)
        raw[end_]['stop'] = {'gtfsId': stop_id, 'platformCode': platform if end_ == 'from' else None}
    raw['route']['shortName'] = {'RAIL': 'LPV 2400', 'BUS': '6'}[mode] if trip != 'IJPP:t2' else 'IC 502'
    return raw


def walk(start, end, seconds):
    return leg('WALK', start, end, transit=False, duration=seconds)


FAR = ('IJPP:far', 'Medvode', 46.14, 14.41)
FAR2 = ('IJPP:far2', 'Kamnik', 46.22, 14.61)
BAVARSKI = ('LPP:bd-north', 'Bavarski dvor', 46.05880, 14.50590)
BAVARSKI_SAME_SIDE = ('LPP:bd-north-2', 'Bavarski dvor', 46.05890, 14.50600)
BAVARSKI_ACROSS = ('LPP:bd-south', 'Bavarski dvor', 46.05862, 14.50610)  # 25 m off, the other direction
LJUBLJANA = (LJ, 'Ljubljana', 46.05817, 14.51043)
AP_STOP = (AP, 'Ljubljana AP', 46.05805, 14.51475)


class TransferWalkTests(SimpleTestCase):
    def build(self, *legs, slack=180):
        groups = {BAVARSKI[0]: [BAVARSKI[0], BAVARSKI_SAME_SIDE[0]], BAVARSKI_SAME_SIDE[0]: [BAVARSKI[0], BAVARSKI_SAME_SIDE[0]]}
        ways = {BAVARSKI[0]: [(0.0, 1.0)], BAVARSKI_SAME_SIDE[0]: [(0.0, 1.0)], BAVARSKI_ACROSS[0]: [(0.0, -1.0)],
                'IJPP:kranj-2': [(0.0, 1.0)], 'IJPP:kranj-5': [(0.0, -1.0)]}
        with mock.patch.object(sources, 'stop_group', side_effect=lambda s: groups.get(s, [s])),                 mock.patch.object(sources, 'stop_directions', side_effect=lambda s: ways.get(s, [])):
            [j] = journeys.build_journeys(plan(list(legs)), request(insane=False, slack=slack), [])
        [t] = j['transfers']
        return j, t

    def test_same_side_bus_change_is_otps_walk(self):
        _, t = self.build(ride('BUS', '10:00:00', '10:20:00', 'IJPP:b1', FAR, BAVARSKI), walk('10:20:00', '10:20:30', 30),
                          ride('BUS', '10:25:00', '10:40:00', 'IJPP:b2', BAVARSKI_SAME_SIDE, FAR2))
        self.assertEqual((t['walkSeconds'], t['walkKind'], t['rating'], t['status']), (30, 'same-side', 'comfortable', 'safe'))

    def test_opposite_side_bus_change_crosses_the_road(self):
        _, t = self.build(ride('BUS', '10:00:00', '10:20:00', 'IJPP:b1', FAR, BAVARSKI), walk('10:20:00', '10:20:40', 40),
                          ride('BUS', '10:24:00', '10:40:00', 'IJPP:b2', BAVARSKI_ACROSS, FAR2))
        # 40 s OTP walk + 60 s crossing = 100 s; 4 min there, 3 min buffer: under 100 + 180 s, so tight.
        self.assertEqual((t['walkSeconds'], t['walkKind'], t['rating'], t['status']), (100, 'cross-road', 'tight', 'tight'))
        self.assertEqual(t['requiredSeconds'], 100)

    def test_another_stop_of_a_bus_station_is_not_across_the_road(self):
        kranj2, kranj5 = ('IJPP:kranj-2', 'Kranj AP', 46.2449, 14.3555), ('IJPP:kranj-5', 'Kranj AP', 46.2451, 14.3559)
        _, t = self.build(ride('BUS', '10:00:00', '10:20:00', 'IJPP:b1', FAR, kranj2), walk('10:20:00', '10:20:40', 40),
                          ride('BUS', '10:30:00', '10:40:00', 'IJPP:b2', kranj5, FAR2))
        self.assertEqual((t['walkSeconds'], t['walkKind']), (40, 'walk'))  # in one way, out the other: bays, no road between

    def test_ljubljana_track_change(self):
        tracks_at = {('LPV 2400', LJ): '3'}
        with mock.patch.object(tracks.tracks, 'track', side_effect=lambda name, stop, at=None: (tracks_at.get((name, stop)), True)):
            _, t = self.build(ride('RAIL', '10:00:00', '10:20:00', 'IJPP:t1', FAR, LJUBLJANA),
                              ride('RAIL', '10:26:00', '11:40:00', 'IJPP:t2', LJUBLJANA, FAR2, platform='7'))
            self.assertEqual((t['walkSeconds'], t['walkKind'], t['rating']), (240, 'track', 'tight'))  # 6 min < 4 + 3
            # The same platform: a few steps, comfortable.
            _, same = self.build(ride('RAIL', '10:00:00', '10:20:00', 'IJPP:t1', FAR, LJUBLJANA),
                                 ride('RAIL', '10:27:00', '11:40:00', 'IJPP:t2', LJUBLJANA, FAR2, platform='3'))
            self.assertEqual((same['walkSeconds'], same['rating']), (transfer_walk.SAME_TRACK_SECONDS, 'comfortable'))

    def test_ljubljana_bay_to_bay(self):
        j, t = self.build(ride('BUS', '10:00:00', '10:20:00', 'IJPP:b1', FAR, AP_STOP),
                          ride('BUS', '10:25:00', '11:40:00', 'IJPP:b2', AP_STOP, FAR2, platform='27'))
        # From where the bus sets down to bay 27, ~76 m away: 76 m × 1.4 / 1.2 m/s ≈ 89 s (OTP walks 0 here).
        bay = platforms.bays(AP)['27']
        setdown = j['legs'][0]['destination']
        meters = transfer_walk._meters(setdown, {'latitude': bay['lat'], 'longitude': bay['lon']})
        self.assertAlmostEqual(t['walkSeconds'], meters * transfer_walk.DETOUR / transfer_walk.WALK_SPEED, delta=1)
        self.assertTrue(60 <= t['walkSeconds'] <= 120, t['walkSeconds'])
        self.assertEqual((t['walkKind'], t['rating'], t['platform']), ('bay', 'comfortable', '27'))  # 5 min ≥ 1.5 + 3
        # With a 4 min buffer the same change is tight.
        _, tight = self.build(ride('BUS', '10:00:00', '10:20:00', 'IJPP:b1', FAR, AP_STOP),
                              ride('BUS', '10:25:00', '11:40:00', 'IJPP:b2', AP_STOP, FAR2, platform='27'), slack=240)
        self.assertEqual(tight['rating'], 'tight')

    def test_ljubljana_track_to_bay(self):
        with mock.patch.object(tracks.tracks, 'track', side_effect=lambda name, stop, at=None: ('5', True) if stop == LJ else (None, False)):
            _, t = self.build(ride('RAIL', '10:00:00', '10:20:00', 'IJPP:t1', FAR, LJUBLJANA), walk('10:20:00', '10:23:00', 180),
                              ride('BUS', '10:35:00', '11:40:00', 'IJPP:b2', AP_STOP, FAR2, platform='27'))
        # OTP's 3 min from the station to the bus station, 2.5 min off track 5, and on to bay 27.
        self.assertEqual(t['walkKind'], 'track-to-bus')
        self.assertGreater(t['walkSeconds'], 180 + transfer_walk.TRACK_EXIT_SECONDS[LJ])

    def test_rating_rule(self):
        self.assertEqual(transfer_walk.rate(400, 100, 180), ('safe', True, 'comfortable'))
        self.assertEqual(transfer_walk.rate(200, 100, 180), ('tight', False, 'tight'))
        self.assertEqual(transfer_walk.rate(60, 100, 180), ('missed', False, 'tight'))

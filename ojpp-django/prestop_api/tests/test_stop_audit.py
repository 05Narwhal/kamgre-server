"""stop_audit (spec 2026-10-23 E6): empty stops, twins, far namesakes and wide merged markers."""
from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import supplement
from prestop_api.management.commands.stop_audit import audit
from prestop_api.tests.test_kamgre import stop
from prestop_api.tests.test_stopfix import EAST, WEST

LAT, LON = 46.0566, 14.5054


def north(meters: float) -> float:
    return LAT + meters / 110_574


def snap(stops: list[dict], ways: dict, merged: list[dict] = None) -> dict:
    return {'all': stops, 'list': merged if merged is not None else stops, 'directions': ways}


class AuditTests(SimpleTestCase):
    def test_a_marker_is_empty_only_when_none_of_its_members_has_a_trip(self):
        a, b, c = stop('LPP:a', 'Kolodvor', LAT, LON), stop('IJPP:b', 'Kolodvor', north(5), LON), stop('LPP:c', 'Rudnik', north(900), LON)
        head = {**b, 'memberIds': ['IJPP:b', 'LPP:a']}
        found = audit(snap([a, b, c], {}, [head, c]), {}, {}, served={'LPP:a'})
        self.assertEqual([m['id'] for m in found['empty']], ['LPP:c'])
        self.assertEqual(audit(snap([a, b, c], {}, [head, c]), {}, {})['empty'], [])

    def test_a_case_only_twin_going_the_same_way_is_listed(self):
        a, b = stop('LPP:a', 'KOLODVOR', LAT, LON), stop('IJPP:b', 'Kolodvor', north(40), LON)
        found = audit(snap([a, b], {'LPP:a': EAST, 'IJPP:b': EAST}), {}, {})
        self.assertEqual([(x['id'], y['id']) for x, y, _ in found['twins']], [('IJPP:b', 'LPP:a')])
        self.assertEqual(found['far'], [])

    def test_two_termini_at_one_spot_are_twins(self):
        a, b = stop('LPP:a', 'KOLODVOR', LAT, LON), stop('LPP:b', 'SŽ KOLODVOR', north(5), LON)
        found = audit(snap([a, b], {'LPP:a': EAST + WEST, 'LPP:b': WEST + EAST}), {}, {})
        self.assertEqual(len(found['twins']), 1)

    def test_opposite_sides_are_never_twins(self):
        a, b = stop('LPP:a', 'NS Rudnik', LAT, LON), stop('LPP:b', 'NS Rudnik', north(25), LON)
        found = audit(snap([a, b], {'LPP:a': EAST, 'LPP:b': WEST}), {}, {})
        self.assertEqual((found['twins'], found['far']), ([], []))

    def test_an_unknown_direction_is_not_a_twin(self):
        a, b = stop('LPP:a', 'Viadukt', LAT, LON), stop('IJPP:b', 'Viadukt', north(30), LON)
        self.assertEqual(audit(snap([a, b], {'LPP:a': EAST}), {}, {})['twins'], [])

    def test_far_namesakes_lie_75_to_400_m_apart(self):
        a, b, c, d = (stop('IJPP:a', 'Bavarski dvor', LAT, LON), stop('LPP:b', 'Bavarski dvor', north(120), LON),
                      stop('LPP:c', 'Bavarski dvor', north(300), LON), stop('LPP:d', 'Bavarski dvor', north(900), LON))
        ways = {s['id']: EAST for s in (a, b, c, d)}
        found = audit(snap([a, b, c, d], ways), {}, {})
        far = sorted((x['id'], y['id'], round(m)) for x, y, m in found['far'])
        self.assertEqual(far, [('IJPP:a', 'LPP:b', 120), ('IJPP:a', 'LPP:c', 300), ('LPP:b', 'LPP:c', 180)])
        self.assertEqual([(x['id'], y['id']) for x, y, _ in found['twins']], [('IJPP:a', 'LPP:b')])

    def test_a_merged_marker_with_a_far_member_is_wide(self):
        a, b, c = stop('IJPP:a', 'Ljubljana Viadukt', LAT, LON), stop('LPP:b', 'Viadukt', north(5), LON), stop('LPP:c', 'Viadukt', north(118), LON)
        marker = {**a, 'latitude': c['latitude'], 'memberIds': ['IJPP:a', 'LPP:c', 'LPP:b']}
        found = audit(snap([a, b, c], {}, [marker]), {}, {})
        self.assertEqual([(m['id'], far['id'], round(d)) for m, far, d in found['wide']], [('IJPP:a', 'IJPP:a', 118)])


class RunningStopsTests(SimpleTestCase):
    def test_stops_of_trips_running_on_one_of_the_days(self):
        feed = {'calendar': {'wk': ('20261001', '20261231', [True] * 5 + [False] * 2), 'old': ('20260101', '20260601', [True] * 7)},
                'exceptions': {}, 'trips': {'T1': {'id': 'T1', 'serviceId': 'wk'}, 'T2': {'id': 'T2', 'serviceId': 'old'}},
                'byStop': {'S:1': [('T1', 0)], 'S:2': [('T1', 1), ('T2', 0)], 'S:3': [('T2', 1)]}}
        with mock.patch.object(supplement, '_feeds', return_value={'S': feed}):
            self.assertEqual(supplement.running_stops([date(2026, 10, 24), date(2026, 10, 25)]), set())  # a weekend
            self.assertEqual(supplement.running_stops([date(2026, 10, 25), date(2026, 10, 26)]), {'S:1', 'S:2'})

import json
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import gbfs
from prestop_api.upstream import UpstreamError

FIXTURES = Path(__file__).parent / 'fixtures' / 'gbfs'


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


def fake_get_json(version, missing=()):
    """get_json for one fixture feed: https://vN.example/<feed>.json -> vN_<feed>.json."""
    def get(url, timeout=None):
        if url.endswith('/gbfs.json'):
            return fixture(f'{version}_gbfs')
        feed = url.rsplit('/', 1)[1].removesuffix('.json')
        if feed in missing or not (FIXTURES / f'{version}_{feed}.json').exists():
            raise UpstreamError(f'{feed} unavailable')
        return fixture(f'{version}_{feed}')
    return get


def load(version, **kwargs):
    with mock.patch.object(gbfs, 'get_json', fake_get_json(version, **kwargs)):
        return gbfs.load_network(f'test_{version}', 'https://feed.example/gbfs.json')


class NormaliseTests(SimpleTestCase):
    def test_v1_reads_numbers_flags_and_epoch_times(self):
        network = load('v1')
        self.assertEqual(network['version'], '1.0')
        self.assertEqual(network['name'], 'Example v1 bikes')
        self.assertEqual(network['updated'], 1791619200)
        self.assertEqual(network['stations']['101'], {
            'bikes': 4, 'ebikes': 1, 'docks': 8, 'renting': True, 'returning': True, 'installed': True,
            'lastReported': 1791619100,
        })
        self.assertIs(network['stations']['102']['renting'], False)

    def test_v1_unknown_counts_stay_unknown_never_0(self):
        station = load('v1')['stations']['103']
        self.assertIsNone(station['bikes'])
        self.assertIsNone(station['ebikes'])
        self.assertIsNone(station['lastReported'])
        self.assertEqual(station['docks'], 5)

    def test_v2_splits_e_bikes_by_vehicle_type_and_prefers_english_feeds(self):
        network = load('v2')
        self.assertEqual(network['version'], '2.3')
        self.assertEqual(network['name'], 'KolesCE')
        self.assertEqual(network['stations']['2001'], {
            'bikes': 5, 'ebikes': 2, 'docks': 7, 'renting': True, 'returning': True, 'installed': True,
            'lastReported': 1791619150,
        })
        self.assertEqual(network['stations']['2002']['ebikes'], 0)

    def test_v2_without_vehicle_types_leaves_e_bikes_unknown(self):
        station = load('v2', missing=('vehicle_types',))['stations']['2001']
        self.assertEqual(station['bikes'], 5)
        self.assertIsNone(station['ebikes'])

    def test_v3_reads_vehicles_localised_names_and_rfc3339_times(self):
        network = load('v3')
        self.assertEqual(network['version'], '3.0')
        self.assertEqual(network['name'], 'BicikeLJ')
        self.assertEqual(network['updated'], 1791612000)  # 2026-10-10T08:00+02:00
        first, closed = network['stations']['1'], network['stations']['2']
        self.assertEqual((first['bikes'], first['ebikes'], first['docks']), (9, 3, 11))
        self.assertEqual(first['lastReported'], 1791601960)  # 05:12:40+02:00
        self.assertEqual((closed['installed'], closed['renting'], closed['returning']), (False, False, False))

    def test_a_feed_without_station_status_fails(self):
        with self.assertRaises(UpstreamError):
            load('v1', missing=('station_status',))


class MergeTests(SimpleTestCase):
    otp = {'id': 'jcdecaux_ljubljana:1', 'availableCount': 7, 'docksAvailable': 13, 'canPickup': True, 'canReturn': True,
           'updatedAt': '2026-10-10T06:05:00Z', 'capacity': 20}

    def feeds(self, version='v3', ok=True):
        return {'jcdecaux_ljubljana': {'ok': True, **load(version)} if ok else {'ok': False, 'error': 'down'}}

    def test_the_operator_feed_overrides_otp_and_carries_its_own_time(self):
        out = gbfs.merge(self.otp, 'jcdecaux_ljubljana', '1', self.feeds(), now=1791612300)
        self.assertEqual((out['availableCount'], out['ebikesAvailable'], out['docksAvailable']), (9, 3, 11))
        self.assertEqual(out['updatedAt'], '2026-10-10T06:00:00Z')
        self.assertEqual(out['gbfsVersion'], '3.0')
        self.assertEqual(out['capacity'], 20)
        self.assertTrue(out['canPickup'] and out['canReturn'])

    def test_a_closed_station_can_neither_rent_nor_return(self):
        out = gbfs.merge({**self.otp, 'id': 'jcdecaux_ljubljana:2'}, 'jcdecaux_ljubljana', '2', self.feeds(), now=1791612300)
        self.assertEqual(out['availableCount'], 0)
        self.assertFalse(out['canPickup'])
        self.assertFalse(out['canReturn'])

    def test_a_failed_feed_keeps_otps_numbers(self):
        self.assertIs(gbfs.merge(self.otp, 'jcdecaux_ljubljana', '1', self.feeds(ok=False), now=1791612300), self.otp)

    def test_a_station_missing_from_the_feed_keeps_otps_numbers(self):
        self.assertIs(gbfs.merge(self.otp, 'jcdecaux_ljubljana', '999', self.feeds(), now=1791612300), self.otp)


class DiscoveryTests(SimpleTestCase):
    def test_versions(self):
        self.assertEqual(gbfs.version_of(fixture('v1_gbfs')), '1.0')
        self.assertEqual(gbfs.version_of(fixture('v3_gbfs')), '3.0')

    def test_v2_picks_english_over_other_languages(self):
        self.assertEqual(gbfs.feed_urls(fixture('v2_gbfs'))['station_status'], 'https://v2.example/station_status.json')

"""Place search speed: geocoder answers are cached, and the slow geocoder does not hold up the quick one."""
import threading
import time
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from prestop_api import places, sources

LOCAL_CACHE = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


def place(name, source):
    return {'id': f'{source}:{name}', 'name': name, 'detail': None, 'category': 'address', 'kind': 'address', 'latitude': 46.05, 'longitude': 14.5}


@override_settings(CACHES=LOCAL_CACHE, PRESTOP_SHORT_CACHE=True)
class SearchTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.release = threading.Event()

    def slow_photon(self, *args):
        self.release.wait(5)
        return [place('Tivolska cesta 30', 'osm')]

    def test_the_quick_geocoder_answers_first_and_the_slow_one_arrives_from_the_cache(self):
        pelias = mock.Mock(return_value=[place('Tivolska cesta', 'pelias')])
        photon = mock.Mock(side_effect=self.slow_photon)
        with mock.patch.object(places, '_photon', photon), mock.patch.object(places, '_pelias', pelias):
            started = time.monotonic()
            found, complete = places.search('tivolska', 8, 'sl', soft=0.1)
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(([p['name'] for p in found], complete), (['Tivolska cesta'], False))
            self.release.set()
            for _ in range(50):  # the lookup finishes after the answer went out
                if not places._inflight:
                    break
                time.sleep(0.02)
            found, complete = places.search('Tivolska', 8, 'sl', soft=0.1)
        self.assertTrue(complete)
        self.assertEqual(sorted(p['name'] for p in found), ['Tivolska cesta', 'Tivolska cesta 30'])
        self.assertEqual((photon.call_count, pelias.call_count), (1, 1))  # the second search asked neither

    def test_without_soft_it_waits_for_both(self):
        self.release.set()
        with mock.patch.object(places, '_photon', mock.Mock(side_effect=self.slow_photon)), mock.patch.object(places, '_pelias', mock.Mock(return_value=[])):
            self.assertEqual([p['name'] for p in places.geocode('tivolska', 8, 'sl')], ['Tivolska cesta 30'])

    def test_a_failed_geocoder_is_not_asked_again_at_once_and_the_answer_is_complete(self):
        photon = mock.Mock(side_effect=places.UpstreamError('down'))
        with mock.patch.object(places, '_photon', photon), mock.patch.object(places, '_pelias', mock.Mock(return_value=[place('Bled', 'pelias')])):
            self.assertEqual(places.search('bled', 5, 'sl', soft=0.1)[1], True)
            found, complete = places.search('bled', 5, 'sl', soft=0.1)
        self.assertEqual(([p['name'] for p in found], complete, photon.call_count), (['Bled'], True, 1))

    def test_both_failing_is_an_upstream_error(self):
        down = mock.Mock(side_effect=places.UpstreamError('down'))
        with mock.patch.object(places, '_photon', down), mock.patch.object(places, '_pelias', down), self.assertRaises(places.UpstreamError):
            places.search('bled', 5, 'sl', soft=0.1)

    def test_the_cache_key_ignores_case_and_spaces_but_not_the_area(self):
        self.assertEqual(places._key('photon', ' Bled', 5, 'sl', (46.051, 14.5)), places._key('photon', 'bled ', 5, 'sl', (46.05, 14.5)))
        self.assertNotEqual(places._key('photon', 'bled', 5, 'sl', (46.05, 14.5)), places._key('photon', 'bled', 5, 'sl', (46.37, 14.11)))


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class ViewTests(SimpleTestCase):
    def test_an_incomplete_answer_says_so(self):
        with mock.patch.object(sources, 'search_stations', return_value=[]), \
                mock.patch.object(sources, 'geocode_soon', return_value=([place('Tivolska cesta', 'pelias')], False)):
            body = self.client.get('/api/v1/places', {'q': 'tivolska'}).json()
        self.assertEqual(([p['name'] for p in body['data']], body.get('partial')), (['Tivolska cesta'], True))
        with mock.patch.object(sources, 'search_stations', return_value=[]), \
                mock.patch.object(sources, 'geocode_soon', return_value=([], True)):
            self.assertNotIn('partial', self.client.get('/api/v1/places', {'q': 'tivolska'}).json())

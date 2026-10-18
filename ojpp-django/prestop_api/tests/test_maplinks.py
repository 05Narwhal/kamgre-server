from unittest import mock

from django.test import SimpleTestCase

from prestop_api import maplinks


class MapLinkTests(SimpleTestCase):
    def test_coordinates(self):
        self.assertEqual(maplinks.parse_coordinates('46.0514, 14.5060'), (46.0514, 14.506))
        self.assertEqual(maplinks.parse_coordinates('46.0514 14.5060'), (46.0514, 14.506))
        lat, lon = maplinks.parse_coordinates('46°03\'05.0"N 14°30\'21.6"E')
        self.assertAlmostEqual(lat, 46.05139, places=4)
        self.assertAlmostEqual(lon, 14.506, places=4)
        self.assertIsNone(maplinks.parse_coordinates('Kranj'))
        self.assertIsNone(maplinks.parse_coordinates('123, 456'))

    def test_google_links(self):
        place = maplinks.parse_link('https://www.google.com/maps/place/Pre%C5%A1ernov+trg/@46.0514,14.5056,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d46.0513!4d14.5061')
        self.assertEqual(place, {'coords': (46.0513, 14.5061), 'name': 'Prešernov trg', 'query': None})
        self.assertEqual(maplinks.parse_link('https://maps.google.com/?q=46.1,14.2')['coords'], (46.1, 14.2))
        self.assertEqual(maplinks.parse_link('https://www.google.com/maps/search/?api=1&query=46.1%2C14.2')['coords'], (46.1, 14.2))
        self.assertEqual(maplinks.parse_link('https://www.google.si/maps/@46.2,14.3,15z')['coords'], (46.2, 14.3))
        self.assertEqual(maplinks.parse_link('https://maps.google.com/?q=Bled+Castle&ftid=0x1'), {'coords': None, 'name': 'Bled Castle', 'query': 'Bled Castle'})
        self.assertEqual(maplinks.parse_link('geo:46.3,14.1')['coords'], (46.3, 14.1))
        self.assertIsNone(maplinks.parse_link('https://evil.example/maps/@46.2,14.3'))

    def test_link_detection(self):
        self.assertTrue(maplinks.looks_like_link('https://maps.app.goo.gl/AbCd123'))
        self.assertTrue(maplinks.looks_like_link('www.google.com/maps/place/Bled'))
        self.assertFalse(maplinks.looks_like_link('https://example.com/maps'))
        self.assertFalse(maplinks.looks_like_link('Google Maps'))

    def test_expand_never_leaves_google(self):
        response = mock.Mock(status_code=302, headers={'Location': 'http://127.0.0.1/admin'})
        with mock.patch('prestop_api.maplinks.requests.get', return_value=response) as get:
            self.assertIsNone(maplinks.expand('https://maps.app.goo.gl/AbCd123'))
        self.assertEqual(get.call_count, 1)
        response = mock.Mock(status_code=302, headers={'Location': 'https://www.google.com/maps/place/Bled/@46.36,14.09,15z'})
        with mock.patch('prestop_api.maplinks.requests.get', return_value=response):
            self.assertEqual(maplinks.expand('https://maps.app.goo.gl/AbCd123'), 'https://www.google.com/maps/place/Bled/@46.36,14.09,15z')

    def test_expand_only_follows_web_links_on_standard_ports_within_its_time(self):
        # Spec 2026-10-18 A6: no other schemes or ports even on a Google host, and a few seconds at most.
        response = mock.Mock(status_code=302, headers={'Location': 'https://maps.app.goo.gl:8443/next'})
        with mock.patch('prestop_api.maplinks.requests.get', return_value=response) as get:
            self.assertIsNone(maplinks.expand('https://maps.app.goo.gl/AbCd123'))
            self.assertIsNone(maplinks.expand('ftp://maps.app.goo.gl/AbCd123'))
            self.assertIsNone(maplinks.expand('https://x@maps.app.goo.gl/AbCd123'))
        self.assertEqual(get.call_count, 1)
        loop = mock.Mock(status_code=302, headers={'Location': 'https://maps.app.goo.gl/again'})
        with mock.patch('prestop_api.maplinks.requests.get', return_value=loop) as get, mock.patch.object(maplinks, 'EXPAND_BUDGET', 0.6):
            self.assertIsNone(maplinks.expand('https://maps.app.goo.gl/AbCd123'))
        self.assertLessEqual(max(call.kwargs['timeout'][1] for call in get.call_args_list), 0.6)

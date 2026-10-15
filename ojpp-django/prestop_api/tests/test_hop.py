"""Hop: presence, nearby, codes and sending (hop.py), on a scratch Redis database."""
import json
import time
import uuid

from django.test import SimpleTestCase, override_settings

from prestop_api import hop

HOP = dict(PRESTOP_HOP_REDIS_URL='redis://127.0.0.1:6379/13', PRESTOP_CLIENT_IP_HEADER='CF-Connecting-IP', ROOT_URLCONF='ojpp_core.urls_prestop')
HOME, CAFE, FAR = 'u2edk5x', 'u2edk5z', 'u2ed2bx'  # Ljubljana: a cell, its neighbour, one ~5 km off


def device():
    return str(uuid.uuid4())


@override_settings(**HOP)
class HopTests(SimpleTestCase):
    def setUp(self):
        hop._redis().flushdb()
        self.now = time.time()

    def here(self, dev, nick, ip='198.51.100.1', cell=None, at=None):
        return hop.presence({'device': dev, 'nickname': nick, **({'cell': cell} if cell else {})}, ip, now=at or self.now)

    def names(self, dev, at=None):
        return [p['nickname'] for p in hop.nearby(dev, now=at or self.now)]

    def test_same_ip_is_nearby_under_an_opaque_token(self):
        ana, bor = device(), device()
        self.here(ana, 'Ana')
        self.here(bor, 'Bor')
        self.here(device(), 'Elsewhere', ip='203.0.113.5')
        [peer] = hop.nearby(ana, now=self.now)
        self.assertEqual(peer['nickname'], 'Bor')
        self.assertNotIn(bor, peer['peer'])
        self.assertNotEqual(peer['peer'], hop.nearby(bor, now=self.now)[0]['peer'])  # each viewer has its own tokens
        self.assertEqual(self.names(bor), ['Ana'])

    def test_same_or_adjacent_cell_is_nearby_far_is_not(self):
        ana, bor, cene = device(), device(), device()
        self.here(ana, 'Ana', ip='198.51.100.1', cell=HOME)
        self.here(bor, 'Bor', ip='203.0.113.2', cell=CAFE)
        self.here(cene, 'Cene', ip='203.0.113.3', cell=FAR)
        self.assertEqual(self.names(ana), ['Bor'])
        self.assertEqual(self.names(cene), [])
        self.assertIn(CAFE, hop.cells_around(HOME))
        self.assertEqual(len(hop.cells_around(HOME)), 9)

    def test_a_crowded_ip_counts_only_peers_that_also_match_by_cell(self):
        crowd = [device() for _ in range(hop.CGNAT_LIMIT + 1)]
        for i, dev in enumerate(crowd):
            self.here(dev, f'Phone {i}', ip='100.64.0.1', cell=HOME if i < 2 else None)
        self.assertEqual(self.names(crowd[0]), ['Phone 1'])
        self.assertEqual(self.names(crowd[5]), [])

    def test_presence_ends_after_its_ttl_and_at_once_on_leave(self):
        ana, bor = device(), device()
        self.here(ana, 'Ana')
        self.here(bor, 'Bor')
        self.assertEqual(self.names(ana, at=self.now + hop.PRESENCE_TTL + 5), [])
        hop.presence({'device': bor, 'leave': True}, '198.51.100.1')
        self.assertEqual(self.names(ana), [])

    def test_send_to_a_code_from_anywhere_is_delivered_once(self):
        ana, far = device(), device()
        code = self.here(ana, 'Ana')['code']
        self.assertRegex(code, '^[A-HJ-NP-Z2-9]{4}$')
        self.here(far, 'Far', ip='203.0.113.9', cell=FAR)
        item = {'kind': 'line', 'id': 'IJPP:r-a', 'date': '2026-10-20', 'trip': 'IJPP:t1'}
        self.assertEqual(hop.send({'device': far, 'to': code.lower(), 'item': item}, now=self.now), {'sent': True})
        [message] = self.here(ana, 'Ana')['incoming']
        self.assertEqual((message['from'], message['item']), ('Far', item))
        self.assertEqual(self.here(ana, 'Ana')['incoming'], [])  # deleted once delivered
        self.assertEqual(self.here(ana, 'Ana')['code'], code)  # the code stays

    def test_send_to_a_listed_peer_and_messages_expire(self):
        ana, bor = device(), device()
        self.here(ana, 'Ana')
        self.here(bor, 'Bor')
        [peer] = hop.nearby(ana, now=self.now)
        hop.send({'device': ana, 'to': peer['peer'], 'item': {'kind': 'stop', 'id': 'IJPP:1122804'}}, now=self.now)
        self.assertEqual(self.here(bor, 'Bor', at=self.now + hop.MESSAGE_TTL + 1)['incoming'], [])
        with self.assertRaisesRegex(hop.HopError, 'not reachable'):
            hop.send({'device': bor, 'to': peer['peer'], 'item': {'kind': 'stop', 'id': 'IJPP:1'}}, now=self.now)  # Ana's token

    def test_limits(self):
        ana, bor = device(), device()
        code = self.here(bor, 'Bor')['code']
        self.here(ana, 'Ana', ip='203.0.113.1')
        item = {'kind': 'vehicle', 'id': 'LPP:123'}
        for _ in range(hop.INBOX_LIMIT):
            hop.send({'device': ana, 'to': code, 'item': item}, now=self.now)
        with self.assertRaises(hop.HopError) as full:
            hop.send({'device': ana, 'to': code, 'item': item}, now=self.now)
        self.assertEqual(full.exception.code, 'INBOX_FULL')
        for _ in range(hop.SEND_PER_MINUTE - hop.INBOX_LIMIT - 1):
            self.here(bor, 'Bor')  # empties the inbox
            hop.send({'device': ana, 'to': code, 'item': item}, now=self.now)
        self.here(bor, 'Bor')
        with self.assertRaises(hop.HopError) as rate:
            hop.send({'device': ana, 'to': code, 'item': item}, now=self.now)
        self.assertEqual(rate.exception.code, 'RATE_LIMITED')

    def test_payloads_that_are_not_app_objects_are_refused(self):
        ana = device()
        code = self.here(ana, 'Ana')['code']
        sender = device()
        self.here(sender, 'Bor')
        for item in ({'kind': 'note', 'text': 'hi'}, {'kind': 'stop', 'id': 'IJPP:1', 'name': 'Free text'},
                     {'kind': 'stop', 'id': 'https://evil.example/x'}, {'kind': 'journey', 'code': 'abc def'},
                     {'kind': 'line', 'id': 'IJPP:r', 'date': 'tomorrow'}, 'journey', None):
            with self.assertRaises(hop.HopError, msg=item) as refused:
                hop.send({'device': sender, 'to': code, 'item': item}, now=self.now)
            self.assertEqual(refused.exception.code, 'INVALID_ITEM')
        for nick in ('A', 'x' * 21, ' Ana', 'Ana!', 'a<b>'):
            with self.assertRaises(hop.HopError, msg=nick):
                hop.presence({'device': ana, 'nickname': nick}, '198.51.100.1')
        self.assertTrue(hop.nickname_ok('Žan Čuk-2'))
        self.assertTrue(hop.nickname_ok('Анна'))
        with self.assertRaises(hop.HopError):
            hop.presence({'device': 'not-a-device', 'nickname': 'Ana'}, '198.51.100.1')
        with self.assertRaises(hop.HopError):
            hop.send({'device': device(), 'to': code, 'item': {'kind': 'stop', 'id': 'IJPP:1'}})  # not present itself

    def test_the_api(self):
        ana, bor = device(), device()
        post = lambda path, body, ip='198.51.100.1': self.client.post(f'/api/v1/hop/{path}', json.dumps(body), content_type='application/json', HTTP_CF_CONNECTING_IP=ip)
        code = post('presence', {'device': ana, 'nickname': 'Ana'}).json()['data']['code']
        post('presence', {'device': bor, 'nickname': 'Bor'})
        [peer] = self.client.get('/api/v1/hop/nearby', {'device': ana}).json()['data']
        self.assertEqual(peer['nickname'], 'Bor')
        self.assertEqual(post('send', {'device': bor, 'to': code, 'item': {'kind': 'journey', 'code': 'Bq3xA_-9'}}).status_code, 200)
        self.assertEqual(post('presence', {'device': ana, 'nickname': 'Ana'}).json()['data']['incoming'][0]['item'], {'kind': 'journey', 'code': 'Bq3xA_-9'})
        self.assertEqual(post('send', {'device': bor, 'to': code, 'item': {'kind': 'journey', 'code': 'x' * 5000}}).status_code, 413)
        self.assertEqual(post('send', {'device': bor, 'to': code, 'item': {'kind': 'stop', 'id': 'IJPP:1', 'url': 'x'}}).status_code, 422)

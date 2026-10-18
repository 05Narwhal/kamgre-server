import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from pywebpush import WebPushException

from prestop_push import watcher
from prestop_push.models import PushSubscription, Watch

NOW = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
SUB = {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc', 'keys': {'p256dh': 'BNc' + 'A' * 84, 'auth': 'x' * 22}, 'language': 'sl'}


def trip(delay=0, canceled=False):
    when = (NOW + timedelta(minutes=20, seconds=delay)).isoformat()
    return {'id': 'LPP:t1', 'routeName': '6', 'stops': [{'stopId': 'LPP:a', 'name': 'Bavarski dvor', 'scheduledDeparture': (NOW + timedelta(minutes=20)).isoformat(),
            'effectiveDeparture': when, 'scheduledArrival': when, 'effectiveArrival': when, 'canceled': canceled}]}


class PushTests(TestCase):
    def setUp(self):
        self.sub = PushSubscription.objects.create(endpoint=SUB['endpoint'], p256dh=SUB['keys']['p256dh'], auth=SUB['keys']['auth'], language='sl')

    def watch(self, **extra):
        return Watch.objects.create(subscription=self.sub, client_id='board:x', kind='departure', notify_at=NOW + timedelta(minutes=15),
                                    title='6 → Črnuče', body='08:20', url='/stations/LPP%3Aa', trip_ids=['LPP:t1'], stop_id='LPP:a',
                                    scheduled_at=NOW + timedelta(minutes=20), expires_at=NOW + timedelta(hours=1), **extra)

    def test_subscribe_is_idempotent_by_endpoint(self):
        for _ in range(2):
            r = self.client.post('/api/v1/push/subscriptions', json.dumps(SUB), content_type='application/json')
            self.assertEqual(r.status_code, 201)
        self.assertEqual(PushSubscription.objects.count(), 1)

    @mock.patch('prestop_push.sender.webpush')
    @mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip()})
    def test_due_reminder_is_sent_once(self, _trips, push):
        self.watch()
        watcher.tick(NOW + timedelta(minutes=15, seconds=5))
        watcher.tick(NOW + timedelta(minutes=15, seconds=25))
        self.assertEqual(push.call_count, 1)
        self.assertEqual(json.loads(push.call_args.kwargs['data'])['tag'], 'board:x')

    @mock.patch('prestop_push.sender.webpush', side_effect=WebPushException('gone', response=SimpleNamespace(status_code=410)))
    @mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip()})
    def test_gone_subscription_is_deleted(self, _trips, _push):
        self.watch()
        watcher.tick(NOW + timedelta(minutes=16))
        self.assertFalse(PushSubscription.objects.exists())
        self.assertFalse(Watch.objects.exists())

    @mock.patch('prestop_push.sender.webpush')
    def test_live_update_on_two_minute_delay_change(self, push):
        self.watch(last_delay=60, sent_reminder=False)
        with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(delay=200)}):
            watcher.tick(NOW)
        payload = json.loads(push.call_args.kwargs['data'])
        self.assertEqual((payload['tag'], payload['renotify'], payload['kind']), ('board:x', False, 'update'))

    @mock.patch('prestop_push.sender.webpush')
    def test_throttles_small_changes(self, push):
        self.watch(last_delay=60)
        for i, delay in enumerate([90, 120, 150]):
            with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(delay=delay)}):
                watcher.tick(NOW + timedelta(seconds=20 * i))
        self.assertEqual(push.call_count, 0)
        with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(delay=300)}):
            watcher.tick(NOW + timedelta(seconds=80))
        with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(delay=420)}):
            watcher.tick(NOW + timedelta(seconds=140))  # within 3 min of the last push
        self.assertEqual(push.call_count, 1)

    @mock.patch('prestop_push.sender.webpush')
    def test_cancellation_always_notifies(self, push):
        self.watch(last_delay=0, last_sent=NOW)
        with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(canceled=True)}):
            watcher.tick(NOW + timedelta(seconds=30))
        self.assertTrue(json.loads(push.call_args.kwargs['data'])['renotify'])

    @mock.patch('prestop_push.sender.webpush')
    @mock.patch('prestop_push.watcher.load_trips', return_value={})
    def test_expired_watches_are_removed(self, _trips, push):
        self.watch()
        watcher.tick(NOW + timedelta(hours=2))
        self.assertFalse(Watch.objects.exists())
        push.assert_not_called()

    @mock.patch('prestop_push.sender.webpush')
    def test_first_look_at_a_trip_is_a_baseline_not_a_change(self, push):
        self.watch()
        with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(delay=600)}):
            watcher.tick(NOW)
        push.assert_not_called()
        self.assertEqual(Watch.objects.get().last_delay, 600)

    @mock.patch('prestop_push.sender.webpush')
    def test_update_says_when_the_bus_now_leaves(self, push):
        self.watch(last_delay=0)
        with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(delay=180)}):
            watcher.tick(NOW + timedelta(minutes=5))
        body = json.loads(push.call_args.kwargs['data'])['body']
        self.assertIn('Bavarski dvor', body)
        self.assertIn('10:23', body)  # Ljubljana time
        self.assertIn('+3 min', body)

    @mock.patch('prestop_push.sender.webpush')
    def test_no_live_updates_after_the_bus_left(self, push):
        self.watch(last_delay=0, sent_reminder=True)
        with mock.patch('prestop_push.watcher.load_trips', return_value={'LPP:t1': trip(delay=300)}):
            watcher.tick(NOW + timedelta(minutes=26))
        push.assert_not_called()


class PushApiTests(TestCase):
    def post(self, path, body):
        return self.client.post(path, json.dumps(body), content_type='application/json')

    def test_only_browser_push_services_are_accepted(self):
        # Spec 2026-10-18 A6: the server POSTs to the endpoint, so it must be a real push service, not any URL.
        for endpoint in ('https://evil.example/x', 'https://127.0.0.1/x', 'https://169.254.169.254/latest', 'https://fcm.googleapis.com:6379/x',
                         'https://fcm.googleapis.com.evil.example/x', 'https://user@fcm.googleapis.com/x', 'http://fcm.googleapis.com/x'):
            r = self.post('/api/v1/push/subscriptions', {**SUB, 'endpoint': endpoint})
            self.assertEqual(r.status_code, 422, endpoint)
        for endpoint in ('https://fcm.googleapis.com/fcm/send/a', 'https://updates.push.services.mozilla.com/wpush/v2/a',
                         'https://web.push.apple.com/a', 'https://wns2-db5p.notify.windows.com/w/?token=a'):
            self.assertEqual(self.post('/api/v1/push/subscriptions', {**SUB, 'endpoint': endpoint}).status_code, 201, endpoint)

    def test_a_stored_endpoint_off_the_push_services_is_never_sent_to(self):
        from prestop_push import sender
        sub = PushSubscription.objects.create(endpoint='https://evil.example/x', p256dh='BNc' + 'A' * 84, auth='x' * 22)
        with mock.patch.object(sender, 'webpush') as webpush:
            self.assertEqual(sender.send(sub, {'title': 't'}), 'gone')
        webpush.assert_not_called()

    def test_rejects_a_non_https_endpoint(self):
        r = self.post('/api/v1/push/subscriptions', {**SUB, 'endpoint': 'http://push.example/abc'})
        self.assertEqual(r.status_code, 422)

    def test_watch_lifecycle(self):
        self.post('/api/v1/push/subscriptions', SUB)
        watch = {'endpoint': SUB['endpoint'], 'id': 'board:x', 'kind': 'departure', 'notifyAt': NOW.isoformat(), 'title': '6', 'body': '08:20',
                 'url': '/stations/LPP%3Aa', 'tripIds': ['LPP:t1'], 'stopId': 'LPP:a', 'scheduledAt': (NOW + timedelta(minutes=5)).isoformat()}
        for _ in range(2):
            self.assertEqual(self.post('/api/v1/push/watches', watch).status_code, 201)
        self.assertEqual(Watch.objects.get().expires_at, NOW + timedelta(minutes=35))
        r = self.client.delete('/api/v1/push/watches/board:x?endpoint=' + SUB['endpoint'])
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Watch.objects.exists())

    def test_watch_needs_a_known_subscription(self):
        r = self.post('/api/v1/push/watches', {'endpoint': 'https://fcm.googleapis.com/fcm/send/zzz', 'id': 'x', 'kind': 'journey', 'notifyAt': NOW.isoformat(),
                                               'title': 't', 'body': 'b', 'url': '/', 'tripIds': []})
        self.assertEqual(r.status_code, 404)

    def test_watch_rejects_an_external_url(self):
        self.post('/api/v1/push/subscriptions', SUB)
        r = self.post('/api/v1/push/watches', {'endpoint': SUB['endpoint'], 'id': 'x', 'kind': 'journey', 'notifyAt': NOW.isoformat(),
                                               'title': 't', 'body': 'b', 'url': 'https://evil.example/', 'tripIds': []})
        self.assertEqual(r.status_code, 422)

    def test_at_most_fifty_watches_per_subscription(self):
        self.post('/api/v1/push/subscriptions', SUB)
        base = {'endpoint': SUB['endpoint'], 'kind': 'journey', 'notifyAt': NOW.isoformat(), 'title': 't', 'body': 'b', 'url': '/', 'tripIds': []}
        for i in range(50):
            self.assertEqual(self.post('/api/v1/push/watches', {**base, 'id': f'w{i}'}).status_code, 201)
        self.assertEqual(self.post('/api/v1/push/watches', {**base, 'id': 'w50'}).status_code, 422)
        self.assertEqual(self.post('/api/v1/push/watches', {**base, 'id': 'w3'}).status_code, 201)  # updating one is fine

    @override_settings(PRESTOP_VAPID_PRIVATE_KEY='test-key')
    @mock.patch('prestop_push.sender.webpush')
    def test_test_notification_goes_to_that_subscription(self, push):
        self.post('/api/v1/push/subscriptions', SUB)
        r = self.post('/api/v1/push/test', {'endpoint': SUB['endpoint']})
        self.assertEqual((r.status_code, r.json()['result']), (200, 'ok'))
        self.assertEqual(push.call_args.kwargs['subscription_info']['endpoint'], SUB['endpoint'])

    def test_a_rotated_subscription_keeps_its_reminders(self):
        self.post('/api/v1/push/subscriptions', SUB)
        self.post('/api/v1/push/watches', {'endpoint': SUB['endpoint'], 'id': 'board:x', 'kind': 'departure', 'notifyAt': NOW.isoformat(),
                                           'title': 't', 'body': 'b', 'url': '/', 'tripIds': []})
        rotated = {**SUB, 'endpoint': 'https://fcm.googleapis.com/fcm/send/new', 'previousEndpoint': SUB['endpoint']}
        self.assertEqual(self.post('/api/v1/push/subscriptions', rotated).status_code, 201)
        self.assertEqual(list(PushSubscription.objects.values_list('endpoint', flat=True)), ['https://fcm.googleapis.com/fcm/send/new'])
        self.assertEqual(Watch.objects.get().subscription.endpoint, 'https://fcm.googleapis.com/fcm/send/new')

    def test_unsubscribe(self):
        self.post('/api/v1/push/subscriptions', SUB)
        r = self.client.delete('/api/v1/push/subscriptions', json.dumps({'endpoint': SUB['endpoint']}), content_type='application/json')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(PushSubscription.objects.exists())


class CapabilityTests(TestCase):
    def setUp(self):
        from prestop_api import sources
        from prestop_api.tests.test_views import fixed
        for name, value in {'routes': fixed({}), 'rentals': fixed([])}.items():
            patch = mock.patch.object(sources, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    @override_settings(PRESTOP_VAPID_PUBLIC_KEY='', PRESTOP_VAPID_PRIVATE_KEY='')
    def test_push_is_off_without_keys(self):
        data = self.client.get('/api/v1/capabilities').json()['data']
        self.assertEqual((data['push'], data.get('pushKey')), (False, None))

    @override_settings(PRESTOP_VAPID_PUBLIC_KEY='BPublic', PRESTOP_VAPID_PRIVATE_KEY='private')
    def test_push_offers_only_the_public_key(self):
        data = self.client.get('/api/v1/capabilities').json()['data']
        self.assertEqual((data['push'], data['pushKey']), (True, 'BPublic'))
        self.assertNotIn('private', json.dumps(data))


class VapidKeyTests(TestCase):
    def test_generated_keys_sign_pushes(self):
        import base64
        from io import StringIO
        from django.core.management import call_command
        from py_vapid import Vapid
        out = StringIO()
        call_command('vapid_keys', stdout=out)
        env = dict(line.split('=', 1) for line in out.getvalue().split() if '=' in line)
        public = base64.urlsafe_b64decode(env['PRESTOP_VAPID_PUBLIC_KEY'] + '==')
        self.assertEqual((len(public), public[0]), (65, 4))  # uncompressed P-256 point: the browser's applicationServerKey
        vapid = Vapid.from_string(env['PRESTOP_VAPID_PRIVATE_KEY'])
        self.assertIn('Authorization', vapid.sign({'sub': 'mailto:a@b.si', 'aud': 'https://push.example'}))

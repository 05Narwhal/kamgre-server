import json
import os
import tempfile
from unittest import mock

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from prestop_api import traffic

def error(response):
    return json.loads(response.content)['error']


GUARD = dict(PRESTOP_TRAFFIC_GUARD=True, PRESTOP_CLIENT_IP_HEADER='CF-Connecting-IP',
             PRESTOP_TRAFFIC_REDIS_URL='redis://127.0.0.1:6379/15', PRESTOP_TRAFFIC_PER_MINUTE=5,
             PRESTOP_TRAFFIC_MAX_ACTIVE=3, PRESTOP_TRAFFIC_HOURLY_MB=1, SESSION_COOKIE_SECURE=False)


class TrafficGuardTests(SimpleTestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.settings = override_settings(**GUARD, PRESTOP_TRAFFIC_STATE_DIR=self.state)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.body = b'{}'
        self.guard = traffic.TrafficGuardMiddleware(lambda request: JsonResponse({'x': self.body.decode()}))
        self.guard.redis.flushdb()
        self.factory = RequestFactory()

    def get(self, ip='198.51.100.1', cookies=None, path='/api/v1/stops'):
        request = self.factory.get(path, **({'HTTP_CF_CONNECTING_IP': ip} if ip else {}))
        request.COOKIES.update(cookies or {})
        return self.guard(request)

    def admitted(self, ip='198.51.100.1'):
        return {traffic.COOKIE: self.get(ip).cookies[traffic.COOKIE].value}

    def test_normal_requests_pass_and_admit_the_browser(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertIn(traffic.COOKIE, response.cookies)
        # An admitted browser is not re-admitted on every request.
        self.assertNotIn(traffic.COOKIE, self.get(cookies=self.admitted()).cookies)

    def test_a_client_over_its_rate_gets_429(self):
        codes = [self.get().status_code for _ in range(7)]
        self.assertEqual(codes, [200] * 5 + [429] * 2)
        self.assertEqual(self.get(ip='198.51.100.2').status_code, 200)  # others are unaffected

    def test_costly_endpoints_have_their_own_limit_per_client(self):
        # Spec 2026-10-18 A6: planning is limited well below the overall rate.
        with override_settings(PRESTOP_TRAFFIC_PER_MINUTE=100):
            guard = traffic.TrafficGuardMiddleware(lambda request: JsonResponse({}))
            guard.route_limits = (('/api/v1/journeys', 'plan', 3, 60),)
            request = lambda ip='198.51.100.1', path='/api/v1/journeys': guard(self.factory.post(path, HTTP_CF_CONNECTING_IP=ip))
            self.assertEqual([request().status_code for _ in range(5)], [200] * 3 + [429] * 2)
            self.assertEqual(request(path='/api/v1/stops').status_code, 200)  # other requests go on
            self.assertEqual(request(ip='198.51.100.2').status_code, 200)    # other clients too
            self.assertEqual(error(request())['code'], 'RATE_LIMITED')

    def test_busy_flag_refuses_new_visitors_only(self):
        cookies = self.admitted()
        open(os.path.join(self.state, 'busy'), 'w').close()
        self.guard._decision = (0.0, None)
        refused = self.get(ip='198.51.100.9')
        self.assertEqual(refused.status_code, 503)
        self.assertEqual(error(refused)['code'], 'BUSY')
        self.assertEqual(refused['Retry-After'], '900')
        self.assertEqual(self.get(cookies=cookies).status_code, 200)

    def test_forged_cookie_does_not_admit(self):
        open(os.path.join(self.state, 'busy'), 'w').close()
        self.assertEqual(self.get(cookies={traffic.COOKIE: '1'}).status_code, 503)

    def test_too_many_active_clients_refuses_new_ones(self):
        cookies = self.admitted('198.51.100.1')
        for n in range(2, 6):
            self.get(ip=f'198.51.100.{n}')
        self.guard._decision = (0.0, None)
        self.assertEqual(self.get(ip='198.51.100.50').status_code, 503)
        self.assertEqual(self.get(cookies=cookies).status_code, 200)

    def test_hourly_output_budget_refuses_new_visitors(self):
        self.body = b'x' * 1_100_000
        cookies = self.admitted()
        self.guard._decision = (0.0, None)
        self.assertEqual(self.get(ip='198.51.100.7').status_code, 503)
        self.assertEqual(self.get(cookies=cookies).status_code, 200)

    def test_stopped_refuses_everyone_but_the_server_itself(self):
        cookies = self.admitted()
        open(os.path.join(self.state, 'stopped'), 'w').close()
        response = self.get(cookies=cookies)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(error(response)['code'], 'PAUSED')
        self.assertEqual(self.get(ip=None, path='/api/v1/health').status_code, 200)  # watchdog

    def test_slovenian_message(self):
        open(os.path.join(self.state, 'stopped'), 'w').close()
        request = self.factory.get('/api/v1/stops', HTTP_CF_CONNECTING_IP='198.51.100.1', HTTP_ACCEPT_LANGUAGE='sl')
        self.assertIn('ustavljen', error(self.guard(request))['message'])

    def test_redis_failure_lets_requests_through(self):
        import redis
        with mock.patch.object(self.guard, '_count', side_effect=redis.ConnectionError('down')):
            self.assertEqual(self.get().status_code, 200)

    def test_disabled_guard_does_nothing(self):
        with override_settings(PRESTOP_TRAFFIC_GUARD=False):
            guard = traffic.TrafficGuardMiddleware(lambda request: JsonResponse({}))
        open(os.path.join(self.state, 'stopped'), 'w').close()
        request = self.factory.get('/api/v1/stops', HTTP_CF_CONNECTING_IP='198.51.100.1')
        self.assertEqual(guard(request).status_code, 200)


class PlanSlotTests(SimpleTestCase):
    def test_plans_beyond_the_slots_get_a_retryable_503_instead_of_tying_up_the_worker(self):
        # Spec 2026-10-18 A6: slow OTP plans must not take every gunicorn thread.
        from prestop_api import views
        request = RequestFactory().post('/api/v1/journeys', data='{}', content_type='application/json')
        taken = [views._plan_slots.acquire(timeout=1) for _ in range(views.PLAN_SLOTS)]
        try:
            with mock.patch.object(views, 'PLAN_WAIT', 0.05):
                response = views.journeys(request)
        finally:
            for _ in taken:
                views._plan_slots.release()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(error(response)['code'], 'BUSY')
        self.assertTrue(error(response)['retryable'])

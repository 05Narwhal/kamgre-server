"""Usage counts (analytics.py). The report on them is the usage tab of server:top (test_server_top.py)."""
from datetime import datetime, timedelta

from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve

from prestop_api import analytics
from prestop_api.models import AnalyticsDay, AnalyticsHour

COUNTING = dict(PRESTOP_ANALYTICS=True, PRESTOP_ANALYTICS_REDIS_URL='redis://127.0.0.1:6379/14', PRESTOP_CLIENT_IP_HEADER='CF-Connecting-IP',
                ROOT_URLCONF='ojpp_core.urls_prestop')
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36 Edg/141.0'


@override_settings(**COUNTING)
class CountingTests(TestCase):
    def setUp(self):
        self.r = analytics._redis()
        self.r.flushdb()
        analytics._salt.__dict__.clear()
        self.factory = RequestFactory()
        self.status = 200
        self.middleware = analytics.AnalyticsMiddleware(lambda request: JsonResponse({}, status=self.status))

    def call(self, path, ip='198.51.100.7', agent=IPHONE, **params):
        request = self.factory.get(path, params, **({'HTTP_CF_CONNECTING_IP': ip} if ip else {}), HTTP_USER_AGENT=agent)
        request.resolver_match = resolve(path) if path.startswith('/api/v1/') else None
        return self.middleware(request)

    def test_requests_are_counted_by_route_pattern_and_status_class_never_by_path(self):
        self.call('/api/v1/stops/IJPP:123/board')
        self.call('/api/v1/stops/LPP:9/board')
        self.status = 503
        self.call('/api/v1/journeys')
        self.call('/api/v1/stops', ip=None)  # the server itself
        self.call('/admin/')  # not the API
        self.assertEqual(analytics.flush(), 2)
        rows = {(r.route, r.status): r.count for r in AnalyticsHour.objects.all()}
        self.assertEqual(rows, {('stops/*/board', '2xx'): 2, ('journeys', '5xx'): 1})
        self.assertEqual(sum(AnalyticsHour.objects.get(route='stops/*/board').buckets), 2)
        self.assertEqual(self.r.keys('analytics:h:*'), [])

    def test_flushing_twice_adds_and_counts_made_meanwhile_are_kept(self):
        self.call('/api/v1/vehicles')
        analytics.flush()
        self.call('/api/v1/vehicles')
        self.call('/api/v1/vehicles')
        analytics.flush()
        self.assertEqual(AnalyticsHour.objects.get(route='vehicles').count, 3)

    def test_a_visitor_counts_once_a_day_and_cannot_be_followed_to_the_next_day(self):
        for _ in range(3):
            self.call('/api/v1/vehicles')
        self.call('/api/v1/vehicles', ip='203.0.113.9', agent=WINDOWS, display='app')
        day = analytics.local_day(datetime.now().timestamp())
        self.assertEqual(self.r.pfcount(f'analytics:uv:{day}'), 2)
        today = analytics.visitor(self.r, '198.51.100.7', IPHONE, day)
        tomorrow = analytics.visitor(self.r, '198.51.100.7', IPHONE, day + timedelta(days=1))
        self.assertNotEqual(today, tomorrow)  # each day has its own random salt
        self.assertGreater(self.r.ttl(f'analytics:salt:{day}'), 0)

    def test_the_night_saves_the_day_and_deletes_its_salt(self):
        yesterday = datetime.now().timestamp() - 86400
        day = analytics.local_day(yesterday)
        for ip, agent in (('198.51.100.7', IPHONE), ('203.0.113.9', WINDOWS), ('203.0.113.10', WINDOWS)):
            analytics.record(self.r, 'vehicles', 200, 0.05, ip, agent, now=yesterday)
        analytics.hello('198.51.100.7', IPHONE, now=yesterday)
        analytics.hello('198.51.100.7', IPHONE, now=yesterday)  # once per visitor
        saved = analytics.nightly()
        self.assertEqual(saved, [{'day': day.isoformat(), 'visitors': 3, 'new': 1}])
        row = AnalyticsDay.objects.get(day=day)
        self.assertEqual((row.platforms, row.new_users), ({'ios': 1, 'desktop': 2}, 1))
        self.assertFalse(self.r.exists(f'analytics:salt:{day}', f'analytics:uv:{day}', f'analytics:new:{day}'))
        self.assertTrue(bytes(row.visitors_hll))

    def test_hello_counts_a_new_user(self):
        response = self.client.post('/api/v1/stats/hello', HTTP_CF_CONNECTING_IP='198.51.100.7', HTTP_USER_AGENT=IPHONE)
        self.assertEqual(response.status_code, 204)
        day = analytics.local_day(datetime.now().timestamp())
        self.assertEqual(self.r.pfcount(f'analytics:new:{day}'), 1)

    def test_robots_and_test_browsers_are_requests_but_never_people(self):
        robots = ['Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                  'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0) Chrome/116.0 Safari/537.36',
                  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 HeadlessChrome/141.0 Safari/537.36',
                  'Mozilla/5.0 (Linux; Android 11; moto g power) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36 Chrome-Lighthouse',
                  'Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)', 'curl/8.5.0', 'python-requests/2.32', '']
        for n, agent in enumerate(robots):
            self.call('/api/v1/vehicles', ip=f'203.0.113.{n}', agent=agent)
            self.client.post('/api/v1/stats/hello', HTTP_CF_CONNECTING_IP=f'203.0.113.{n}', HTTP_USER_AGENT=agent)
        cubot = 'Mozilla/5.0 (Linux; Android 10; CUBOT X30) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36'
        self.call('/api/v1/vehicles', agent=cubot)  # a phone, not a robot
        self.client.post('/api/v1/stats/hello', HTTP_CF_CONNECTING_IP='198.51.100.7', HTTP_USER_AGENT=cubot)
        day = analytics.local_day(datetime.now().timestamp())
        self.assertEqual((self.r.pfcount(f'analytics:uv:{day}'), self.r.pfcount(f'analytics:new:{day}')), (1, 1))
        analytics.flush()
        self.assertEqual(AnalyticsHour.objects.get(route='vehicles').count, len(robots) + 1)

"""Usage counts (analytics.py) and the server:stats report (analytics_report.py)."""
from datetime import date, datetime, timedelta, timezone

from django.http import JsonResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve

from prestop_api import analytics
from prestop_api.analytics_report import gather, p95, parse_period, period, render, report
from prestop_api.models import AnalyticsDay, AnalyticsHour

COUNTING = dict(PRESTOP_ANALYTICS=True, PRESTOP_ANALYTICS_REDIS_URL='redis://127.0.0.1:6379/14', PRESTOP_CLIENT_IP_HEADER='CF-Connecting-IP',
                ROOT_URLCONF='ojpp_core.urls_prestop')
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36 Edg/141.0'
NOW = datetime(2026, 10, 16, 14, 5, tzinfo=analytics.LOCAL)  # a Friday


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
        self.assertEqual(analytics.union([bytes(row.visitors_hll)]), 3)

    def test_hello_counts_a_new_user(self):
        response = self.client.post('/api/v1/stats/hello', HTTP_CF_CONNECTING_IP='198.51.100.7', HTTP_USER_AGENT=IPHONE)
        self.assertEqual(response.status_code, 204)
        day = analytics.local_day(datetime.now().timestamp())
        self.assertEqual(self.r.pfcount(f'analytics:new:{day}'), 1)


class PeriodTests(TestCase):
    def test_periods_and_the_ones_before(self):
        today = period('today', NOW)
        self.assertEqual((today.start.isoformat(), today.prev_start.date(), today.prev_end.hour, today.step),
                         ('2026-10-16T00:00:00+02:00', date(2026, 10, 15), 14, 'hour'))
        week = period('week', NOW)
        self.assertEqual((week.start.date(), week.prev_start.date(), week.prev_end.date()), (date(2026, 10, 12), date(2026, 10, 5), date(2026, 10, 9)))
        month = period('month', NOW)
        self.assertEqual((month.start.date(), month.prev_start.date(), month.prev_end.date()), (date(2026, 10, 1), date(2026, 9, 1), date(2026, 9, 16)))
        # 31 March compares with all of February, not with 3 March.
        march = period('month', datetime(2027, 3, 31, 12, tzinfo=analytics.LOCAL))
        self.assertEqual((march.prev_start.date(), march.prev_end.date()), (date(2027, 2, 1), date(2027, 3, 1)))
        self.assertIsNone(period('all', NOW, NOW - timedelta(days=3)).prev_start)

    def test_period_words(self):
        self.assertEqual([parse_period(w) for w in ('', 'today', 'this week', 'This Month', 'all')], ['today', 'today', 'week', 'month', 'all'])
        with self.assertRaises(ValueError):
            parse_period('fortnight')

    def test_p95_from_buckets(self):
        self.assertIsNone(p95([0] * 8))
        self.assertEqual(p95([90, 6, 4, 0, 0, 0, 0, 0]), 100)
        self.assertEqual(p95([0, 0, 0, 0, 0, 0, 0, 5]), -1)


class ReportTests(TestCase):
    def test_the_report_renders_with_no_data(self):
        for name in ('today', 'week', 'month', 'all'):
            text = render(gather(period(name, NOW), None))
            self.assertIn('Visitors', text)
            self.assertIn('no requests yet', text)
            self.assertTrue(all(len(line) <= 80 for line in text.splitlines()), text)

    def test_the_report_shows_requests_features_and_the_change(self):
        hour = lambda h, d=0: datetime(2026, 10, 16 - d, h, tzinfo=analytics.LOCAL).astimezone(timezone.utc)
        AnalyticsHour.objects.create(hour=hour(8), route='stops/*/board', status='2xx', count=300, ms=30000, buckets=[200, 80, 20, 0, 0, 0, 0, 0])
        AnalyticsHour.objects.create(hour=hour(9), route='journeys', status='5xx', count=10, ms=5000, buckets=[0, 0, 0, 0, 10, 0, 0, 0])
        AnalyticsHour.objects.create(hour=hour(9), route='hop/presence', status='2xx', count=5000, ms=0, buckets=[5000, 0, 0, 0, 0, 0, 0, 0])
        AnalyticsHour.objects.create(hour=hour(8, 1), route='stops/*/board', status='2xx', count=155, ms=0, buckets=[155, 0, 0, 0, 0, 0, 0, 0])
        text = render(gather(period('today', NOW), None))
        self.assertRegex(text, r'Requests\s+310   ▲ 100 %')  # Hop presence pings are not requests here
        self.assertRegex(text, r'Errors\s+3 %   server \(5xx\)')
        self.assertIn('5,000 presence pings', text)
        self.assertRegex(text, r'Boards\s+300\s+97 %\s+≤200 ms')
        self.assertRegex(text, r'08:00  #+\s+300')
        self.assertTrue(all(len(line) <= 80 for line in text.splitlines()), text)

    @override_settings(**COUNTING)
    def test_report_reads_todays_visitors_from_redis(self):
        r = analytics._redis()
        r.flushdb()
        analytics.record(r, 'vehicles', 200, 0.01, '198.51.100.7', IPHONE, display='app')
        self.assertRegex(report('today'), r'Visitors\s+1\b')

"""The usage tab of server:top (deploy/oracle/server/top.py), whose SQL runs here against the real tables, and the
way its graphs and buttons answer the mouse."""
import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock, skipUnless

from django.db import connection
from django.test import SimpleTestCase, TestCase

from prestop_api.models import AnalyticsDay, AnalyticsHour

TOP_PY = Path(__file__).resolve().parents[3] / 'deploy' / 'oracle' / 'server' / 'top.py'


def load_top():
    spec = importlib.util.spec_from_file_location('prestop_top', TOP_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


top = load_top() if TOP_PY.exists() else None
NOW = datetime(2026, 10, 16, 14, 5, tzinfo=top.TZ) if top else None  # a Friday


def run_sql(sql):
    """Rows the way psql -At -F'|' prints them."""
    with connection.cursor() as c:
        c.execute(sql.replace('%', '%%'))
        return ['|'.join('' if v is None else str(v) for v in row) for row in c.fetchall()]


def text(lines):
    return '\n'.join(''.join(t for t, _ in line) for line in lines)


@skipUnless(TOP_PY.exists(), 'the deploy bundle is not next to this checkout')
class PeriodTests(SimpleTestCase):
    def test_periods_and_the_ones_before(self):
        start, _, prev_start, prev_end = top.usage_period('today', NOW)
        self.assertEqual((start.isoformat(), prev_start.date(), prev_end.hour), ('2026-10-16T00:00:00+02:00', date(2026, 10, 15), 14))
        start, _, prev_start, prev_end = top.usage_period('week', NOW)
        self.assertEqual((start.date(), prev_start.date(), prev_end.date()), (date(2026, 10, 12), date(2026, 10, 5), date(2026, 10, 9)))
        start, _, prev_start, prev_end = top.usage_period('month', NOW)
        self.assertEqual((start.date(), prev_start.date(), prev_end.date()), (date(2026, 10, 1), date(2026, 9, 1), date(2026, 9, 16)))
        # 31 March compares with all of February, not with 3 March.
        _, _, prev_start, prev_end = top.usage_period('month', datetime(2027, 3, 31, 12, tzinfo=top.TZ))
        self.assertEqual((prev_start.date(), prev_end.date()), (date(2027, 2, 1), date(2027, 3, 1)))
        self.assertIsNone(top.usage_period('all', NOW)[2])

    def test_p95_from_buckets(self):
        self.assertIsNone(top.p95([0] * 8))
        self.assertEqual(top.p95([90, 6, 4, 0, 0, 0, 0, 0]), 100)
        self.assertEqual(top.p95([0, 0, 0, 0, 0, 0, 0, 5]), -1)

    def test_days_become_weeks_then_months_when_they_do_not_fit(self):
        days = [{'day': date(2026, 1, 1) + timedelta(days=i)} for i in range(120)]
        self.assertEqual(len(top.group_days(days, 120)), 120)
        weeks = top.group_days(days, 40)
        self.assertTrue(18 <= len(weeks) <= 40)
        self.assertEqual(sum(len(g[2]) for g in weeks), 120)
        self.assertEqual(len(top.group_days(days, 10)), 4)


@skipUnless(TOP_PY.exists(), 'the deploy bundle is not next to this checkout')
class UsageTests(TestCase):
    def setUp(self):
        top.UI['period'] = 'today'

    def hour(self, h, back=0):
        return (datetime(2026, 10, 16, h, tzinfo=top.TZ) - timedelta(days=back)).astimezone(timezone.utc)

    def fill(self):
        AnalyticsHour.objects.create(hour=self.hour(8), route='stops/*/board', status='2xx', count=300, ms=30000, buckets=[200, 80, 20, 0, 0, 0, 0, 0])
        AnalyticsHour.objects.create(hour=self.hour(9), route='journeys', status='5xx', count=10, ms=5000, buckets=[0, 0, 0, 0, 10, 0, 0, 0])
        AnalyticsHour.objects.create(hour=self.hour(9), route='hop/presence', status='2xx', count=5000, ms=0, buckets=[5000, 0, 0, 0, 0, 0, 0, 0])
        AnalyticsHour.objects.create(hour=self.hour(8, 1), route='stops/*/board', status='2xx', count=155, ms=0, buckets=[155, 0, 0, 0, 0, 0, 0, 0])
        AnalyticsDay.objects.create(day=date(2026, 10, 15), visitors=40, new_users=5, platforms={'ios': 30, 'desktop': 10, 'app': 6, 'browser': 34})

    def usage(self, live=None):
        return top.usage(query=run_sql, live=lambda today: live or {}, now=NOW)

    def test_requests_leave_out_presence_pings_and_compare_with_yesterday(self):
        self.fill()
        u = self.usage()
        self.assertEqual((u['requests'], u['errors'], u['prev_requests'], u['presence']), (310, 10, 155, 5000))
        self.assertEqual(u['hours'], {8: (300, 0), 9: (10, 10)})
        self.assertEqual([(n, x['count']) for n, x in u['features']], [('Boards', 300), ('Planner', 10)])
        self.assertEqual(top.p95(dict(u['routes'])['stops/*/board']['buckets']), 200)
        self.assertEqual(u['series'][-1]['requests'], 310)

    def test_todays_users_come_from_redis_and_days_not_saved_yet_are_merged(self):
        self.fill()
        u = self.usage(live={date(2026, 10, 16): (12, 3, {'ios': 12}), date(2026, 10, 15): (50, 2, {'ios': 35})})
        today, yesterday = u['series'][-1], u['series'][-2]
        self.assertEqual((today['users'], today['new'], today['joined']), (12, 3, 10))
        self.assertEqual((yesterday['users'], yesterday['new'], yesterday['platforms']['ios']), (50, 7, 35))

    def test_redis_being_down_still_shows_the_saved_days(self):
        self.fill()

        def down(_):
            raise OSError('connection refused')
        u = top.usage(query=run_sql, live=down, now=NOW)
        self.assertEqual(u['live_error'], 'connection refused')
        self.assertEqual(u['series'][-2]['users'], 40)

    def test_a_period_shows_users_a_day_since_days_cannot_be_linked(self):
        for i, n in enumerate((10, 20, 30)):
            AnalyticsDay.objects.create(day=date(2026, 10, 13) + timedelta(days=i), visitors=n, new_users=1)
        top.UI['period'] = 'week'
        tiles = {t[0]: t for t in top.usage_tiles(self.usage(live={date(2026, 10, 16): (500, 1, {})}))}
        self.assertEqual(tiles['USERS A DAY'][1], '20')  # the finished days; today is not over yet
        self.assertEqual(tiles['NEW USERS'][1], '4')
        self.assertEqual(tiles['ALL USERS'][1], '4')

    def test_the_tab_draws_at_every_width_for_every_period_even_with_no_data(self):
        for filled in (False, True):
            if filled:
                self.fill()
            for name, _ in top.PERIODS:
                top.UI['period'] = name
                top.POLL['usage'] = type('P', (), {'value': self.usage(), 'error': None})()
                for w in (80, 104, 120, 160):
                    drawn = text(top.fit(x, w) for x in top.tab_usage(w))
                    for word in ('Users per day', 'New users per day', 'Requests per day', 'All users so far', 'Features', 'Top endpoints', 'Platforms'):
                        self.assertIn(word, drawn)
                    self.assertTrue(all(len(x) == w for x in drawn.splitlines()))
        top.POLL.pop('usage')


@skipUnless(TOP_PY.exists(), 'the deploy bundle is not next to this checkout')
class MouseTests(SimpleTestCase):
    def view(self, lines):
        return {'regions': top.regions(lines), 'mouse': None}

    def test_a_graph_keeps_its_hover_data_through_panel_and_columns(self):
        chart = lambda cw: top.panel('Chart', top.bars([5, 9], cw - 4, 3, labels=['a', 'b'], name='items'), cw)  # noqa: E731
        lines = [top.fit(x, 120) for x in top.columns(120, [chart], [chart])]
        view = self.view(lines)
        right = [x for x0, x1, _, x in view['regions'][1] if x0 > 60]
        self.assertTrue(right)
        self.assertEqual(right[0].tip(), ['5  items', 'a'])

    def test_hover_lights_the_whole_column_and_shows_the_tooltip_beside_the_pointer(self):
        lines = [top.fit(x, 60) for x in top.bars([5, 9], 40, 4, labels=['a', 'b'], name='items')]
        view = self.view(lines)
        x0, x1, _, hot = view['regions'][0][-1]
        self.assertEqual(hot.mark, False)  # the gap reacts but stays dark
        x0 = view['regions'][0][-2][0]
        view['mouse'] = (x0, 1)
        out = top.hovered([list(x) for x in lines] + [top.blank(60) for _ in range(6)], view, 60, 11)
        self.assertIn('9  items', text(out))
        styled = [s for line in out[:4] for _, s in line if s == 'hover']
        self.assertEqual(len(styled), 4)  # the bar's column, in all four rows

    def test_the_tooltip_flips_to_the_left_at_the_right_edge(self):
        lines = [top.blank(30) for _ in range(8)]
        out = top.with_tip(lines, ['hello'], (28, 3), 30, 8)
        row = text([out[3]])
        self.assertEqual(len(row), 30)
        self.assertLess(row.index('hello'), 28)

    def test_every_graph_answers_on_a_panel_built_from_histories(self):
        h = top.Hist()
        for v in (1, 2, 3):
            h.append(v)
        line = top.spark(h, 3, name='things')
        tip = line[-1][1].tip()
        self.assertEqual(tip[0], '3  things')
        self.assertRegex(tip[1], r'\d\d:\d\d:\d\d')
        rows = top.area(h, 12, 3, name='things')
        self.assertTrue(any(isinstance(s, top.Hot) for _, s in rows[0]))
        self.assertEqual(top.meter(40, 10)[0][1].tip, ['40.0 %'])

    def test_buttons_do_what_their_keys_do(self):
        view = {'tab': 0, 'scroll': 0, 'help': False, 'scrolls': {}}
        top.press(top.go('logs'), view, 20)
        self.assertEqual(view['tab'], [k for k, _ in top.TABS].index('logs'))
        top.press('e', view, 20)
        self.assertTrue(top.LOGS['errors_only'])
        top.LOGS['errors_only'] = False
        self.assertFalse(top.press('?', view, 20))
        self.assertTrue(view['help'])
        self.assertTrue(top.press('q', view, 20))

    def test_the_footer_and_tabs_are_clickable(self):
        top.UI['paused'] = False
        foot = top.regions([top.footer(100, False, True)])[0]
        acts = [s.act for _, _, _, s in foot if s.act is not None]
        self.assertIn('p', acts)
        self.assertIn('q', acts)
        with mock.patch.object(top, 'alerts', lambda: []):
            line = top.tabbar(100, 'usage')
        self.assertEqual(len({s.key for _, _, _, s in top.regions([line])[0]}), len(top.TABS))
        self.assertIn('Usage', text([line]))

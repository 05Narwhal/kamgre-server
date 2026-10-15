"""The `manage.py stats` report (yarn server:stats): readable in a plain 80-column terminal, no colour needed.

period() is the date maths, gather() reads AnalyticsHour / AnalyticsDay (plus today's figures still in Redis),
render() turns the result into text. See analytics.py for what is counted.
"""
import base64
import fnmatch
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from django.db.models import Min

from . import analytics
from .analytics import BUCKETS_MS, LOCAL

WIDTH = 80
PERIODS = {'today': 'today', 'day': 'today', 'week': 'week', 'month': 'month', 'all': 'all'}
HOP_PRESENCE = 'hop/presence'  # counted on its own: a ping every 15 s would swamp everything else
# Feature groups by route pattern, first match wins.
FEATURES = [
    ('Boards', ('stops/*/board',)), ('Planner', ('journeys',)), ('Search', ('places',)),
    ('Lines & trips', ('lines/*', 'trips', 'trips/*', 'statistics/*')), ('Vehicles', ('vehicles',)),
    ('Map', ('stops', 'rentals')), ('Disruptions', ('alerts', 'alerts/*')), ('Hop', ('hop/*',)),
    ('Reminders', ('push/*',)), ('App start', ('capabilities', 'locale', 'stats/*')), ('Health', ('health',)),
]


@dataclass
class Period:
    name: str
    start: datetime          # aware, local
    end: datetime            # aware, local (now, or the end of the data)
    prev_start: Optional[datetime]
    prev_end: Optional[datetime]
    step: str                # 'hour' or 'day'


def parse_period(words: str) -> str:
    """'today', 'week', 'this week', 'month', 'this month', 'all' -> today | week | month | all."""
    key = ' '.join(words.lower().split()).removeprefix('this ').strip() or 'today'
    if key not in PERIODS:
        raise ValueError(f'Unknown period "{words}": use today, week, month or all.')
    return PERIODS[key]


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), LOCAL)


def period(name: str, now: datetime, first: Optional[datetime] = None) -> Period:
    """The period up to `now` and the one before it, of the same length (today vs yesterday until the same time,
    this week from Monday vs last week, this month vs last month's first days)."""
    now = now.astimezone(LOCAL)
    today = now.date()
    if name == 'today':
        start = _midnight(today)
        return Period(name, start, now, _midnight(today - timedelta(days=1)), now - timedelta(days=1), 'hour')
    if name == 'week':
        start = _midnight(today - timedelta(days=today.weekday()))
        return Period(name, start, now, _midnight(start.date() - timedelta(days=7)), now - timedelta(days=7), 'day')
    if name == 'month':
        start = _midnight(today.replace(day=1))
        before = _midnight((start.date() - timedelta(days=1)).replace(day=1))
        # The same stretch of last month, cut at its end (31 March vs February).
        prev_end = min(datetime.combine(before.date() + (now.date() - start.date()), now.time(), LOCAL), start)
        return Period(name, start, now, before, prev_end, 'day')
    start = (first or now).astimezone(LOCAL)
    return Period('all', _midnight(start.date()), now, None, None, 'day')


def p95(buckets: list[int]) -> Optional[int]:
    """Upper bound (ms) of the bucket holding the 95th percentile; None without data, -1 above the last bound."""
    total = sum(buckets)
    if not total:
        return None
    seen = 0
    for i, n in enumerate(buckets):
        seen += n
        if seen >= 0.95 * total:
            return BUCKETS_MS[i] if i < len(BUCKETS_MS) else -1
    return -1


def feature(route: str) -> str:
    for name, patterns in FEATURES:
        if any(fnmatch.fnmatchcase(route, p) for p in patterns):
            return name
    return 'Other'


def _days(start: datetime, end: datetime) -> list[date]:
    out, day = [], start.date()
    while _midnight(day) < end:
        out.append(day)
        day += timedelta(days=1)
    return out


def _hours(start: datetime, end: datetime):
    from .models import AnalyticsHour
    return list(AnalyticsHour.objects.filter(hour__gte=start.astimezone(timezone.utc), hour__lt=end.astimezone(timezone.utc)))


def _visitors(start: datetime, end: datetime, today: date, live: Optional[dict]) -> dict:
    """Unique visitors and new users of the days in the period, merged across days, and the platform split."""
    from .models import AnalyticsDay
    days = _days(start, end)
    rows = [{'visitors_hll': bytes(r.visitors_hll), 'visitors': r.visitors, 'new_users': r.new_users, 'platform_hll': r.platform_hll,
             'platforms': r.platforms} for r in AnalyticsDay.objects.filter(day__in=days)]
    if live and today in days:
        rows.append(live)
    visitors = analytics.union([r['visitors_hll'] for r in rows])
    names = {n for r in rows for n in r['platform_hll']}
    platforms = {n: analytics.union([base64.b64decode(r['platform_hll'][n]) for r in rows if n in r['platform_hll']]) for n in names}
    approximate = visitors is None
    if approximate:  # no Redis to merge with: the days' own counts added up
        visitors = sum(r['visitors'] for r in rows)
        platforms = {n: sum(r['platforms'].get(n, 0) for r in rows) for n in names}
    return {'visitors': visitors, 'new': sum(r['new_users'] for r in rows), 'platforms': platforms, 'approximate': approximate}


def gather(p: Period, live: Optional[dict] = None) -> dict:
    """Everything the report shows for period `p` (and the one before it, for the arrows)."""
    def totals(rows):
        requests = [r for r in rows if r.route != HOP_PRESENCE]
        count = sum(r.count for r in requests)
        errors = sum(r.count for r in requests if r.status == '5xx')
        refused = sum(r.count for r in requests if r.status == '4xx')
        return count, errors, refused

    rows = _hours(p.start, p.end)
    count, errors, refused = totals(rows)
    out = {'period': p, 'requests': count, 'errors': errors, 'refused': refused,
           **_visitors(p.start, p.end, p.end.date(), live)}
    if p.prev_start:
        prev_rows = _hours(p.prev_start, p.prev_end)
        out['prev'] = {'requests': totals(prev_rows)[0], **_visitors(p.prev_start, p.prev_end, p.end.date(), None)}

    out['unit'], out['chart'] = _chart_series(rows, p)

    by_hour: dict[int, int] = {}
    routes: dict[str, dict] = {}
    groups: dict[str, dict] = {}
    for r in rows:
        if r.route == HOP_PRESENCE:
            continue
        hour = r.hour.astimezone(LOCAL).hour
        by_hour[hour] = by_hour.get(hour, 0) + r.count
        for table, key in ((routes, r.route), (groups, feature(r.route))):
            entry = table.setdefault(key, {'count': 0, 'errors': 0, 'buckets': [0] * (len(BUCKETS_MS) + 1)})
            entry['count'] += r.count
            entry['errors'] += r.count if r.status == '5xx' else 0
            entry['buckets'] = [a + b for a, b in zip(entry['buckets'], list(r.buckets) + [0] * (len(entry['buckets']) - len(r.buckets)))]
    out['busiest'] = sorted(by_hour.items(), key=lambda kv: -kv[1])[:3]
    out['routes'] = sorted(routes.items(), key=lambda kv: -kv[1]['count'])[:8]
    out['features'] = sorted(groups.items(), key=lambda kv: -kv[1]['count'])
    out['hop'] = {'presence': sum(r.count for r in rows if r.route == HOP_PRESENCE),
                  'sends': sum(r.count for r in rows if r.route == 'hop/send' and r.status == '2xx')}
    return out


def _chart_series(rows, p: Period) -> tuple[str, list[tuple[str, int]]]:
    """The unit and (label, requests) for every hour of today, or every day (week, month for long periods), empty ones too."""
    counts: dict[datetime, int] = {}
    span = (p.end.date() - p.start.date()).days
    unit = 'hour' if p.step == 'hour' else 'day' if span <= 45 else 'week' if span <= 400 else 'month'

    def slot(at: datetime) -> datetime:
        at = at.astimezone(LOCAL)
        if unit == 'hour':
            return at.replace(minute=0, second=0, microsecond=0)
        day = at.date()
        if unit == 'week':
            day -= timedelta(days=day.weekday())
        elif unit == 'month':
            day = day.replace(day=1)
        return _midnight(day)

    for r in rows:
        if r.route != HOP_PRESENCE:
            counts[slot(r.hour)] = counts.get(slot(r.hour), 0) + r.count
    out, at = [], slot(p.start)
    fmt = {'hour': '%H:00', 'day': '%a %d %b', 'week': 'wk %d %b %y', 'month': '%b %Y'}[unit]
    while at <= p.end:
        out.append((at.strftime(fmt), counts.get(at, 0)))
        if unit == 'hour':
            at = (at + timedelta(hours=1)).astimezone(LOCAL)
        elif unit == 'day':
            at = _midnight(at.date() + timedelta(days=1))
        elif unit == 'week':
            at = _midnight(at.date() + timedelta(days=7))
        else:
            at = _midnight((at.date() + timedelta(days=32)).replace(day=1))
    return unit, out


# ---------------------------------------------------------------- text

def _n(value: int) -> str:
    return f'{value:,}'


def delta(now: Optional[int], before: Optional[int]) -> str:
    if now is None or before is None:
        return ''
    if before == 0:
        return '' if now == 0 else '(new)'
    change = (now - before) * 100 / before
    if abs(change) < 0.5:
        return '= 0 %'
    return f'{"▲" if change > 0 else "▼"} {abs(change):.0f} %'


def _ms(value: Optional[int]) -> str:
    return '–' if value is None else '>3.2 s' if value < 0 else f'≤{value} ms'


def _share(part: int, whole: int) -> str:
    return f'{part * 100 / whole:.0f} %' if whole else '–'


def _when(at: datetime, with_time: bool) -> str:
    return at.strftime('%a %d %b %H:%M' if with_time else '%a %d %b %Y')


def render(data: dict) -> str:
    p: Period = data['period']
    prev = data.get('prev') or {}
    title = {'today': 'today', 'week': 'this week', 'month': 'this month', 'all': 'all time'}[p.name]
    lines = [f'KamGre usage · {title} · {_when(p.start, False)} – {_when(p.end, True)}']
    if p.prev_start:
        lines.append(f'compared with {_when(p.prev_start, False)} – {_when(p.prev_end, True)}')
    lines.append('')
    approx = ' (sum of days)' if data.get('approximate') else ''
    rows = [
        ('Visitors', _n(data['visitors']) + approx, delta(data['visitors'], prev.get('visitors'))),
        ('New users', _n(data['new']), delta(data['new'], prev.get('new'))),
        ('Requests', _n(data['requests']), delta(data['requests'], prev.get('requests'))),
    ]
    for label, value, arrow in rows:
        lines.append(f'  {label:<12}{value:>14}   {arrow}')
    lines.append(f'  {"Errors":<12}{_share(data["errors"], data["requests"]):>14}   server (5xx) · '
                 f'{_share(data["refused"], data["requests"])} refused or not found (4xx)')
    lines.append(f'  {"Hop":<12}{_n(data["hop"]["sends"]):>14}   routes sent · {_n(data["hop"]["presence"])} presence pings')
    if p.prev_start and data['period'].name != 'all':
        lines.append('  (visitors and new users compare whole days)')

    chart = data['chart']
    lines += ['', f'Requests per {data["unit"]}']
    top = max((n for _, n in chart), default=0)
    label_width = max((len(label) for label, _ in chart), default=5)
    bar_width = WIDTH - label_width - 16
    if not top:
        lines.append('  no requests yet')
    for label, n in chart if top else []:
        bar = '#' * round(n * bar_width / top) if top else ''
        lines.append(f'  {label:<{label_width}}  {bar:<{bar_width}} {_n(n):>10}'.rstrip())

    if data['busiest']:
        busiest = ' · '.join(f'{h:02d}:00 {_share(n, data["requests"])}' for h, n in data['busiest'])
        lines += ['', f'Busiest hours   {busiest}']

    lines += ['', f'{"Features":<24}{"requests":>10}{"share":>8}{"p95":>11}{"errors":>9}']
    if not data['features']:
        lines.append('  none yet')
    for name, e in data['features']:
        lines.append(f'  {name:<22}{_n(e["count"]):>10}{_share(e["count"], data["requests"]):>8}{_ms(p95(e["buckets"])):>11}{_share(e["errors"], e["count"]):>9}')
    lines += ['', f'{"Top endpoints":<24}{"requests":>10}{"share":>8}{"p95":>11}']
    if not data['routes']:
        lines.append('  none yet')
    for route, e in data['routes']:
        lines.append(f'  {route[:22]:<22}{_n(e["count"]):>10}{_share(e["count"], data["requests"]):>8}{_ms(p95(e["buckets"])):>11}')

    plat = data['platforms']
    seen = sum(plat.get(n, 0) for n in analytics.PLATFORMS)
    lines += ['', 'Platforms   ' + (' · '.join(f'{label} {_share(plat.get(n, 0), seen)}' for n, label in
                                               (('ios', 'iOS'), ('android', 'Android'), ('desktop', 'desktop'), ('other', 'other')) if plat.get(n))
                                    or 'no visitors yet')]
    shown = plat.get('app', 0) + plat.get('browser', 0)
    if shown:
        lines.append(f'            installed app {_share(plat.get("app", 0), shown)} · browser {_share(plat.get("browser", 0), shown)}')
    return '\n'.join(line[:WIDTH] for line in lines) + '\n'


def report(name: str, now: Optional[datetime] = None) -> str:
    from .models import AnalyticsDay, AnalyticsHour
    now = now or datetime.now(LOCAL)
    first = None
    if name == 'all':
        stamps = [AnalyticsHour.objects.aggregate(t=Min('hour'))['t']]
        day = AnalyticsDay.objects.aggregate(d=Min('day'))['d']
        stamps.append(_midnight(day) if day else None)
        first = min((s for s in stamps if s), default=None)
    try:
        live = analytics.live_day(now.astimezone(LOCAL).date())
    except Exception:  # noqa: BLE001 — the saved days still make a report
        live = None
    return render(gather(period(name, now, first), live))

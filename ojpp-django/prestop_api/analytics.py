"""Small, privacy-preserving usage counts for /api/v1 (`yarn server:stats`, analytics_report.py).

Per request the middleware adds to Redis, never to the database: the route (its URL pattern such as
"stops/*/board", never a path with ids in it), the status class and the time taken, per hour. The collector moves
those counts to AnalyticsHour once a minute (flush) and drops them from Redis.

Unique visitors are a HyperLogLog per day of hash(IP + browser family + a random salt made for that day). The salt
lives in Redis only until its day is over, so a visitor cannot be followed from one day to the next; IPs and their
hashes are never stored. Each night the finished day's HyperLogLogs (also per platform: iOS, Android or desktop, and
installed app or browser when the app says so with `display=` on /capabilities) are saved to AnalyticsDay as bytes,
so any period can be merged. New users: the app's one POST /stats/hello after onboarding, counted the same way
(once per visitor a day). Requests without the proxy's client IP header come from the server itself and are skipped.
"""
import base64
import bisect
import hashlib
import logging
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import redis
from django.conf import settings
from django.db import transaction

log = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
BUCKETS_MS = (50, 100, 200, 400, 800, 1600, 3200)  # upper bounds of the time-taken buckets; one more above the last
HOUR_TTL = 6 * 3600  # s an hour's counts may wait in Redis for the collector
DAY_TTL = 8 * 86400  # s a day's HyperLogLogs may wait for the nightly save
KEEP_HOURS_DAYS = 400
PLATFORMS = ('ios', 'android', 'desktop', 'other')
DISPLAYS = ('app', 'browser')

_salt = threading.local()
_warned = [0.0]


def _redis():
    url = getattr(settings, 'PRESTOP_ANALYTICS_REDIS_URL', '') or settings.CACHES['default']['LOCATION']
    return redis.Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)


def local_day(now: float) -> date:
    return datetime.fromtimestamp(now, LOCAL).date()


def route_name(request) -> str:
    """The route's URL pattern without the API prefix and with every parameter as *: "stops/*/board"."""
    match = getattr(request, 'resolver_match', None)
    if match is None:
        return 'other'  # unknown paths, and requests the traffic guard refused before routing
    parts = [('*' if p.startswith('<') else p) for p in match.route.split('/')]
    return '/'.join(parts).removeprefix('api/v1/')[:64] or 'other'


def platform(agent: str) -> str:
    if any(k in agent for k in ('iPhone', 'iPad', 'iPod')):
        return 'ios'
    if 'Android' in agent:
        return 'android'
    if any(k in agent for k in ('Windows', 'Macintosh', 'X11', 'Linux', 'CrOS')):
        return 'desktop'
    return 'other'


def browser(agent: str) -> str:
    for key, name in (('Edg', 'edge'), ('Firefox', 'firefox'), ('FxiOS', 'firefox'), ('SamsungBrowser', 'samsung'),
                      ('CriOS', 'chrome'), ('Chrome', 'chrome'), ('Safari', 'safari')):
        if key in agent:
            return name
    return 'other'


def _day_salt(r, day: date) -> bytes:
    """The day's random salt, shared by the workers through Redis and gone when the day ends."""
    cached = getattr(_salt, 'value', None)
    if cached and cached[0] == day:
        return cached[1]
    key = f'analytics:salt:{day.isoformat()}'
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), LOCAL)
    if r.set(key, secrets.token_hex(16), nx=True):
        r.expireat(key, int(end.timestamp()))
    value = r.get(key) or b''
    _salt.value = (day, value)
    return value


def visitor(r, ip: str, agent: str, day: date) -> str:
    family = f'{platform(agent)}/{browser(agent)}'
    return hashlib.sha256(_day_salt(r, day) + f'|{ip}|{family}'.encode()).hexdigest()[:16]


def record(r, route: str, status: int, seconds: float, ip: str, agent: str, display: Optional[str] = None, now: Optional[float] = None):
    now = time.time() if now is None else now
    ms = max(0, int(seconds * 1000))
    field = f'{route}|{status // 100}xx'
    hour_key = f'analytics:h:{int(now // 3600)}'
    day = local_day(now)
    who = visitor(r, ip, agent, day)
    uv = f'analytics:uv:{day.isoformat()}'
    days = [uv, f'{uv}:{platform(agent)}'] + ([f'{uv}:{display}'] if display in DISPLAYS else [])
    pipe = r.pipeline(transaction=False)
    pipe.hincrby(hour_key, field, 1).hincrby(hour_key, f'{field}|ms', ms)
    pipe.hincrby(hour_key, f'{field}|b{bisect.bisect_left(BUCKETS_MS, ms)}', 1).expire(hour_key, HOUR_TTL)
    for key in days:
        pipe.pfadd(key, who).expire(key, DAY_TTL)
    pipe.execute()


def hello(ip: str, agent: str, now: Optional[float] = None) -> None:
    """A new user finished onboarding (POST /stats/hello): counted once per visitor and day."""
    now = time.time() if now is None else now
    r = _redis()
    day = local_day(now)
    key = f'analytics:new:{day.isoformat()}'
    r.pipeline(transaction=False).pfadd(key, visitor(r, ip, agent, day)).expire(key, DAY_TTL).execute()


def client_ip(request) -> Optional[str]:
    header = getattr(settings, 'PRESTOP_CLIENT_IP_HEADER', '')
    return request.headers.get(header) if header else request.META.get('REMOTE_ADDR')


class AnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, 'PRESTOP_ANALYTICS', False)
        self.redis = _redis() if self.enabled else None

    def __call__(self, request):
        if not self.enabled or not request.path.startswith('/api/v1/'):
            return self.get_response(request)
        started = time.monotonic()
        response = self.get_response(request)
        ip = client_ip(request)
        if ip:
            try:
                display = request.GET.get('display')
                record(self.redis, route_name(request), response.status_code, time.monotonic() - started, ip,
                       request.headers.get('User-Agent', ''), display if display in DISPLAYS else None)
            except redis.RedisError as e:  # counting must never cost a request
                if time.time() - _warned[0] > 600:
                    _warned[0] = time.time()
                    log.warning('analytics: redis unavailable (%s); not counting', e)
        return response


# ---------------------------------------------------------------- the collector

def _parse_hour(data: dict) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    for raw, value in data.items():
        parts = raw.decode().split('|')
        row = rows.setdefault((parts[0], parts[1]), {'count': 0, 'ms': 0, 'buckets': [0] * (len(BUCKETS_MS) + 1)})
        if len(parts) == 2:
            row['count'] += int(value)
        elif parts[2] == 'ms':
            row['ms'] += int(value)
        elif parts[2].startswith('b') and parts[2][1:].isdigit() and int(parts[2][1:]) < len(row['buckets']):
            row['buckets'][int(parts[2][1:])] += int(value)
    return rows


def _add_hour(hour: int, data: dict) -> int:
    from .models import AnalyticsHour
    at = datetime.fromtimestamp(hour * 3600, timezone.utc)
    rows = _parse_hour(data)
    with transaction.atomic():
        for (route, status), add in rows.items():
            row, _ = AnalyticsHour.objects.select_for_update().get_or_create(hour=at, route=route, status=status)
            buckets = list(row.buckets) + [0] * (len(add['buckets']) - len(row.buckets))
            row.count += add['count']
            row.ms += add['ms']
            row.buckets = [a + b for a, b in zip(buckets, add['buckets'])]
            row.save()
    return len(rows)


def flush(now: Optional[float] = None) -> int:
    """Moves the hourly counts from Redis to AnalyticsHour (the collector, once a minute); returns rows written.
    The hash is renamed first (atomic), so requests counted meanwhile go to a new one; if the database write fails,
    the renamed hash stays and is written on the next run."""
    if not getattr(settings, 'PRESTOP_ANALYTICS', False):
        return 0
    r = _redis()
    now = time.time() if now is None else now
    written = 0
    for hour in range(int(now // 3600) - HOUR_TTL // 3600, int(now // 3600) + 1):
        key = f'analytics:h:{hour}'
        work = f'{key}:flushing'
        if not r.exists(work):
            try:
                r.rename(key, work)
            except redis.ResponseError:  # nothing counted in that hour
                continue
        written += _add_hour(hour, r.hgetall(work))
        r.delete(work)
    return written


def _hll(r, key: str) -> bytes:
    return r.get(key) or b''


def save_day(day: date, r=None) -> Optional[dict]:
    """Saves a finished day's HyperLogLogs to AnalyticsDay and deletes them and the day's salt from Redis."""
    from .models import AnalyticsDay
    r = r or _redis()
    uv = f'analytics:uv:{day.isoformat()}'
    new = f'analytics:new:{day.isoformat()}'
    keys = {name: f'{uv}:{name}' for name in PLATFORMS + DISPLAYS}
    if not r.exists(uv, new, *keys.values()):
        return None
    row, _ = AnalyticsDay.objects.get_or_create(day=day)
    # A day saved before (the collector restarted) is merged, not replaced.
    merged = f'analytics:merge:{day.isoformat()}'
    if row.visitors_hll:
        r.set(merged, bytes(row.visitors_hll), ex=60)
        r.pfmerge(uv, uv, merged)
    for name, key in keys.items():
        if row.platform_hll.get(name):
            r.set(merged, base64.b64decode(row.platform_hll[name]), ex=60)
            r.pfmerge(key, key, merged)
    row.visitors = r.pfcount(uv) if r.exists(uv) else 0
    row.visitors_hll = _hll(r, uv)
    row.new_users += r.pfcount(new) if r.exists(new) else 0
    row.platforms = {name: r.pfcount(key) for name, key in keys.items() if r.exists(key)}
    row.platform_hll = {name: base64.b64encode(_hll(r, key)).decode() for name, key in keys.items() if r.exists(key)}
    row.save()
    r.delete(uv, new, merged, f'analytics:salt:{day.isoformat()}', *keys.values())
    return {'day': day.isoformat(), 'visitors': row.visitors, 'new': row.new_users}


_nightly = {'day': None}


def nightly(now: Optional[float] = None) -> Optional[list]:
    """Once a day after midnight: save the finished days (analytics_day) and drop hourly rows past KEEP_HOURS_DAYS."""
    if not getattr(settings, 'PRESTOP_ANALYTICS', False):
        return None
    from .models import AnalyticsHour
    now = time.time() if now is None else now
    today = local_day(now)
    if _nightly['day'] == today:
        return None
    r = _redis()
    saved = [s for d in range(1, DAY_TTL // 86400 + 1) if (s := save_day(today - timedelta(days=d), r))]
    AnalyticsHour.objects.filter(hour__lt=datetime.fromtimestamp(now, timezone.utc) - timedelta(days=KEEP_HOURS_DAYS)).delete()
    _nightly['day'] = today
    return saved


def live_day(day: date, r=None) -> dict:
    """Today's figures straight from Redis (not saved until tonight), shaped like AnalyticsDay."""
    r = r or _redis()
    uv = f'analytics:uv:{day.isoformat()}'
    keys = {name: f'{uv}:{name}' for name in PLATFORMS + DISPLAYS}
    return {'day': day, 'visitors': r.pfcount(uv), 'visitors_hll': _hll(r, uv), 'new_users': r.pfcount(f'analytics:new:{day.isoformat()}'),
            'platforms': {name: r.pfcount(key) for name, key in keys.items() if r.exists(key)},
            'platform_hll': {name: base64.b64encode(_hll(r, key)).decode() for name, key in keys.items() if r.exists(key)}}


def union(blobs: list[bytes], r=None) -> Optional[int]:
    """Unique count across saved HyperLogLogs (a whole period), or None when Redis is unavailable."""
    blobs = [b for b in blobs if b]
    if not blobs:
        return 0
    try:
        r = r or _redis()
        keys = [f'analytics:union:{secrets.token_hex(6)}:{i}' for i in range(len(blobs))]
        pipe = r.pipeline(transaction=False)
        for key, blob in zip(keys, blobs):
            pipe.set(key, blob, ex=60)
        pipe.execute()
        try:
            return r.pfcount(*keys)
        finally:
            r.delete(*keys)
    except redis.RedisError:
        return None

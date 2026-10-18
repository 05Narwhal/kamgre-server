"""Traffic guard for /api/v1: keeps the public server inside Oracle's free allowance.

The server is a fixed Always Free VM, so the only charge traffic can cause is outbound
data above 10 TB a month. The guard sheds load in three steps, cheapest check first:

1. Stopped: the egress guard (deploy/oracle/server/egress-guard.sh) writes `stopped` in
   PRESTOP_TRAFFIC_STATE_DIR once the month's outbound data reaches EGRESS_LIMIT_GB.
   Every request then gets 503 (it also stops the tunnel and Caddy; this is the backstop).
2. Busy: new visitors get 503 while existing users keep working, when
   - the egress guard wrote `busy` (the month is ahead of its pro-rata pace), or
   - the API sent more than PRESTOP_TRAFFIC_HOURLY_MB in the last hour (rolling), or
   - more than PRESTOP_TRAFFIC_MAX_ACTIVE clients were seen in the last 15 minutes.
   "Existing" means the browser holds the signed `kg_admit` cookie, which the API sets
   on normal responses; Caddy checks the same cookie for the app's static files.
3. Rate: a client sending more than PRESTOP_TRAFFIC_PER_MINUTE requests a minute gets 429, and so does one
   going over ROUTE_LIMITS on an endpoint that costs an upstream call or a database row (spec 2026-10-18 A6).

Clients are counted by a salted hash of their IP (from PRESTOP_CLIENT_IP_HEADER, which
Cloudflare sets), kept in Redis for at most two hours. Requests without that header come
from the server itself (watchdog, SSH tunnel) and are never limited. If Redis fails, the
guard lets requests through and the egress guard still caps the month.
"""
import hashlib
import logging
import os
import threading
import time
import uuid

import redis
from django.conf import settings
from django.http import JsonResponse

log = logging.getLogger(__name__)

COOKIE = 'kg_admit'
COOKIE_SALT = 'prestop.traffic'
COOKIE_AGE = 30 * 86400
ACTIVE_WINDOW_MINUTES = 15
DECISION_TTL = 5.0  # seconds a busy/not-busy decision is reused by this worker
# (path prefix, group, requests, window in s) per client, on top of the overall rate: what a person never needs
# more of, but a script could use to tie up the planner, flood the geocoders we borrow or fill a table. Several
# people behind one mobile carrier's address share them, hence the headroom.
ROUTE_LIMITS = (
    ('/api/v1/journeys', 'plan', 60, 60),        # each is an OTP plan (seconds of upstream time)
    ('/api/v1/places', 'search', 240, 60),       # Photon (fair use) and Pelias
    ('/api/v1/statistics/', 'stats', 300, 60),   # database scans; daily counts ask OTP per route
    ('/api/v1/push/', 'push', 120, 3600),        # subscriptions and reminders are database rows
)

MESSAGES = {
    'BUSY': ('KamGre is very busy right now. Please try again a bit later.',
             'KamGre je trenutno zelo obremenjen. Poskusite znova malo kasneje.'),
    'PAUSED': ('KamGre is paused until the start of next month.',
               'KamGre je do začetka naslednjega meseca začasno ustavljen.'),
    'RATE_LIMITED': ('Too many requests. Please wait a minute.',
                     'Preveč zahtevkov. Počakajte minuto.'),
}


def _error(request, status, code, retry_after):
    english, slovene = MESSAGES[code]
    message = slovene if request.headers.get('Accept-Language', '').lower().startswith('sl') else english
    response = JsonResponse({'error': {'code': code, 'message': message, 'retryable': code != 'PAUSED'},
                             'requestId': uuid.uuid4().hex[:12]}, status=status)
    response['Retry-After'] = str(retry_after)
    response['Cache-Control'] = 'no-store'
    return response


class TrafficGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, 'PRESTOP_TRAFFIC_GUARD', False)
        self.ip_header = getattr(settings, 'PRESTOP_CLIENT_IP_HEADER', '')
        self.state_dir = getattr(settings, 'PRESTOP_TRAFFIC_STATE_DIR', '')
        self.per_minute = getattr(settings, 'PRESTOP_TRAFFIC_PER_MINUTE', 1200)
        self.max_active = getattr(settings, 'PRESTOP_TRAFFIC_MAX_ACTIVE', 3000)
        self.hourly_bytes = getattr(settings, 'PRESTOP_TRAFFIC_HOURLY_MB', 30000) * 1_000_000
        self.route_limits = getattr(settings, 'PRESTOP_TRAFFIC_ROUTE_LIMITS', ROUTE_LIMITS)
        self.salt = settings.SECRET_KEY.encode()
        url = getattr(settings, 'PRESTOP_TRAFFIC_REDIS_URL', '') or settings.CACHES['default']['LOCATION']
        self.redis = redis.Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)
        self._decision = (0.0, None)
        self._lock = threading.Lock()

    def __call__(self, request):
        if not self.enabled or not request.path.startswith('/api/v1/'):
            return self.get_response(request)
        ip = request.headers.get(self.ip_header) if self.ip_header else request.META.get('REMOTE_ADDR')
        if not ip:  # not from the tunnel: the server itself
            return self.get_response(request)

        if self._flag('stopped'):
            return _error(request, 503, 'PAUSED', 3600)
        client = hashlib.sha256(self.salt + ip.encode()).hexdigest()[:20]
        admitted = self._admitted(request)
        try:
            count = self._count(client)
            if count > self.per_minute:
                return _error(request, 429, 'RATE_LIMITED', 60)
            wait = self._route_limited(client, request.path)
            if wait:
                return _error(request, 429, 'RATE_LIMITED', wait)
            if not admitted and self._busy():
                return _error(request, 503, 'BUSY', 900)
        except redis.RedisError as exc:
            log.warning('traffic guard: redis unavailable (%s); letting the request through', exc)

        response = self.get_response(request)
        try:
            size = len(response.content) if not response.streaming else 0
            hour = int(time.time() // 3600)
            self.redis.pipeline(transaction=False).incrby(f'traffic:bytes:{hour}', size).expire(f'traffic:bytes:{hour}', 7300).execute()
        except redis.RedisError:
            pass
        if response.status_code < 500 and (admitted is None or time.time() - admitted > 86400):
            response.set_signed_cookie(COOKIE, str(int(time.time())), salt=COOKIE_SALT, max_age=COOKIE_AGE,
                                       secure=settings.SESSION_COOKIE_SECURE, httponly=True, samesite='Lax')
        return response

    def _flag(self, name):
        return bool(self.state_dir) and os.path.exists(os.path.join(self.state_dir, name))

    @staticmethod
    def _admitted(request):
        """When the browser was admitted (epoch seconds), or None for a new visitor."""
        value = request.get_signed_cookie(COOKIE, default=None, salt=COOKIE_SALT, max_age=COOKIE_AGE)
        try:
            return int(value) if value else None
        except ValueError:
            return None

    def _count(self, client):
        """Counts the request for the client's per-minute limit and the active-client tally."""
        minute = int(time.time() // 60)
        rate_key, active_key = f'traffic:rate:{client}:{minute}', f'traffic:active:{minute}'
        count, *_ = (self.redis.pipeline(transaction=False)
                     .incr(rate_key).expire(rate_key, 120)
                     .pfadd(active_key, client).expire(active_key, (ACTIVE_WINDOW_MINUTES + 1) * 60)
                     .execute())
        return count

    def _route_limited(self, client, path):
        """Seconds to wait when the client is over its limit for this kind of request (ROUTE_LIMITS), else 0."""
        for prefix, group, limit, window in self.route_limits:
            if path.startswith(prefix):
                key = f'traffic:route:{group}:{client}:{int(time.time() // window)}'
                count, _ = self.redis.pipeline(transaction=False).incr(key).expire(key, window * 2).execute()
                return window if count > limit else 0
        return 0

    def _busy(self):
        now = time.time()
        with self._lock:
            checked, busy = self._decision
            if busy is not None and now - checked < DECISION_TTL:
                return busy
        reason = None
        if self._flag('busy'):
            reason = 'monthly outbound data ahead of pace'
        else:
            minute, hour = int(now // 60), int(now // 3600)
            pipe = self.redis.pipeline(transaction=False)
            pipe.pfcount(*[f'traffic:active:{minute - i}' for i in range(ACTIVE_WINDOW_MINUTES)])
            pipe.mget(f'traffic:bytes:{hour}', f'traffic:bytes:{hour - 1}')
            active, (this_hour, last_hour) = pipe.execute()
            # Rolling hour: all of this hour plus the part of the last hour still inside the window.
            sent = int(this_hour or 0) + int(last_hour or 0) * (1 - (now % 3600) / 3600)
            if active > self.max_active:
                reason = f'{active} active clients (limit {self.max_active})'
            elif sent > self.hourly_bytes:
                reason = f'{sent / 1e6:.0f} MB sent in the last hour (limit {self.hourly_bytes / 1e6:.0f} MB)'
        with self._lock:
            if bool(reason) != bool(self._decision[1]):
                log.warning('traffic guard: %s', f'busy, new visitors refused: {reason}' if reason else 'back to normal')
            self._decision = (now, bool(reason))
        return bool(reason)

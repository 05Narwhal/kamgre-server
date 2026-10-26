"""Bounded HTTP access to the public upstream services Prestop reads.

- OpenTripPlanner (GTFS GraphQL) run by the OJPP authors: stops, timetables with
  realtime applied, journeys, alerts and rentals for all Slovenian feeds.
- Their combined GTFS-Realtime feed: vehicle positions and trip updates.

Every call has a timeout and a response-size limit. `Cached` keeps the last good
value so a failing upstream degrades to stale data instead of an error.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

T = TypeVar('T')
USER_AGENT = 'KamGre/0.1 (+https://kamgre.si)'
TIMEOUT = (5, 20)


class UpstreamError(Exception):
    """An upstream service failed, timed out or returned something unusable."""


_local = threading.local()


def session() -> requests.Session:
    """This thread's HTTP session: connections to each upstream are kept open and reused, so a
    request doesn't pay a new TCP + TLS handshake (~0.1 s, more from the server) every time.
    One per thread because a Session isn't safe to share between threads."""
    s = getattr(_local, 'session', None)
    if s is None:
        s = _local.session = requests.Session()
        s.headers['User-Agent'] = USER_AGENT
    return s


def _read_json(resp: requests.Response, limit: int) -> Any:
    size, chunks = 0, []
    for chunk in resp.iter_content(256 * 1024):
        size += len(chunk)
        if size > limit:
            raise UpstreamError(f'{resp.url} exceeds {limit} bytes')
        chunks.append(chunk)
    try:
        return json.loads(b''.join(chunks))
    except ValueError as e:
        raise UpstreamError(f'{resp.url} returned invalid JSON') from e


def get_json(url: str, params: Optional[dict] = None, limit: int = 32 * 1024 * 1024, timeout=TIMEOUT) -> Any:
    try:
        with session().get(url, params=params, timeout=timeout, stream=True, headers={'Accept': 'application/json'}) as resp:
            if resp.status_code != 200:
                raise UpstreamError(f'{url} returned HTTP {resp.status_code}')
            return _read_json(resp, limit)
    except requests.RequestException as e:
        raise UpstreamError(f'{url}: {e.__class__.__name__}') from e


def url_list(value) -> list[str]:
    """A setting naming one URL or several (a list, or comma-separated in the env): the URLs in order, blanks left out."""
    items = value.split(',') if isinstance(value, str) else list(value or [])
    return [u.strip() for u in items if isinstance(u, str) and u.strip()]


class Mirrors:
    """URLs that serve the same data (one service under two host names, then an older service): each call tries the
    one that answered last time first, then the others in their listed order. `setting` names the Django setting, read
    on every call so tests and env changes apply at once."""

    def __init__(self, setting: str):
        self.setting = setting
        self.good: Optional[str] = None  # the URL that answered last

    @property
    def urls(self) -> list[str]:
        return url_list(getattr(settings, self.setting, ''))

    def get_json(self, suffix: str = '', check: Callable[[Any], Any] = lambda data: data, **kwargs) -> Any:
        """The first usable answer: `check` turns the JSON into the value or raises ValueError/TypeError for a
        shape that isn't this feed (an answer of a dead mirror)."""
        urls = self.urls
        order = ([self.good] if self.good in urls else []) + [u for u in urls if u != self.good]
        last: Optional[Exception] = None
        for url in order:
            try:
                value = check(get_json(url + suffix, **kwargs))
            except (UpstreamError, ValueError, TypeError, AttributeError) as e:
                last = e
                continue
            self.good = url
            return value
        raise UpstreamError(f'{self.setting}: every URL failed ({last!r})' if last else f'{self.setting}: no URL')


class Otp:
    """GraphQL client that fails over between the configured OTP servers."""

    def __init__(self, urls: list[str], cooldown: float = 300):
        self.urls = urls
        self.cooldown = cooldown
        self._down_until: dict[str, float] = {}

    def query(self, query: str, variables: Optional[dict] = None, limit: int = 64 * 1024 * 1024, timeout=(5, 40)) -> dict:
        now = time.monotonic()
        candidates = [u for u in self.urls if self._down_until.get(u, 0) <= now] or self.urls
        last: Optional[Exception] = None
        for url in candidates:
            try:
                with session().post(url, json={'query': query, 'variables': variables or {}}, timeout=timeout, stream=True,
                                    headers={'Content-Type': 'application/json'}) as resp:
                    if resp.status_code != 200:
                        raise UpstreamError(f'OTP {url} returned HTTP {resp.status_code}')
                    body = _read_json(resp, limit)
            except (requests.RequestException, UpstreamError) as e:
                last = e
                self._down_until[url] = time.monotonic() + self.cooldown
                logger.warning('OTP %s failed: %r', url, e)
                continue
            if body.get('errors') and not body.get('data'):
                # A query error is not a server failure; another server would answer the same.
                raise UpstreamError(f'OTP query error: {body["errors"][0].get("message", "")[:200]}')
            return body['data']
        raise UpstreamError(f'All OTP servers failed: {last!r}')


_otp: Optional[Otp] = None


def otp() -> Otp:
    global _otp
    if _otp is None:
        _otp = Otp(settings.PRESTOP_OTP_URLS)
    return _otp


@dataclass
class Snapshot(Generic[T]):
    value: T
    fetched_at: float  # wall-clock epoch seconds of the successful fetch
    error: Optional[str] = None  # set while serving an older value after a failed refresh

    @property
    def age(self) -> float:
        return time.time() - self.fetched_at


@dataclass
class Cached(Generic[T]):
    """Process-local TTL cache with single-flight refresh and stale fallback."""

    load: Callable[[], T]
    ttl: float
    max_stale: float
    revalidate: float = 0  # serve a value up to ttl+revalidate old while refreshing in the background
    _snap: Optional[Snapshot[T]] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _flag: threading.Lock = field(default_factory=threading.Lock)
    _retry_at: float = 0
    _last_error: str = ''
    _refreshing: bool = False

    def get(self) -> Snapshot[T]:
        snap = self._snap
        if snap and snap.age < self.ttl:
            return snap
        if snap and snap.age < self.ttl + self.revalidate and not snap.error:
            self._refresh_in_background()
            return snap
        return self._refresh()

    def _refresh_in_background(self):
        with self._flag:
            if self._refreshing:
                return
            self._refreshing = True

        def run():
            try:
                self._refresh(force=True)
            except UpstreamError:
                pass
            finally:
                self._refreshing = False
        threading.Thread(target=run, daemon=True).start()

    def _refresh(self, force: bool = False) -> Snapshot[T]:
        with self._lock:
            snap = self._snap
            if snap and snap.age < self.ttl and not force:
                return snap
            if time.time() < self._retry_at:
                # Backing off after a failure: the last value, or with none the same failure (no new attempt), so a
                # dead upstream is not asked by every request (Arriva unreachable from the server: ~600 tries an hour).
                if snap:
                    return snap
                raise UpstreamError(self._last_error or 'retrying later')
            try:
                self._snap = Snapshot(self.load(), time.time())
                return self._snap
            except Exception as e:
                logger.warning('Refresh failed (%s): %r', getattr(self.load, '__name__', 'source'), e)
                # Back off before retrying so a dead upstream is not hammered by every request.
                self._retry_at = time.time() + min(60.0, max(5.0, self.ttl))
                self._last_error = str(e)
                if snap and snap.age < self.max_stale:
                    snap.error = str(e)
                    return snap
                raise UpstreamError(str(e)) from e

    def get_nowait(self) -> Optional[Snapshot[T]]:
        """The value now, never waiting on the upstream: an old one starts a refresh in the background,
        and with none yet (or only one past `max_stale`) the load starts in the background and None comes back."""
        snap = self._snap
        if snap and snap.age < self.ttl:
            return snap
        self._refresh_in_background()
        return snap if snap and snap.age < self.max_stale else None

    def wait(self, timeout: float) -> Optional[Snapshot[T]]:
        """Like get_nowait, but with nothing usable yet waits up to `timeout` s for the background load."""
        snap = self.get_nowait()
        deadline = time.time() + timeout
        while snap is None and time.time() < deadline:
            time.sleep(0.05)
            current = self._snap
            snap = current if current and current.age < self.max_stale else None
        return snap

    def warm(self, share: float = 0.8):
        """Refreshes (blocking) once the value is `share` of its ttl old, so a request never finds it expired."""
        snap = self._snap
        if snap is None or snap.age >= self.ttl * share or snap.error:
            try:
                self._refresh(force=True)
            except UpstreamError:
                pass

    def peek(self) -> Optional[Snapshot[T]]:
        return self._snap

    def clear(self):
        self._snap = None
        self._retry_at = 0

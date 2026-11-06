"""Plain HTTP access to potniski.sz.si behind Cloudflare's check.

Without a cookie every request gets 403 with `cf-mitigated: challenge`. A real browser passes; so does FlareSolverr
when its browser scores well from this IP. The solver only *solves*: it opens one page, we keep its `cf_clearance`
cookie and exact user agent (Cloudflare binds one to the other) in `clearance.json`, and every later request is a
small plain one with those, until a 403 challenge says the cookie no longer works (then one new solve, once).

Politeness: one request at a time, at least MIN_GAP s apart, gzip, bounded size, and a back-off ladder per job that
never goes faster than 60 s (`Backoff`). An IP block (Cloudflare 1020 / 1015, 429) waits an hour at once.
"""
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger(__name__)

BASE = 'https://potniski.sz.si'
SOLVE_PAGE = '/pomoc-uporabnikom-in-stanje-v-prometu/'
AJAX = '/wp-admin/admin-ajax.php'
SESSION = 'kamgre-sz'
TIMEOUT = (5, 20)
LIMIT = 8 * 1024 * 1024   # bytes of one answer
MIN_GAP = 1.0             # s between requests
SOLVE_TIMEOUT_MS = 120000
LADDER = (60, 300, 900, 3600)  # s of back-off after the 1st, 2nd, ... failure of a job
BLOCKED_WAIT = 3600
DEFAULT_UA = 'Mozilla/5.0 (compatible; KamGre/0.1; +https://kamgre.si)'
KINDS = ('challenge', 'blocked', 'down', 'layout')


class SiteError(Exception):
    """The site could not give a usable answer. `kind`: challenge (not cleared), blocked (IP refused), down (5xx,
    timeout, connection) or layout (the page is not what the parsers expect)."""

    def __init__(self, kind: str, detail: str = ''):
        super().__init__(f'{kind}: {detail}' if detail else kind)
        self.kind = kind
        self.detail = detail


class Backoff:
    """How long a job waits after failing: 60, 300, 900, 3600 s and then 3600 s again, never faster; an IP block waits
    3600 s at once. A success starts the ladder over."""

    def __init__(self):
        self.failures = 0
        self.until = 0.0

    def failed(self, kind: str, now: float) -> float:
        delay = BLOCKED_WAIT if kind == 'blocked' else LADDER[min(self.failures, len(LADDER) - 1)]
        self.failures += 1
        self.until = now + delay
        return delay

    def ok(self) -> None:
        self.failures, self.until = 0, 0.0

    def due(self, now: float) -> bool:
        return now >= self.until


def atomic_write(path: Path, text: str) -> None:
    """Written to a temporary file, then moved over the old one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def clearance_from(raw: Any) -> dict:
    """{'cookies': {name: value}, 'userAgent'} from a browser export: cookies as an object or a list of {name, value}
    (what the DevTools protocol and extensions give), the user agent beside them. A JSON string is read first."""
    if isinstance(raw, (str, bytes)):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError('a clearance is an object with cookies and userAgent')
    cookies = raw.get('cookies')
    if isinstance(cookies, list):
        cookies = {c['name']: c['value'] for c in cookies if isinstance(c, dict) and c.get('name')}
    if not isinstance(cookies, dict) or not cookies:
        raise ValueError('no cookies in the clearance')
    return {'cookies': {str(k): str(v) for k, v in cookies.items()}, 'userAgent': str(raw.get('userAgent') or DEFAULT_UA)}


def read_body(resp, limit: int) -> str:
    """The answer's text, refusing more than `limit` bytes (requests has already undone gzip)."""
    chunks, size = [], 0
    for chunk in resp.iter_content(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise SiteError('layout', f'answer exceeds {limit} bytes')
        chunks.append(chunk)
    return b''.join(chunks).decode(getattr(resp, 'encoding', None) or 'utf-8', errors='replace')


class Client:
    def __init__(self, solver_url: str, state_dir: str, base: str = BASE, http: Optional[Any] = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.solver_url = (solver_url or '').strip()
        self.base = base.rstrip('/')
        self.path = Path(state_dir) / 'clearance.json'
        self.min_gap = MIN_GAP
        self._http = http
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._last = float('-inf')
        self.clearance: dict = {'cookies': {}, 'userAgent': DEFAULT_UA, 'at': 0}
        self.solves = 0
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            self.clearance = {**clearance_from(saved), 'at': float(saved.get('at') or 0)}
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @property
    def http(self):
        if self._http is None:
            self._http = requests.Session()
        return self._http

    @property
    def cleared(self) -> bool:
        return bool(self.clearance['cookies'])

    def seed(self, raw: Any) -> None:
        """Use a clearance exported from a browser (local testing: the cookie works with plain HTTP from the same IP)."""
        self._keep(clearance_from(raw))

    def _keep(self, clearance: dict) -> None:
        self.clearance = {**clearance, 'at': time.time()}
        atomic_write(self.path, json.dumps(self.clearance, ensure_ascii=False))

    # ------------------------------------------------------------ requests

    def get(self, path: str, params: Optional[dict] = None) -> str:
        return self._request('GET', path, params=params)

    def ajax(self, action: str, data: Optional[dict] = None) -> str:
        return self._request('POST', AJAX, data={'action': action, **(data or {})})

    def _request(self, method: str, path: str, **kwargs) -> str:
        with self._lock:  # one request at a time; a new solve happens inside the same turn
            try:
                return self._send(method, path, **kwargs)
            except SiteError as e:
                if e.kind != 'challenge':
                    raise
            self.solve()
            return self._send(method, path, **kwargs)

    def _send(self, method: str, path: str, **kwargs) -> str:
        wait = self._last + self.min_gap - self._clock()
        if wait > 0:
            self._sleep(wait)
        headers = {'User-Agent': self.clearance['userAgent'], 'Accept-Encoding': 'gzip', 'Referer': self.base + '/'}
        if method == 'POST':
            headers['X-Requested-With'] = 'XMLHttpRequest'
        try:
            resp = self.http.request(method, self.base + path, headers=headers, cookies=self.clearance['cookies'],
                                     timeout=TIMEOUT, stream=True, **kwargs)
            try:
                body = read_body(resp, LIMIT)
            finally:
                resp.close()
        except requests.RequestException as e:
            raise SiteError('down', e.__class__.__name__) from e
        finally:
            self._last = self._clock()
        status = resp.status_code
        if status == 429 or (status == 403 and re.search(r'Error 10(20|15)', body)):
            raise SiteError('blocked', f'HTTP {status}')
        if status in (403, 503) and (resp.headers.get('cf-mitigated') == 'challenge' or 'Just a moment' in body):
            raise SiteError('challenge', f'HTTP {status}')
        if status >= 500:
            raise SiteError('down', f'HTTP {status}')
        if status != 200:
            raise SiteError('blocked' if status == 403 else 'layout', f'HTTP {status}')
        return body

    # ------------------------------------------------------------ solver

    def solve(self) -> None:
        """Ask FlareSolverr for a fresh clearance. Its browser (~600 MB) lives only for this call."""
        if not self.solver_url:
            raise SiteError('challenge', 'no solver configured')
        try:
            self._solver({'cmd': 'sessions.create', 'session': SESSION})
            out = self._solver({'cmd': 'request.get', 'url': self.base + SOLVE_PAGE, 'session': SESSION,
                                'maxTimeout': SOLVE_TIMEOUT_MS})
            solution = out.get('solution') or {}
            cookies = {c['name']: c['value'] for c in solution.get('cookies') or [] if isinstance(c, dict) and c.get('name')}
            if 'cf_clearance' not in cookies:
                raise SiteError('challenge', 'the solver returned no cf_clearance cookie')
            self._keep({'cookies': cookies, 'userAgent': str(solution.get('userAgent') or DEFAULT_UA)})
            self.solves += 1
            logger.info('SŽ site: new clearance (%d cookies)', len(cookies))
        finally:
            try:
                self._solver({'cmd': 'sessions.destroy', 'session': SESSION})
            except SiteError as e:
                logger.warning('SŽ site: solver session not destroyed: %s', e)

    def _solver(self, payload: dict) -> dict:
        try:
            resp = self.http.request('POST', self.solver_url.rstrip('/') + '/v1', json=payload,
                                     timeout=(5, SOLVE_TIMEOUT_MS / 1000 + 30))
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise SiteError('challenge', f'solver unreachable ({e.__class__.__name__})') from e
        if not isinstance(data, dict) or data.get('status') != 'ok':
            say = data.get('message') if isinstance(data, dict) else data
            raise SiteError('challenge', f'solver: {str(say)[:120]}')
        return data

"""A cheap look at the hand-kept city timetables (N15): which one expires soon and which one's source changed.

`manage.py citytt_check` runs nightly on the server (prestop-citytt-check.timer, 02:15) and at the start of `yarn live`
on the PC (arriva.si answers only from Slovenia, so the PC sees what the server cannot). Per feed it reads the folder's
status.json (end date, last build, the files it was built from) and asks the operator's site for two small things, no
PDF downloads and no Valhalla: the list page, whose timetable links must still be the files the build read, and a HEAD
of each of those files (Last-Modified and Content-Length against what was seen when the folder was last built or
uploaded). The answer goes to a small state file; `/health` `cityTimetables` serves it, `server:top` and `yarn live` show it.

States, most urgent first: expired, new (a timetable was published or replaced), expires (<= EXPIRING days left),
failed (the last build failed), unreachable (the site did not answer: only said, never an alarm), ok.
Nothing here rebuilds or ships anything; `yarn city-timetables --update` does that when the user asks.
"""
import html
import json
import logging
import os
import re
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import requests
from django.conf import settings

from . import CITIES, EXPIRING, STATUS
from .. import supplement
from ..upstream import USER_AGENT

logger = logging.getLogger(__name__)
GAP = 1.0           # s between two requests to an operator
PAGE_LIMIT = 2 * 1024 * 1024
URGENT = ('expired', 'new', 'expires', 'failed')    # what the user must act on; the order is the priority
TTL = 60            # s a /health answer reuses the folders' status files


class Unreachable(Exception):
    pass


def state_file() -> str:
    return getattr(settings, 'PRESTOP_CITYTT_CHECK_FILE', '')


def read_status(feed: str) -> dict:
    try:
        return json.loads((supplement.LOCAL_GTFS / feed / STATUS).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def end_of(city, status: dict) -> date:
    try:
        return date.fromisoformat(status['end'])
    except (KeyError, ValueError, TypeError):
        return city.end


# ---------------------------------------------------------------- the two looks at an operator's site

def fetch_page(url: str) -> str:
    try:
        with requests.get(url, timeout=(10, 30), stream=True, headers={'User-Agent': USER_AGENT}) as resp:
            if resp.status_code != 200:
                raise Unreachable(f'HTTP {resp.status_code}')
            data = resp.raw.read(PAGE_LIMIT + 1, decode_content=True)
    except requests.RequestException as e:
        raise Unreachable(type(e).__name__) from e
    return data[:PAGE_LIMIT].decode('utf-8', 'replace')


def head_file(url: str) -> Optional[tuple]:
    """(Last-Modified, Content-Length) of a file, or None when the server gives neither (no signal, not an error)."""
    try:
        resp = requests.head(url, timeout=(10, 30), allow_redirects=True, headers={'User-Agent': USER_AGENT})
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    seen = (resp.headers.get('Last-Modified', ''), resp.headers.get('Content-Length', ''))
    return seen if any(seen) else None


class Gap:
    """Wraps a request function so two calls are at least GAP seconds apart (one polite client per operator)."""
    def __init__(self, fn: Callable, gap: float = GAP):
        self.fn, self.gap, self.last = fn, gap, float('-inf')

    def __call__(self, url: str):
        wait = self.last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return self.fn(url)
        finally:
            self.last = time.monotonic()


# ---------------------------------------------------------------- one feed

def look(city, status: dict, fetch: Callable, head: Callable, seen: dict) -> dict:
    """The network side of one feed: {'network': 'ok' | 'new' | 'unreachable', 'detail': [...], 'headers': {url: [lm, len]}}.
    `seen` is the headers recorded when the folder's version was first looked at; a feed built or uploaded anew starts a
    fresh baseline, so only a file that changes under the same version counts as new."""
    recorded = {f['file']: f['url'] for f in status.get('files') or [] if f.get('file') and f.get('url')}
    detail, headers = [], {}
    if '{line}' not in city.page:     # one page per line (Marprom): the build's own page scan is the only reader of those
        try:
            page = '\n'.join(fetch(u) for u in [city.page, *city.pages])
        except Unreachable as e:
            return {'network': 'unreachable', 'detail': [f'{city.page}: {e}'], 'headers': {}}
        names = {html.unescape(u).rsplit('/', 1)[-1] for u in re.findall(city.links, page)}
        detail += [f'{n} is new on the page' for n in sorted(names - set(recorded) - set(city.stale))]
        detail += [f'{n} is no longer on the page' for n in sorted(set(recorded) - names)]
        urls = list(recorded.values())
    else:
        urls = list(recorded.values())[:1]      # Marprom: the published feed (gtfs.zip)
    for url in urls:
        got = head(url)
        if got is None:
            continue
        headers[url] = list(got)
        if url in seen and list(seen[url]) != list(got):
            detail.append(f'{url.rsplit("/", 1)[-1]} changed')
    if '{line}' in city.page and urls and not headers:
        return {'network': 'unreachable', 'detail': [urls[0]], 'headers': {}}
    return {'network': 'new' if detail else 'ok', 'detail': detail, 'headers': headers}


def summarize(city, status: dict, entry: Optional[dict], today: date) -> dict:
    """The feed's answer for /health: the most urgent state, a line for people (`text`), `level` warn | info | ok."""
    end = end_of(city, status)
    left = (end - today).days
    if not status:
        return {'feed': city.feed, 'name': city.name, 'state': 'unavailable', 'level': 'warn', 'end': None, 'daysLeft': None,
                'text': f'{city.name} has no timetable folder', 'detail': []}
    network = entry['network'] if entry and entry.get('version') == status.get('version') else 'ok'
    detail = list(entry['detail']) if network != 'ok' and entry else []
    if left < 0:
        state, text = 'expired', f'{city.name} timetable ended {-left} days ago' if left < -1 else f'{city.name} timetable ended yesterday'
    elif network == 'new':
        state, text = 'new', f'{city.name} has a new timetable'
    elif left <= EXPIRING:
        state, text = 'expires', f'{city.name} expires in {left} days' if left != 1 else f'{city.name} expires tomorrow'
        if left == 0:
            text = f'{city.name} expires today'
    elif status.get('status') != 'ok':
        state, text = 'failed', f'{city.name} build failed'
        detail = list(status.get('problems') or [])[:3]
    elif network == 'unreachable':
        state, text = 'unreachable', f'{city.name} site not reachable'
    else:
        state, text = 'ok', f'{city.name} ok until {end.isoformat()}'
    return {'feed': city.feed, 'name': city.name, 'state': state, 'level': 'warn' if state in URGENT else 'info' if state == 'unreachable' else 'ok',
            'end': end.isoformat(), 'daysLeft': left, 'text': text, 'detail': detail}


# ---------------------------------------------------------------- all feeds

def _load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')) if path else {}
    except (OSError, ValueError):
        return {}


def run(today: date, fetch: Optional[Callable] = None, head: Optional[Callable] = None, path: Optional[str] = None,
        cities=None) -> dict:
    """Look at every city feed, write the state file and return {'checkedAt', 'feeds': [summary, ...]}."""
    path = state_file() if path is None else path
    fetch = fetch or Gap(fetch_page)
    head = head or Gap(head_file)
    old = _load(path).get('feeds') or {}
    state, feeds = {}, []
    for city in cities or CITIES.values():
        status = read_status(city.feed)
        entry = None
        if status:
            before = old.get(city.feed) or {}
            same = before.get('version') == status.get('version')
            entry = look(city, status, fetch, head, before.get('headers') or {} if same else {})
            if same and not entry['headers']:
                entry['headers'] = before.get('headers') or {}     # a HEAD that failed tonight keeps the baseline
            entry['version'] = status.get('version')
            state[city.feed] = entry
        feeds.append(summarize(city, status, entry, today))
    result = {'checkedAt': datetime.now(supplement.LOCAL).isoformat(timespec='seconds'), 'feeds': feeds}
    if path:
        _save(path, {**result, 'feeds': state})
    _memo.clear()
    return result


def _save(path: str, doc: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix='.citytt-check-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, target)
    except OSError:
        logger.exception('citytt check: state file not written')
        Path(tmp).unlink(missing_ok=True)


_memo: dict = {}


def latest(today: date) -> Optional[dict]:
    """/health `cityTimetables`: the last check's answer, re-read against the folders (a folder uploaded since the check
    is no longer "new"; the days left count from today). None when no check ever ran."""
    hit = _memo.get('v')
    if hit and time.monotonic() - hit[0] < TTL and hit[1] == today:
        return hit[2]
    doc = _load(state_file())
    out = None
    if doc.get('feeds'):
        out = {'checkedAt': doc.get('checkedAt'),
               'feeds': [summarize(c, read_status(c.feed), doc['feeds'].get(c.feed), today) for c in CITIES.values()]}
    _memo['v'] = (time.monotonic(), today, out)
    return out


def lines(result: dict) -> list[str]:
    """The text lines a person reads (server:top, yarn live): the urgent feeds, `new` ones first, with what changed."""
    return [f['text'] + (f' ({"; ".join(f["detail"][:2])})' if f['detail'] and f['state'] == 'new' else '')
            for f in sorted(result['feeds'], key=lambda f: URGENT.index(f['state']) if f['state'] in URGENT else 9) if f['level'] == 'warn']

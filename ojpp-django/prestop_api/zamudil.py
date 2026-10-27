"""zamudil.si: SŽ's notices per service date, the class SŽ plans for each train, and works on the lines.

zamudil.si's author allowed us (2026-10-27) to read three endpoints of `PRESTOP_ZAMUDIL_URL`
(https://api.zamudil.si/api), with the source named and our app in the User-Agent (upstream.USER_AGENT); the API
may change, so every answer is checked and a wrong shape counts as a failing mirror, never as "no data":

- `notices?date=YYYY-MM-DD` {serviceDate, notices: [{summary, body, severity, source, trainNumbers}]}: the notices of
  the trains running that date. A replacement notice is two items with equal `trainNumbers`, the title with its dates
  and "Povezava: [Vozni red nadomestnega prevoza](….pdf)" (see `records`, which turns them into the records of SŽ's
  old notices feed that closures.py and szpdf_sync read).
- `rollingstock/assignments?date=` {serviceDate, rollingStock: [{name, features, tables, trainNumbers}]}: the class
  planned for each train, not the unit that runs.
- `map/maintenance` {works: [{id, relation, validFrom, validTo, title, body, geometry}]}: works up to 14 days ahead.

Light on their server: the polls (`poll`, from warm.py while the app is in use, and from szpdf_sync) follow
`interval`, about 200 requests a day in all, and the last good copy of each endpoint and date is kept in
`PRESTOP_ZAMUDIL_DIR` (written atomically, past dates pruned). That directory is shared: the API's workers and the
szpdf timer read each other's copies and none asks again for a copy younger than its interval. A failed poll keeps
the copy and marks it stale (/health `sz:zamudil-*`).
"""
import hashlib
import html
import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from django.conf import settings

from .mapping import fold, iso
from .upstream import Mirrors, UpstreamError

logger = logging.getLogger(__name__)

LOCAL = ZoneInfo('Europe/Ljubljana')
SOURCE_NAME = 'zamudil.si'
SOURCE_URL = 'https://zamudil.si'
NOTICES, CLASSES, WORKS = 'notices', 'assignments', 'maintenance'
PATHS = {NOTICES: '/notices', CLASSES: '/rollingstock/assignments', WORKS: '/map/maintenance'}
DAYS_AHEAD = 13        # notices of today … today + 13 (the planner's date window)
ON_DEMAND_AGE = 6 * 3600  # s: a plan for another date asks for that date's notices when its copy is older
RETRY = 600            # s between attempts at one copy after a failure (shared through the copy's `checkedAt`)
STAT_EVERY = 10        # s between looks at one copy's file (stat is slow on the WSL /mnt drives)
LIMIT = 2 * 1024 * 1024
TIMEOUT = (4, 15)
DAYTIME = (5, 22)      # local hours with trains: today's notices every 10 min, else hourly

urls = Mirrors('PRESTOP_ZAMUDIL_URL')


def enabled() -> bool:
    return bool(urls.urls)


def today() -> date:
    from .trips import service_day
    return service_day()


# ---------------------------------------------------------------- checks (a wrong shape is a failing mirror)

def _items(data: Any, key: str) -> list:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise ValueError(f'no {key} list')
    return data[key]


def _same_day(data: dict, day: Optional[date]):
    got = data.get('serviceDate')
    if day and got not in (None, '') and str(got)[:10] != day.isoformat():
        raise ValueError(f'serviceDate {got} for {day}')


def check_notices(data: Any, day: Optional[date] = None) -> dict:
    items = _items(data, 'notices')
    _same_day(data, day)
    notices = [n for n in items if isinstance(n, dict) and isinstance(n.get('summary'), str) and n['summary'].strip()]
    if items and not notices:
        raise ValueError('no readable notice')
    return {'serviceDate': (day or today()).isoformat(), 'notices': notices}


def check_classes(data: Any, day: Optional[date] = None) -> dict:
    items = _items(data, 'rollingStock')
    _same_day(data, day)
    stock = [r for r in items if isinstance(r, dict) and isinstance(r.get('name'), str) and isinstance(r.get('trainNumbers'), list)]
    if items and not stock:
        raise ValueError('no readable class')
    return {'serviceDate': (day or today()).isoformat(), 'rollingStock': stock}


def check_works(data: Any, day: Optional[date] = None) -> dict:
    items = _items(data, 'works')
    works = [w for w in items if isinstance(w, dict) and w.get('id') is not None and isinstance(w.get('geometry'), list)]
    if items and not works:
        raise ValueError('no readable work')
    return {'works': works}


CHECKS: dict[str, Callable[[Any, Optional[date]], dict]] = {NOTICES: check_notices, CLASSES: check_classes, WORKS: check_works}
LISTS = {NOTICES: 'notices', CLASSES: 'rollingStock', WORKS: 'works'}


# ---------------------------------------------------------------- copies (memory, and the shared directory)

_copies: dict[tuple[str, Optional[str]], dict] = {}  # (endpoint, date or None) -> {data, fetchedAt, checkedAt, error}
_looked: dict[tuple[str, Optional[str]], tuple[float, Optional[tuple]]] = {}  # -> (when, file stamp) last read
_lock = threading.Lock()


def directory() -> Optional[Path]:
    path = getattr(settings, 'PRESTOP_ZAMUDIL_DIR', '') or ''
    return Path(path) if path else None


def _file(endpoint: str, day: Optional[str]) -> Optional[Path]:
    where = directory()
    return where / (f'{endpoint}-{day}.json' if day else f'{endpoint}.json') if where else None


def _write(path: Path, copy: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(copy, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)
    except OSError as e:
        logger.warning('zamudil copy not saved to %s: %r', path, e)


def copy(endpoint: str, day: Optional[date] = None, now: Optional[float] = None, look: bool = False) -> Optional[dict]:
    """The last copy of an endpoint (and date): {'data', 'fetchedAt' (last good answer), 'checkedAt' (last try),
    'error'}; another process's newer copy on disk replaces ours (looked for at most every STAT_EVERY s, or now with
    `look`)."""
    key = (endpoint, day.isoformat() if day else None)
    path = _file(*key)
    now = time.time() if now is None else now
    if path is not None and (look or now - _looked.get(key, (0, None))[0] >= STAT_EVERY):
        try:
            info = os.stat(path)
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            stamp = None
        if stamp != _looked.get(key, (0, None))[1]:
            try:
                found = json.loads(path.read_text(encoding='utf-8')) if stamp else None
                if found and isinstance(found.get('data'), dict) and (found.get('checkedAt') or 0) >= (_copies.get(key) or {}).get('checkedAt', 0):
                    _copies[key] = found
            except (OSError, ValueError) as e:
                logger.warning('zamudil copy %s unreadable: %r', path, e)
        _looked[key] = (now, stamp)
    return _copies.get(key)


def _store(endpoint: str, day: Optional[str], value: dict):
    key = (endpoint, day)
    _copies[key] = value
    path = _file(endpoint, day)
    if path is not None:
        _write(path, value)
        _looked.pop(key, None)  # our own write: read back on the next look, not taken for another process's


def prune(now: Optional[float] = None):
    """Copies of dates before today go (from memory and the directory)."""
    first = today().isoformat()
    for key in [k for k in _copies if k[1] and k[1] < first]:
        _copies.pop(key, None)
        _looked.pop(key, None)
    where = directory()
    if where is None or not where.exists():
        return
    for path in where.glob('*-????-??-??.json'):
        if path.stem[-10:] < first:
            try:
                path.unlink()
            except OSError:
                pass


class _Locked:
    """An exclusive lock on one copy across processes (fcntl; none where it is missing), so two workers whose copy
    expired at the same moment don't both ask."""

    def __init__(self, endpoint: str, day: Optional[str]):
        where = directory()
        self.path = where / f'.lock-{endpoint}-{day or "all"}' if where else None
        self.handle = None

    def __enter__(self) -> bool:
        if self.path is None:
            return True
        try:
            import fcntl
        except ImportError:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = open(self.path, 'a')
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self.handle:
                self.handle.close()
                self.handle = None
            return False

    def __exit__(self, *exc):
        if self.handle:
            self.handle.close()  # releases the lock


def fetch(endpoint: str, day: Optional[date] = None, now: Optional[float] = None) -> Optional[dict]:
    """Asks zamudil for one copy now; returns the copy in use afterwards. A failure, a wrong shape, or an empty list
    where the last copy had items keeps the last copy (with `error` set)."""
    if not enabled():
        return None
    now = time.time() if now is None else now
    key = day.isoformat() if day else None
    with _Locked(endpoint, key) as mine:
        if not mine:
            return copy(endpoint, day, now)
        old = copy(endpoint, day, now, look=True)  # what another process stored meanwhile
        params = {'date': key} if key else None
        try:
            data = urls.get_json(PATHS[endpoint], check=lambda raw: CHECKS[endpoint](raw, day), params=params, limit=LIMIT, timeout=TIMEOUT)
            if not data[LISTS[endpoint]] and old and (old.get('data') or {}).get(LISTS[endpoint]):
                raise UpstreamError(f'zamudil {endpoint}: empty answer (the last copy had {len(old["data"][LISTS[endpoint]])})')
        except UpstreamError as e:
            logger.warning('zamudil %s %s: %s', endpoint, key or '', e)
            if old:
                _store(endpoint, key, {**old, 'checkedAt': now, 'error': str(e)[:300]})
            else:
                _copies[(endpoint, key)] = _store_failure(endpoint, key, now, str(e))
            return copy(endpoint, day, now) if old else None
        _store(endpoint, key, {'data': data, 'fetchedAt': now, 'checkedAt': now, 'error': None})
        return _copies[(endpoint, key)]


def _store_failure(endpoint: str, key: Optional[str], now: float, error: str) -> dict:
    """No copy yet and the first try failed: remembered without data (so the retry waits), never written."""
    return {'data': None, 'fetchedAt': None, 'checkedAt': now, 'error': error[:300]}


def interval(endpoint: str, day: Optional[date], first: date, now: float) -> Optional[float]:
    """Seconds a copy is good for before the next poll; None: not polled (asked for on demand only)."""
    hour = datetime.fromtimestamp(now, LOCAL).hour
    day_time = DAYTIME[0] <= hour < DAYTIME[1]
    if endpoint == WORKS:
        return 3600
    ahead = (day - first).days if day else 0
    if endpoint == NOTICES:
        if ahead == 0:
            return 600 if day_time else 3600
        if ahead == 1:
            return 3600
        # the dates further on once a night (and on demand, `ensure`)
        return 20 * 3600 if 0 < ahead <= DAYS_AHEAD and hour < DAYTIME[0] else None
    if endpoint == CLASSES:
        if ahead == 0:
            return 1800 if day_time else 3600
        return 20 * 3600 if ahead == 1 and hour < DAYTIME[0] else None
    return None


def _due(endpoint: str, day: Optional[date], every: float, now: float) -> bool:
    found = copy(endpoint, day, now)
    if not found:
        return True
    if found.get('error') or not found.get('fetchedAt'):
        return now - (found.get('checkedAt') or 0) >= RETRY
    return now - found['fetchedAt'] >= every


def wanted(now: float) -> list[tuple[str, Optional[date], float]]:
    """(endpoint, date, interval) of every copy the schedule keeps."""
    first = today()
    out: list[tuple[str, Optional[date], float]] = [(WORKS, None, 3600)]
    for ahead in range(DAYS_AHEAD + 1):
        day = first + timedelta(days=ahead)
        for endpoint in (NOTICES, CLASSES):
            every = interval(endpoint, day, first, now)
            if every is not None:
                out.append((endpoint, day, every))
    return out


_polling = threading.Lock()


def poll(now: Optional[float] = None, endpoints: Iterable[str] = (NOTICES, CLASSES, WORKS)) -> int:
    """Asks for the copies that are due (warm.py's tick, szpdf_sync); returns how many were asked for."""
    if not enabled() or not _polling.acquire(blocking=False):
        return 0
    try:
        now = time.time() if now is None else now
        asked = 0
        for endpoint, day, every in wanted(now):
            if endpoint in endpoints and _due(endpoint, day, every, now):
                fetch(endpoint, day, now)
                asked += 1
        prune(now)
        return asked
    finally:
        _polling.release()


def ensure(endpoint: str, day: date, max_age: float = ON_DEMAND_AGE, now: Optional[float] = None) -> bool:
    """On demand (a plan for a date the schedule doesn't keep fresh): asks for the date's copy when it is older than
    `max_age` (and the last try is RETRY s past). True when a new copy came."""
    if not enabled() or not (0 <= (day - today()).days <= DAYS_AHEAD):
        return False
    now = time.time() if now is None else now
    if not _due(endpoint, day, max_age, now):
        return False
    before = (copy(endpoint, day, now) or {}).get('fetchedAt')
    after = (fetch(endpoint, day, now) or {}).get('fetchedAt')
    return bool(after and after != before)


def copies(endpoint: str, now: Optional[float] = None) -> list[tuple[date, dict]]:
    """(date, data) of every copy of a dated endpoint from today on that has data, by date."""
    first = today()
    out = []
    for ahead in range(DAYS_AHEAD + 1):
        day = first + timedelta(days=ahead)
        found = copy(endpoint, day, now)
        if found and isinstance(found.get('data'), dict):
            out.append((day, found['data']))
    return out


def version(endpoint: str = NOTICES) -> tuple:
    """Changes whenever a copy of the endpoint changes (each date's last good answer)."""
    return tuple((d.isoformat(), (copy(endpoint, d) or {}).get('fetchedAt')) for d, _ in copies(endpoint))


# ---------------------------------------------------------------- /health

NAMES = {NOTICES: ('sz:zamudil-notices', 'SŽ notices and replacement buses per date (zamudil.si)', ['alerts']),
         CLASSES: ('sz:zamudil-classes', 'Planned train classes (zamudil.si)', ['vehicles']),
         WORKS: ('sz:zamudil-works', 'Works on railway lines (zamudil.si)', ['alerts'])}


def health(now: Optional[float] = None) -> list[dict]:
    """One /health source per endpoint, by today's copy (the works' one copy): live while it is fresh, stale while
    a failed or late poll leaves the last good copy, unavailable with none. Left out when zamudil is off."""
    if not enabled():
        return []
    now = time.time() if now is None else now
    first = today()
    out = []
    for endpoint, (id_, name, capabilities) in NAMES.items():
        day = None if endpoint == WORKS else first
        found = copy(endpoint, day, now) or {}
        every = interval(endpoint, day, first, now) or 3600
        at = found.get('fetchedAt')
        if not at:
            status = 'unavailable'
        elif found.get('error') or now - at > 2 * every + 120:
            status = 'stale'
        else:
            status = 'live'
        stamp = iso(at) if at else None
        out.append({'id': id_, 'name': name, 'status': status, 'updatedAt': stamp, 'capabilities': capabilities, 'since': stamp})
    return out


# ---------------------------------------------------------------- notices → SŽ's notices feed records (G2)

MONTHS = ('jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'avg', 'sep', 'okt', 'nov', 'dec')
_MONTH_WORD = re.compile(r'(\d{1,2})\.?\s*(' + '|'.join(MONTHS) + r'|may|aug|oct)[a-z]*\.?')
_GROUP = re.compile(r'\(([^()]*\d[^()]*)\)')
PDF_LINK = re.compile(r'\[([^\]]*)\]\((https?://[^)\s]+?\.pdf)\)', re.I)
MD_LINK = re.compile(r'\[([^\]]*)\]\((https?://[^)\s]+)\)')
REPLACEMENT_TITLE = re.compile(r'nadomestn\w*\s+prevoz|avtobusn\w*\s+(?:\w+\s+)?prevoz\s+na\s+relaciji')
_RELATION = re.compile(r'(?:.*:\s*|.*\bna relaciji\s+)?(.+?)\s+in obratno', re.I)


def _month(word: str) -> int:
    word = {'may': 'maj', 'aug': 'avg', 'oct': 'okt'}.get(word, word)
    return MONTHS.index(word[:3]) + 1


def title_spans(title: str, seen: date) -> Optional[list[tuple[date, date]]]:
    """The days a notice title gives, as (first, last) spans, its year from `seen` (the service date it was listed
    on; a date more than half a year before it is next year's):
    "(24. 10. - 1. 11.)", "(26. - 30. oktober)", "(26. in 27. oktober)" (two one-day spans), "(26. - 30. 10. in
    3. - 6. 11.)" (two spans: not 31. 10. - 2. 11.), "(do 12. decembra)" (from `seen`). None when unreadable."""
    groups = _GROUP.findall(title or '')
    if not groups:
        return None
    text = _MONTH_WORD.sub(lambda m: f'{m.group(1)}. {_month(m.group(2))}.', fold(groups[-1]))
    until = bool(re.match(r'\s*do\b', text))
    text = re.sub(r'^\s*do\b', '', text)
    spans: list[list[list[int]]] = []
    for part in re.split(r',|;|\bin\b|\bter\b|\band\b', text):
        if not part.strip():
            continue
        ends = [re.findall(r'\d+', e) for e in re.split(r'[-–]', part)]
        if not 1 <= len(ends) <= 2 or any(not e or len(e) > 3 or len(e[0]) > 2 for e in ends) or re.search(r'[a-z]', part):
            return None
        spans.append([[int(x) for x in e] for e in ends])
    if not spans or (until and (len(spans) > 1 or len(spans[0]) > 1)):
        return None
    month = year = None
    for span in reversed(spans):  # "26. - 30. 10.": the first day has the month of the last
        for end in reversed(span):
            if len(end) >= 2:
                month, year = end[1], (end[2] if len(end) == 3 else year)
            elif month is None:
                return None
            else:
                end.extend([month] + ([year] if year else []))

    def day_of(end: list[int], after: date) -> date:
        d, m = end[0], end[1]
        y = end[2] if len(end) == 3 else after.year
        if y < 100:
            y += 2000
        found = date(y, m, d)
        if len(end) < 3 and found < after - timedelta(days=183):
            found = date(y + 1, m, d)
        return found
    try:
        if until:
            return [(seen, day_of(spans[0][0], seen))]
        out = []
        for span in spans:
            a = day_of(span[0], seen)
            b = day_of(span[-1], a) if len(span) > 1 else a
            if b < a:
                return None
            out.append((a, b))
        return out
    except ValueError:
        return None


def relation(title: str) -> str:
    """"Vozni red nadomestnega prevoza: Ljubljana - Jesenice / Beljak in obratno (…)" → "Ljubljana - Jesenice / Beljak"."""
    m = _RELATION.match(re.sub(r'\([^()]*\d[^()]*\)\.?\s*$', '', title or '').strip())
    return m.group(1).strip() if m else ''


def notice_number(pdf_url: str, line: str) -> str:
    """A stable notice number (digits, like SŽ's own `ID_ovire`) from the timetable's address and the line: two
    notices sharing one PDF (Ljubljana - Jesenice and Lesce Bled - Jesenice) stay two notices."""
    key = f'{pdf_url.strip()}\n{" ".join(re.findall(r"[a-z0-9]+", fold(line)))}'
    return str(10 ** 9 + int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) % (9 * 10 ** 9))


def markdown_html(text: str) -> str:
    """zamudil's Markdown links and paragraphs as the HTML SŽ's old feed had (closures reads `href="…"`)."""
    out = html.escape(text or '', quote=False)
    out = MD_LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out)
    return ''.join(f'<p>{p.strip()}</p>' for p in re.split(r'\n{2,}', out) if p.strip())


def markdown_text(text: str) -> tuple[str, Optional[str]]:
    """(plain text with Markdown links as their words, the first link's address) for an alert."""
    first = MD_LINK.search(text or '')
    return MD_LINK.sub(lambda m: m.group(1), text or '').strip(), first.group(2) if first else None


def _numbers(item: dict) -> tuple[int, ...]:
    out = []
    for n in item.get('trainNumbers') or []:
        try:
            out.append(int(n))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(set(out)))


def _pdf_of(item: dict) -> Optional[tuple[str, str]]:
    for text in (item.get('summary') or '', item.get('body') or ''):
        m = PDF_LINK.search(text)
        if m:
            return m.group(1), m.group(2)
    return None


def replacement_pairs(notices: list[dict]) -> tuple[list[tuple[dict, Optional[dict]]], list[dict]]:
    """A date's list as (title item, its "Povezava: …pdf" item or None) per replacement notice, and the other
    notices. A link item belongs to the closest item before it with the same trains that is no link itself."""
    pairs: list[tuple[dict, Optional[dict]]] = []
    paired: set[int] = set()
    for i, item in enumerate(notices):
        summary = fold(item.get('summary') or '').strip()
        if not summary.startswith('povezava') or not _pdf_of(item):
            continue
        for j in range(i - 1, max(-1, i - 4), -1):
            other = notices[j]
            if j in paired or _numbers(other) != _numbers(item) or fold(other.get('summary') or '').strip().startswith('povezava'):
                continue
            pairs.append((other, item))
            paired |= {i, j}
            break
    for i, item in enumerate(notices):
        if i not in paired and REPLACEMENT_TITLE.search(fold(item.get('summary') or '')) and not fold(item.get('summary') or '').startswith('dodatno'):
            pairs.append((item, None))
            paired.add(i)
    others = [n for i, n in enumerate(notices) if i not in paired]
    return pairs, others


def _cas(spans: list[tuple[date, date]]) -> str:
    return ', '.join(f'{a:%d.%m.%Y}-{b:%d.%m.%Y}' for a, b in spans)


def _merged_days(days: list[date]) -> list[tuple[date, date]]:
    out: list[list[date]] = []
    for d in sorted(set(days)):
        if out and d == out[-1][1] + timedelta(days=1):
            out[-1][1] = d
        else:
            out.append([d, d])
    return [(a, b) for a, b in out]


def records(lists: list[tuple[date, dict]]) -> list[dict]:
    """The replacement notices of each date's list (zamudil's notices, by date) as records of SŽ's notices feed:
    `ID_ovire` (notice_number), `Naslov`, `Relacija`, `Cas` ("dd.mm.yyyy-dd.mm.yyyy", several spans comma-
    separated), `Opis` (HTML with the PDF link), and our own `Vlaki` (the trains, all dates), `VlakiPoDnevih` (the
    trains each date's list names), `CasVir` ('title', or 'listed': the title's dates were unreadable, so the dates
    it was listed on). One notice listed on several dates is one record."""
    found: dict[str, dict] = {}
    for day, data in sorted(lists, key=lambda x: x[0]):
        pairs, _ = replacement_pairs([n for n in (data or {}).get('notices') or [] if isinstance(n, dict)])
        for head, link in pairs:
            title = (head.get('summary') or '').strip()
            pdf = _pdf_of(link) if link else None
            line = relation(title)
            number = notice_number(pdf[1] if pdf else title, line or title)
            entry = found.setdefault(number, {'title': title, 'line': line, 'pdf': pdf, 'first': day, 'days': {}, 'body': '',
                                              'source': head.get('source') or 'sz'})
            entry['days'][day.isoformat()] = sorted(set(_numbers(head)) | set(_numbers(link or {})))
            body = '\n\n'.join(t for t in ((head.get('body') or '').strip(), (link or {}).get('body') or '') if t and t.strip())
            if body and day == entry['first']:
                entry['body'] = body
    out = []
    for number, entry in found.items():
        spans = title_spans(entry['title'], entry['first'])
        how = 'title'
        if not spans:
            logger.warning('zamudil notice "%s": dates unreadable; in effect on the dates it is listed on', entry['title'][:120])
            spans, how = _merged_days([date.fromisoformat(d) for d in entry['days']]), 'listed'
        text = markdown_html(entry['body'])
        if entry['pdf']:
            text += f'<p><a href="{html.escape(entry["pdf"][1])}">{html.escape(entry["pdf"][0] or "Vozni red nadomestnega prevoza")}</a></p>'
        trains = sorted({n for numbers in entry['days'].values() for n in numbers})
        out.append({'ID_ovire': [number], 'Naslov': [entry['title']], 'Relacija': [entry['line']], 'Cas': [_cas(spans)],
                    'Opis': [text], 'Vlaki': [trains], 'VlakiPoDnevih': [entry['days']], 'CasVir': [how],
                    'Vir': [SOURCE_NAME]})
    return sorted(out, key=lambda r: r['ID_ovire'][0])


def train_notices(lists: list[tuple[date, dict]]) -> list[dict]:
    """The other notices of each date's list (not replacement timetables, G4), one per notice however many dates list
    it: {'number', 'title' (plain), 'text', 'url' (its first link), 'source' ('sz' | 'oebb'), 'trains' (numbers as
    text), 'days'}. An item right after one with the same trains continues it ("OBVESTILO: Združeni vlaki iz/do
    Zidanega Mosta" + "ZIDANI MOST - LJUBLJANA:" with the details)."""
    found: dict[str, dict] = {}
    for day, data in sorted(lists, key=lambda x: x[0]):
        _, others = replacement_pairs([n for n in (data or {}).get('notices') or [] if isinstance(n, dict)])
        groups: list[list[dict]] = []
        for item in others:
            if groups and _numbers(groups[-1][-1]) == _numbers(item) and _numbers(item):
                groups[-1].append(item)
            else:
                groups.append([item])
        for group in groups:
            head = group[0]
            title, url = markdown_text(head.get('summary') or '')
            parts = [markdown_text(head.get('body') or '')] + [markdown_text(f'{n.get("summary") or ""}\n\n{n.get("body") or ""}') for n in group[1:]]
            text = '\n\n'.join(t for t, _ in parts if t)
            url = url or next((u for _, u in parts if u), None)
            number = notice_number('', title)
            entry = found.setdefault(number, {'number': number, 'title': title, 'text': text, 'url': url, 'source': head.get('source') or 'sz',
                                              'trains': [], 'days': []})
            entry['trains'] = sorted(set(entry['trains']) | {str(n) for item in group for n in _numbers(item)}, key=int)
            entry['days'].append(day)
    return list(found.values())


# ---------------------------------------------------------------- works on the lines (G5)

WORKS_AHEAD = 14       # days: zamudil's maintenance covers this far
NEAR_WORK = 30.0       # m: a leg this close to a work's line runs along it
ALONG_WORK = 300.0     # m: … for at least this long
_works: dict = {'stamp': None, 'value': []}


def _iso_day(value) -> Optional[str]:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def line_works() -> list[dict]:
    """Every work in the maintenance copy as a lineWork (contract): {id, title, message, relation, validFrom,
    validTo, geometry, sourceUrl}; works without dates or a line of two points are left out. Worked out once per
    copy (polled hourly)."""
    found = copy(WORKS) if enabled() else None
    data = (found or {}).get('data') or {}
    stamp = (found or {}).get('fetchedAt'), id(data)
    if _works['stamp'] == stamp:
        return _works['value']
    out = []
    for w in data.get('works') or []:
        start, end = _iso_day(w.get('validFrom')), _iso_day(w.get('validTo'))
        line = [[round(float(p[0]), 6), round(float(p[1]), 6)] for p in w.get('geometry') or []
                if isinstance(p, (list, tuple)) and len(p) >= 2 and all(isinstance(x, (int, float)) for x in p[:2])
                and 13 < p[0] < 17 and 45 < p[1] < 47.5]  # [lon, lat] in and around Slovenia
        if not start or not end or len(line) < 2:
            continue
        text, url = markdown_text(w.get('body') or '')
        title, _ = markdown_text(w.get('title') or '')
        out.append({'id': str(w['id']), 'title': title or (w.get('relation') or ''), 'message': text, 'relation': str(w.get('relation') or ''),
                    'validFrom': start, 'validTo': end, 'geometry': line, 'sourceUrl': url})
    _works.update(stamp=stamp, value=out)
    return out


def works_between(first: date, last: date) -> list[dict]:
    """The works in effect on any day from `first` to `last`."""
    a, b = first.isoformat(), last.isoformat()
    return [w for w in line_works() if w['validFrom'] <= b and w['validTo'] >= a]


def runs_along(leg: list, work: list, near: float = NEAR_WORK, along: float = ALONG_WORK) -> bool:
    """Whether a leg's line ([lon, lat]) runs within `near` m of a work's line for at least `along` m."""
    from . import geometry
    if len(leg) < 2 or len(work) < 2:
        return False
    lat0 = work[0][1]
    pad_x, pad_y = near / geometry._kx(lat0), near / geometry.KY
    lo_x, hi_x = min(p[0] for p in work) - pad_x, max(p[0] for p in work) + pad_x
    lo_y, hi_y = min(p[1] for p in work) - pad_y, max(p[1] for p in work) + pad_y
    if max(p[0] for p in leg) < lo_x or min(p[0] for p in leg) > hi_x or max(p[1] for p in leg) < lo_y or min(p[1] for p in leg) > hi_y:
        return False
    segments = list(zip(geometry._local(work, lat0), geometry._local(work, lat0)[1:]))

    def close(p) -> bool:
        if not (lo_x <= p[0] <= hi_x and lo_y <= p[1] <= hi_y):
            return False
        [(x, y)] = geometry._local([p], lat0)
        for (ax, ay), (bx, by) in segments:
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
            if (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= near * near:
                return True
        return False
    points = geometry.densify(leg, near / 2)
    flags = [close(p) for p in points]
    length = sum(geometry.distance(a, b) for a, b, fa, fb in zip(points, points[1:], flags, flags[1:]) if fa and fb)
    return length >= along


_records: dict = {'version': None, 'value': None}


def notice_records() -> Optional[list[dict]]:
    """`records` of every date's copy from today on, worked out again only when a copy changed; None when zamudil is
    off or no copy has data."""
    if not enabled():
        return None
    lists = copies(NOTICES)
    if not lists:
        return None
    stamp = tuple((d.isoformat(), id(data)) for d, data in lists)
    if _records['version'] != stamp:
        _records.update(version=stamp, value=records(lists))
    return _records['value']

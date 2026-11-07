"""SŽ's own list of disruptions ("Ovire in izredne spremembe"), saved from a browser and uploaded by hand.

That page has 50 or so notices weeks ahead, each with its dates and, for a replacement, its timetable. It is in no open
feed: the page, its data and the infrastructure manager's list of works all answer a Cloudflare check that automated
clients are not meant to pass, so nothing here reads them. zamudil.si lists a notice only on its day and SŽ's RSS has a
few. So whoever runs the server saves the page in their own browser and runs `yarn server:update --sz <file>`
(manage.py sz_notices --import, backend/deploy/oracle/notices-remote.sh).

What the list adds:
- a replacement timetable is a record of SŽ's notices feed (`records`) for closures.py and szpdf_sync: its buses are
  planned only when the PDF reads well, as ever (closures.sz_notice_alerts), and its record makes way for zamudil's of the
  same PDF, which names the trains;
- every other notice, and a timetable that could not be read, is a text alert for its days (`alerts`). Works on the line
  ("zapora enega tira", at set hours on some of the days named) stay in the list and off the trains, or every train
  of those days would say so;
- a notice zamudil also has keeps its trains, and gets the list's title and dates: zamudil only knows today's.

SŽ can withdraw or change a notice after the upload, so /health says how old the list is (`sz:list`).
"""
import html
import json
import logging
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from django.conf import settings

from . import mapping, zamudil

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
LIMIT = 8 * 1024 * 1024  # bytes of a saved page
LIVE_FOR = 3 * 86400     # s an upload counts as fresh on /health
MAX_TEXT = 1500
PAGE = 'https://potniski.sz.si/ovire-in-izredne-spremembe/'
OPERATOR = 'IJPP:1161'
SAME_TEXT = 30           # characters: a shorter title is no proof that a notice's text is the same notice

ITEM = re.compile(r'id="heading-(\d+)"')
DAYS = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})\s*-\s*(\d{1,2})\.(\d{1,2})\.(\d{4})')
HEADING = re.compile(r'</span>(.*?)</button>', re.S)
BODY = re.compile(r'accordion-body[^>]*>(.*)', re.S)
TIMETABLE = re.compile(r'''<a\b[^>]*?href="(https://potniski\.sz\.si/[^"]+?\.pdf)"''', re.I)
BOILERPLATE = re.compile(r'Potnikom se |Hvala za razumevanje|Na portalu MOJ VLAK|Na portalu\s+MOJ')
LINK_LINE = re.compile(r'^Povezava:.*$', re.M)
TRAINS = re.compile(r'vlak\w*\s+st\.\s*((?:\d+(?:\s*,\s*|\s+in\s+)?)+)')
WORKS = 'dela na progi'

_loaded: dict = {'stamp': None, 'value': None}


def _text(body: str) -> str:
    """A notice's words without the lines every notice ends with."""
    plain = html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'<br\s*/?>', '\n', body, flags=re.I)))
    plain = re.sub(r'\s*\n\s*', '\n', re.sub(r'[ \t\xa0]+', ' ', plain)).strip()
    cut = BOILERPLATE.search(plain)
    return LINK_LINE.sub('', plain[:cut.start()] if cut else plain).strip()


def parse(page: str) -> list[dict]:
    """The notices of the list, saved whole or as just its accordion: {'id', 'from', 'to' (ISO days), 'title', 'text',
    'pdf' (the timetable it links on SŽ's own site, or None)}. A notice without its days is left out."""
    found = list(ITEM.finditer(page))
    out = []
    for i, match in enumerate(found):
        chunk = page[match.end():found[i + 1].start() if i + 1 < len(found) else len(page)]
        days, heading, body = DAYS.search(chunk), HEADING.search(chunk), BODY.search(chunk)
        if not days or not heading:
            continue
        d1, m1, y1, d2, m2, y2 = (int(x) for x in days.groups())
        try:
            first, last = date(y1, m1, d1), date(y2, m2, d2)
        except ValueError:
            continue
        title = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', heading.group(1)))).strip()
        if not title or last < first:
            continue
        pdf = TIMETABLE.search(body.group(1)) if body else None
        out.append({'id': match.group(1), 'from': first.isoformat(), 'to': last.isoformat(), 'title': title[:300],
                    'text': _text(body.group(1)) if body else '', 'pdf': html.unescape(pdf.group(1)) if pdf else None})
    return out


def left_out(page: str, notices: list[dict]) -> list[str]:
    """The page's notices parse() could not read (no days or no heading), as "<id> <title>" for the import's summary."""
    read = {n['id'] for n in notices}
    found = list(ITEM.finditer(page))
    out = []
    for i, match in enumerate(found):
        if match.group(1) in read:
            continue
        chunk = page[match.end():found[i + 1].start() if i + 1 < len(found) else len(page)]
        heading = HEADING.search(chunk)
        title = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', heading.group(1)))).strip() if heading else ''
        out.append(f'{match.group(1)} {title[:120] or "(no heading)"}')
    return out


def check(notices) -> list[dict]:
    """`notices` as parse() gives them, or ValueError: nothing else may replace the notices people see."""
    if not isinstance(notices, list) or not notices or not all(isinstance(n, dict) and n.get('id') and n.get('title') for n in notices):
        raise ValueError("no notices of SŽ's list found in it")
    return notices


def save(notices: list[dict], now: Optional[float] = None) -> None:
    """For every worker of the API and the szpdf timer: written to a temporary file, then moved over the old one."""
    path = Path(settings.PRESTOP_SZ_LIST_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps({'uploadedAt': now or time.time(), 'notices': check(notices)}, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def loaded() -> Optional[dict]:
    """{'at', 'notices', 'stamp'} of the last upload, read again only when the file changed (runs for every alert list)."""
    path = getattr(settings, 'PRESTOP_SZ_LIST_FILE', '')
    try:
        info = os.stat(path) if path else None
    except OSError:
        info = None
    stamp = (path, info.st_mtime_ns, info.st_size) if info else None
    if stamp != _loaded['stamp']:
        value = None
        if stamp:
            try:
                body = json.loads(Path(path).read_text(encoding='utf-8'))
                value = {'at': float(body['uploadedAt']), 'notices': check(body['notices']), 'stamp': stamp}
            except (OSError, ValueError, KeyError, TypeError) as e:
                logger.warning('SŽ list %s unreadable: %r', path, e)
        _loaded.update(stamp=stamp, value=value)
    return _loaded['value']


def spans(notice: dict) -> list[tuple[date, date]]:
    """The days it is in effect: those its title lists ("(9. in 30. november)" is two days, not the three weeks of the
    list's own dates) when they end where the list's do, else the list's."""
    first, last = date.fromisoformat(notice['from']), date.fromisoformat(notice['to'])
    listed = zamudil.title_spans(re.sub('[‐-―]', '-', notice['title']), first)
    if listed and listed[0][0] >= first and max(b for _, b in listed) == last:
        return listed
    return [(first, last)]


def _is_timetable(notice: dict) -> bool:
    title = mapping.fold(notice['title'])
    return bool(notice.get('pdf')) and bool(zamudil.REPLACEMENT_TITLE.search(title) or zamudil.CONNECTING_TITLE.search(title))


def records(today: date) -> list[dict]:
    """The replacement timetables of the list still in effect, as records of SŽ's notices feed. Two notices may share a
    PDF (Ljubljana - Jesenice and Lesce Bled - Jesenice): those stay two."""
    upload = loaded()
    out = []
    for n in (upload['notices'] if upload else []):
        if not _is_timetable(n):
            continue
        days = spans(n)
        if max(b for _, b in days) < today:
            continue
        link = f'<p><a href="{html.escape(n["pdf"])}">Vozni red nadomestnega prevoza</a></p>'
        words = ''.join(f'<p>{html.escape(line)}</p>' for line in n['text'].split('\n') if line.strip())
        out.append({'ID_ovire': [n['id']], 'Naslov': [n['title']], 'Relacija': [zamudil.relation(n['title'])], 'Cas': [zamudil._cas(days)],
                    'Opis': [words + link], 'CasVir': ['title'], 'Povezava': [n['pdf']], 'Vir': ['potniski.sz.si']})
    return out


def _timestamps(days: list[tuple[date, date]]) -> tuple[float, float]:
    first, last = days[0][0], days[-1][1]
    return (datetime(first.year, first.month, first.day, tzinfo=LOCAL).timestamp(),
            datetime(last.year, last.month, last.day, 23, 59, tzinfo=LOCAL).timestamp())


def _named_trains(text: str) -> set[str]:
    """The trains a notice names by number ("avtovlaki št. 853, 854, 857 in 858")."""
    return {n for match in TRAINS.finditer(mapping.fold(text)) for n in re.findall(r'\d+', match.group(1))}


def _alert(notice: dict, days: list[tuple[date, date]]) -> dict:
    from . import closures
    start, end = _timestamps(days)
    title, text = notice['title'], notice['text']
    works = mapping.fold(title).startswith(WORKS)
    trains = set() if works or _is_timetable(notice) else _named_trains(text)
    alert_id = f'sz-list:{notice["id"]}'
    alert = {'id': alert_id, 'title': title[:300], 'message': text[:MAX_TEXT] + ('…' if len(text) > MAX_TEXT else ''), 'operatorId': OPERATOR, 'stopIds': [],
             'routeIds': closures.train_routes(trains) if trains else [],
             'validFrom': mapping.iso(start), 'validTo': mapping.iso(end), 'from': mapping.iso(start), 'to': mapping.iso(end),
             'sourceUrl': notice.get('pdf') or PAGE, 'kind': 'delay' if works else mapping.alert_kind(f'{title} {text[:400]}'), 'source': 'sz',
             '_from': start, '_to': end, '_aliases': [alert_id]}
    if len(days) > 1:
        alert['_dates'] = frozenset(date.fromordinal(k).strftime('%Y%m%d') for a, b in days for k in range(a.toordinal(), b.toordinal() + 1))
    if trains:
        alert.update(_trains=frozenset(trains), _leg_notice=True)
    return alert


def _improve(alert: dict, notice: dict, days: list[tuple[date, date]]) -> None:
    """zamudil's copy of a notice in the list: it knows only the day it was listed on, and can be titled by its text."""
    _, end = _timestamps(days)
    if end > alert['_to']:
        alert.update(_to=end, validTo=mapping.iso(end), to=mapping.iso(end))
    alert.update(title=notice['title'][:300], message=notice['text'][:MAX_TEXT], sourceUrl=notice.get('pdf') or alert['sourceUrl'])


def alerts(known: list[dict], now: Optional[float] = None) -> list[dict]:
    """The list's notices in effect or still to come that `known` lacks. A notice zamudil has too is that alert, with the
    list's title and days (`known` is changed in place, and loses a second alert of the same notice)."""
    from . import closures
    upload = loaded()
    if not upload:
        return []
    now = time.time() if now is None else now
    theirs = [a for a in known if a.get('source') == 'sz']
    out = []
    for notice in upload['notices']:
        days = spans(notice)
        if _timestamps(days)[1] < now:
            continue
        title, body = closures.title_key(notice['title']), closures.title_key(notice['text'])
        same = [a for a in theirs if (key := closures.title_key(a.get('title') or '')) == title or (len(key) >= SAME_TEXT and key in body)]
        if not same:
            out.append(_alert(notice, days))
            continue
        if str(same[0]['id']).startswith(closures.ZAMUDIL_PREFIX):
            same.sort(key=lambda a: closures.title_key(a.get('title') or '') != title)
            _improve(same[0], notice, days)
            for extra in same[1:]:
                if str(extra['id']).startswith(closures.ZAMUDIL_PREFIX):
                    known.remove(extra)
                    theirs.remove(extra)
    return out


def health() -> list[dict]:
    """One /health source once a list was uploaded; none before. Never an outage for the app: the feeds still work."""
    upload = loaded()
    if not upload:
        return []
    fresh = time.time() - upload['at'] < LIVE_FOR
    at = mapping.iso(upload['at'])
    return [{'id': 'sz:list', 'name': "SŽ's list of disruptions (uploaded)", 'status': 'live' if fresh else 'stale', 'updatedAt': at, 'capabilities': ['alerts'], 'since': at}]

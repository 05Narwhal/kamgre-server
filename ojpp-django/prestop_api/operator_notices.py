"""Disruption notices from operators' own websites (contract 6, `source: 'operator-site'`).

Checked 2026-10-14, each site's robots.txt and terms first:

- Arriva (arriva.si): robots.txt allows everything but /wp-admin/; its WordPress REST API is public
  (`/wp-json/wp/v2/posts`, a post per notice: road closures, detours, timetable changes, by region); the site's
  terms (splosni-pogoji-uporabe, PDFs on ticket sales and carriage) don't restrict reading or showing its notices.
  Read here, every 15 minutes, with a link back to each post. The site has blocked networks abroad at times, the
  Oracle server's among them (2026-10-15), so `yarn server:update` also reads the posts from the deployer's PC and
  uploads them (manage.py arriva_notices, PRESTOP_ARRIVA_UPLOAD_FILE); the newest read of the two is the one shown.
- LPP (lpp.si): publishes detours as pages (detour-sitemap.xml) and robots.txt allows them, but its REST API is
  closed and its legal notice (pravno-obvestilo-2) forbids copying, distributing or republishing any of the site's
  material without prior written permission: not used. LPP's own alerts in the GTFS-RT feed still come through OTP.
- Marprom (marprom.si) and Nomago (nomago.si) both publish detours as pages (marprom.si/aktualno, checked 2026-11-01),
  but Marprom's terms (jhmb.si/splosni-pogoji/marprom) forbid copying, showing or publishing them and Nomago's
  (nomago.si/splosni-pogoji) reproducing or distributing them without permission: not read. The app links to those
  pages and LPP's instead (DisruptionsPanel); a written permission from any of them would unlock reading it here.
- SŽ (potniski.sz.si, checked 2026-11-01): robots.txt allows all but /wp-admin/; everything but its RSS answers a
  Cloudflare challenge (or blocks by client). The RSS needs none: the feed of its "Obvestila za potnike" category,
  SZ_PAGES pages of it (each 10 posts; a notice running for months is far down), read every 15 minutes with a
  conditional GET. Every post still in effect is a text alert (`sz_news_alerts`, Slovenian only, a link to the post),
  whatever other notices we have. The dated timetables a post links ("od 2. do 6. novembra", weeks before zamudil.si
  lists them for their day) are notices for closures.py and szpdf_sync (`sz_timetable_records`), so the planner has
  those days' replacement buses in advance. SŽ's "ovire-in-izredne-spremembe" page itself is in no open feed: it can
  only be saved by hand and uploaded (sz_list.py).

None of them gives a detour's changed trips in machine form, so the planner and line view keep the feed's times
and paths (what the GTFS-RT feed itself changes reaches OTP as before).
"""
import hashlib
import html
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from django.conf import settings

from . import mapping, sz_list, zamudil
from .upstream import Cached, UpstreamError, get_json, session, url_list

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
ARRIVA_POSTS = 'https://arriva.si/wp-json/wp/v2/posts'
ARRIVA_LIMIT = 4 * 1024 * 1024
MAX_AGE_DAYS = 100     # posts older than this are history; a road closure can run for months after its post
ARRIVA_POSTS_READ = 100  # Arriva posts about one a day (2026-11-01: 47 in 45 days), so this reaches that far back
UNDATED_DAYS = 7       # a notice that names no day stays this long after it was posted
MAX_TEXT = 1500
WIDE = 30              # a single place more routes than this pass (Ljubljana) doesn't pick routes
MONTHS = {'januar': 1, 'februar': 2, 'marec': 3, 'marc': 3, 'april': 4, 'maj': 5, 'junij': 6, 'julij': 7, 'avgust': 8,
          'september': 9, 'septemb': 9, 'oktob': 10, 'novemb': 11, 'decemb': 12}
NUMERIC = re.compile(r'(?<![\d.])(\d{1,2})\.\s*(\d{1,2})\s*\.\s*(\d{4})?')
NAMED = re.compile(r'(?<![\d.])(\d{1,2})\.\s*(januar|februar|marc|april|maj|junij|julij|avgust|septemb|oktob|novemb|decemb)\w*\s*(\d{4})?')
# "17. in 18. 10. 2026", "16.–17. 10. 2026": the first day borrows the month of the second.
SPAN = re.compile(r'(?<![\d.])(\d{1,2})\.\s*(?:in|–|-|do)\s*(\d{1,2})\.\s*(\d{1,2})\s*\.')
TAGS = re.compile(r'<[^>]+>')
CASE_ENDINGS = {'', 'a', 'e', 'i', 'o', 'u', 'ah', 'am', 'ami', 'em', 'ih', 'im', 'om', 'ov', 'ja', 'je', 'ji', 'jo', 'ju', 'na', 'ne', 'ni', 'no'}
NOTICE = re.compile(r'sprememb|zapor|obvoz|odpoved|ne vozi|ukin|prestavlj|nadomestn|postajalisc|zamud|dodatn\w*( \w+)? odhod')


def _fold(text: str) -> str:
    """Folded, with dashes kept as " - " (fold drops "–", which glued "Zaboršt–Ihan" into one word)."""
    return mapping.fold(re.sub('[‐-―-]', ' - ', text or ''))


def _plain(text: str) -> str:
    text = TAGS.sub(' ', html.unescape(text or ''))
    return re.sub(r'[ \t ]+', ' ', re.sub(r'\s*\n\s*', '\n', text)).strip()


def _days(text: str, posted: date) -> list[tuple[date, str]]:
    """(day, the words just before it) for every day the text names, in the order of the days."""
    folded = _fold(text)
    found = []

    def add(match, d, m, y):
        guess = posted.year + (1 if int(m) < posted.month - 6 else 0)
        for year in ([int(y), guess] if y else [guess]):  # "12. 10. 2027" in a post of October 2026 is a typo
            try:
                day = date(year, int(m), int(d))
            except ValueError:
                return
            if -30 <= (day - posted).days <= 300:  # a notice is about the coming months, not a date it mentions in passing
                found.append((day, folded[max(0, match.start() - 24):match.start()]))
                return
    for match in NUMERIC.finditer(folded):
        add(match, *match.groups())
    for match in NAMED.finditer(folded):
        d, name, y = match.groups()
        add(match, d, next(v for k, v in MONTHS.items() if name.startswith(k[:5]) or k.startswith(name)), y)
    for match in SPAN.finditer(folded):
        # "31. 10. in 1. 11." is two whole dates (NUMERIC has them), not the 10th of November.
        if not re.search(r'\d{1,2}\.\s*$', folded[max(0, match.start() - 6):match.start()]):
            add(match, match.group(1), match.group(3), None)
    return sorted(set(found))


# Whole words: "v sredo, 28. 10." is that day, not "s" + "redo" (from then on), nor "dopoldne" until then.
UNTIL = re.compile(r'\bdo\b( vkljucno)?\s*(\w+,\s*)?$')
FROM = re.compile(r'\b(od|z dnem|s)\b( dne)?\s*(\w+,\s*)?$')
FROM_DAYS = 14  # "from 12 October" with no end: shown for two weeks


def window(title: str, text: str, posted: datetime) -> tuple[float, float]:
    """(from, to) epochs: the days the notice names in its title and first lines ("do 1. novembra": from posting until
    then; "z dnem 12. 10.": from then for FROM_DAYS), else UNDATED_DAYS from posting."""
    named = _days(f'{title} {text[:600]}', posted.date())
    midnight = lambda d, h=0, m=0: datetime(d.year, d.month, d.day, h, m, tzinfo=LOCAL).timestamp()
    if not named:
        return posted.timestamp(), (posted + timedelta(days=UNDATED_DAYS)).timestamp()
    days = sorted({d for d, _ in named})
    if len(days) == 1:
        before = [b for d, b in named]
        if any(UNTIL.search(b) for b in before):
            return min(posted.timestamp(), midnight(days[0])), midnight(days[0], 23, 59)
        if any(FROM.search(b) for b in before):
            return midnight(days[0]), midnight(days[0] + timedelta(days=FROM_DAYS), 23, 59)
    return midnight(days[0]), midnight(days[-1], 23, 59)


def _load_arriva() -> list[dict]:
    """Arriva's posts of the last MAX_AGE_DAYS. Something that is not a list of posts, or none at all after there were
    some, is a failed read: the cache keeps the last posts (each notice still ends on its own day, see alerts())."""
    after = (datetime.now(LOCAL) - timedelta(days=MAX_AGE_DAYS)).strftime('%Y-%m-%dT00:00:00')
    posts = get_json(ARRIVA_POSTS, params={'per_page': ARRIVA_POSTS_READ, 'after': after, '_fields': 'id,date,link,title,content'},
                     limit=ARRIVA_LIMIT, timeout=(5, 20))
    if not isinstance(posts, list):
        logger.warning('Arriva notices: the site answered %s, not a list of posts; keeping the last ones', type(posts).__name__)
        raise UpstreamError('Arriva posts: unexpected answer')
    last = arriva.peek()
    if not posts and last and last.value:
        logger.warning('Arriva notices: the site returned no posts (it had %d); keeping the last ones', len(last.value))
        raise UpstreamError('Arriva posts: none returned')
    return posts


# A failed read keeps the last posts for as long as notices are read back (MAX_AGE_DAYS), not 6 h: Arriva's
# notices vanished from the disruptions list whenever the site was slow for a while.
arriva = Cached(_load_arriva, ttl=15 * 60, max_stale=MAX_AGE_DAYS * 86400, revalidate=15 * 60)
_routes_memo: dict = {}
_lock = threading.Lock()
_uploaded: dict = {'stamp': None, 'value': None}


def check_arriva_posts(posts) -> list[dict]:
    """`posts` as the site's list of posts, or ValueError: nothing else may replace the notices people see."""
    if not isinstance(posts, list) or not all(isinstance(p, dict) and p.get('id') and p.get('date') and isinstance(p.get('title'), dict) for p in posts):
        raise ValueError("not Arriva's list of posts")
    if not posts:
        raise ValueError('no posts (the site always has some)')
    return posts


def save_arriva_upload(posts: list[dict], now: Optional[float] = None) -> None:
    """Posts read elsewhere (`yarn server:update`) for every worker of the API: written to a temporary file, then moved
    over the old one, so nobody reads half a file."""
    path = Path(settings.PRESTOP_ARRIVA_UPLOAD_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps({'uploadedAt': now or time.time(), 'posts': check_arriva_posts(posts)}, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def arriva_upload() -> Optional[dict]:
    """{'at', 'posts'} of the last upload, read again only when the file changed (this runs for every alert list)."""
    path = getattr(settings, 'PRESTOP_ARRIVA_UPLOAD_FILE', '')
    try:
        info = os.stat(path) if path else None
    except OSError:
        info = None
    stamp = (path, info.st_mtime_ns, info.st_size) if info else None
    if stamp != _uploaded['stamp']:
        value = None
        if stamp:
            try:
                body = json.loads(Path(path).read_text(encoding='utf-8'))
                value = {'at': float(body['uploadedAt']), 'posts': check_arriva_posts(body['posts'])}
            except (OSError, ValueError, KeyError, TypeError) as e:
                logger.warning('Arriva upload %s unreadable: %r', path, e)
        _uploaded.update(stamp=stamp, value=value)
    return _uploaded['value']


def arriva_read_at() -> Optional[float]:
    """When the posts shown were read, from the site or by an upload; None when neither has any."""
    snap, upload = arriva.peek(), arriva_upload()
    return max([*([snap.fetched_at] if snap else []), *([upload['at']] if upload else [])], default=None)


def _arriva_posts() -> Optional[list[dict]]:
    """The newest read of Arriva's posts: this server's own, or the last upload."""
    snap, upload = arriva.peek(), arriva_upload()
    if upload and (not snap or upload['at'] > snap.fetched_at):
        return upload['posts']
    return snap.value if snap else None


def _place_routes(operator_routes: dict[str, set[str]]) -> dict[str, set[str]]:
    """place word -> routes of the operator passing a stop whose name starts with it."""
    out: dict[str, set[str]] = {}
    for rid, places in operator_routes.items():
        for place in places:
            out.setdefault(place, set()).add(rid)
    return out


def match_routes(text: str, by_place: dict[str, set[str]]) -> list[str]:
    """Routes passing at least two of the places the title names; a single named place picks its routes unless it
    is a hub (more than WIDE routes)."""
    words = set(re.findall(r'[a-z]{4,}', _fold(text)))
    # Slovenian declines place names ("v Škofji Loki", "iz Ljubljane"): a stem plus a case ending.
    stem = lambda p: p if len(p) < 5 else p[:-1] if len(p) < 7 else p[:-2]
    named = {p: rids for p, rids in by_place.items()
             if any(w == p or (w.startswith(stem(p)) and w[len(stem(p)):] in CASE_ENDINGS) for w in words)}
    if not named:
        return []
    if len(named) == 1:
        [rids] = named.values()
        return sorted(rids) if len(rids) <= WIDE else []
    counts: dict[str, int] = {}
    for rids in named.values():
        for r in rids:
            counts[r] = counts.get(r, 0) + 1
    return sorted(r for r, n in counts.items() if n >= 2)


def arriva_alerts(posts: list[dict], operator_id: str, by_place: dict[str, set[str]], now: Optional[float] = None) -> list[dict]:
    now = now or time.time()
    out = []
    for p in posts:
        title = _plain((p.get('title') or {}).get('rendered'))
        text = _plain((p.get('content') or {}).get('rendered'))
        if not title or not NOTICE.search(mapping.fold(f'{title} {text[:300]}')):
            continue  # news and offers, not a change to the service
        try:
            posted = datetime.fromisoformat(p['date']).replace(tzinfo=LOCAL)
        except (KeyError, ValueError, TypeError):
            continue
        start, end = window(title, text, posted)
        if end < now:
            continue
        alert_id = f'arriva:{p.get("id")}'
        out.append({
            'id': alert_id, 'title': title[:300], 'message': text[:MAX_TEXT] + ('…' if len(text) > MAX_TEXT else ''),
            'operatorId': operator_id, 'stopIds': [], 'routeIds': match_routes(title, by_place),
            'validFrom': mapping.iso(start), 'validTo': mapping.iso(end), 'from': mapping.iso(start), 'to': mapping.iso(end),
            'sourceUrl': p.get('link') or 'https://arriva.si/', 'kind': mapping.alert_kind(f'{title} {text[:400]}'), 'source': 'operator-site',
            '_from': start, '_to': end, '_aliases': [alert_id],
        })
    return out


_reading: set = set()


def _read_later(cache) -> None:
    key = id(cache)
    with _lock:
        if key in _reading:
            return
        _reading.add(key)

    def run():
        try:
            cache.get()
        except Exception as e:  # noqa: BLE001 - logged; tried again on the next request
            logger.warning('Operator notices unavailable: %r', e)
        finally:
            with _lock:
                _reading.discard(key)
    threading.Thread(target=run, daemon=True).start()


SZ_CATEGORY = 'Obvestila za potnike'
SZ_OPERATOR = 'IJPP:1161'
RSS_LIMIT = 2 * 1024 * 1024
SZ_PAGES = 5           # of the category's feed, 10 posts each: about half a year of notices
CONTENT = '{http://purl.org/rss/1.0/modules/content/}encoded'
_rss: dict = {'url': None, 'etag': None, 'modified': None}  # validators of the last full answer


def rss_items(body: bytes) -> list[dict]:
    """An RSS 2.0 document's items: {'title', 'link', 'date' (ISO, local), 'categories', 'text'}. A document that
    declares a DOCTYPE or entities is refused (no entity expansion from a feed)."""
    if b'<!DOCTYPE' in body[:4096].upper() or b'<!ENTITY' in body.upper():
        raise ValueError('RSS with a DOCTYPE')
    root = ET.fromstring(body)
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None:
        raise ValueError('not RSS')
    out = []
    for item in channel.iter('item'):
        try:
            posted = parsedate_to_datetime(item.findtext('pubDate') or '').astimezone(LOCAL)
        except (TypeError, ValueError):
            continue
        out.append({'title': (item.findtext('title') or '').strip(), 'link': (item.findtext('link') or '').strip(),
                    'date': posted.replace(tzinfo=None).isoformat(), 'categories': [(c.text or '').strip() for c in item.findall('category')],
                    'text': item.findtext(CONTENT) or item.findtext('description') or ''})
    return out


def _rss_body(url: str, resp) -> list[dict]:
    if resp.status_code != 200:
        raise UpstreamError(f'{url} returned HTTP {resp.status_code}')
    body = resp.raw.read(RSS_LIMIT + 1, decode_content=True)
    if len(body) > RSS_LIMIT:
        raise UpstreamError(f'{url} exceeds {RSS_LIMIT} bytes')
    return rss_items(body)


def _older_posts(url: str) -> list[dict]:
    """Pages 2 to SZ_PAGES of the feed; WordPress answers 404 past its last page."""
    out: list[dict] = []
    for page in range(2, SZ_PAGES + 1):
        address = f'{url}{"&" if "?" in url else "?"}paged={page}'
        with session().get(address, headers={'Accept': 'application/rss+xml, application/xml'}, timeout=(5, 20), stream=True) as resp:
            if resp.status_code == 404:
                break
            items = _rss_body(address, resp)
        if not items:
            break
        out += items
    return out


def _load_sz_news() -> list[dict]:
    """SŽ's RSS items, asked with the last answer's validators: unchanged (HTTP 304) keeps the items read before, so the
    older pages are read only when the feed changed. A page that fails leaves the validators, so it is tried again."""
    urls = url_list(getattr(settings, 'PRESTOP_SZ_NEWS_URL', ''))
    if not urls:
        return []
    last = sz_news.peek()
    error: Optional[Exception] = None
    for url in urls:
        headers = {'Accept': 'application/rss+xml, application/xml'}
        if last and _rss['url'] == url:
            headers.update({k: v for k, v in (('If-None-Match', _rss['etag']), ('If-Modified-Since', _rss['modified'])) if v})
        try:
            with session().get(url, headers=headers, timeout=(5, 20), stream=True) as resp:
                if resp.status_code == 304 and last:
                    return last.value
                items = _rss_body(url, resp)
                validators = {'url': url, 'etag': resp.headers.get('ETag'), 'modified': resp.headers.get('Last-Modified')}
            items += _older_posts(url)
            _rss.update(validators)
            return items
        except (requests.RequestException, UpstreamError, ValueError, ET.ParseError) as e:
            error = e
    raise UpstreamError(f'SŽ RSS: {error!r}')


sz_news = Cached(_load_sz_news, ttl=15 * 60, max_stale=MAX_AGE_DAYS * 86400, revalidate=15 * 60)


def _spans(text: str, seen: date) -> Optional[list[tuple[date, date]]]:
    """The days in brackets at the end of a title or link (zamudil.title_spans), also as "(od 2. do 6. novembra)" and
    with SŽ's own dashes, "(26. 9. – 11. 11. 2026)", which folding would drop."""
    text = re.sub('[‐-―]', '-', text or '')
    return zamudil.title_spans(re.sub(r'\(\s*od\s+([^()]*?)\s+do\s+', r'(\1 - ', text, flags=re.I), seen)


def _post_window(title: str, text: str, posted: datetime) -> tuple[float, float]:
    """The days a post is in effect: those its title gives, read closely ("(10., 11., 17. 10. ter 1. 11.)" is not
    10 November, as `window` would have it), else what `window` finds in its first lines."""
    spans = _spans(title, posted.date())
    if not spans:
        return window(title, text, posted)
    first, last = min(a for a, _ in spans), max(b for _, b in spans)
    return datetime(first.year, first.month, first.day, tzinfo=LOCAL).timestamp(), datetime(last.year, last.month, last.day, 23, 59, tzinfo=LOCAL).timestamp()


def sz_news_alerts(items: list[dict], now: Optional[float] = None) -> list[dict]:
    """SŽ's "Obvestila za potnike" posts as text alerts for the days they name, Slovenian only."""
    now = now or time.time()
    out = []
    for p in items:
        if SZ_CATEGORY not in p.get('categories', []) or not p.get('title'):
            continue
        try:
            posted = datetime.fromisoformat(p['date']).replace(tzinfo=LOCAL)
        except (KeyError, ValueError, TypeError):
            continue
        title, text = _plain(p['title']), _plain(p.get('text') or '')
        text = re.sub(r'\s*\[(…|&#8230;|\.\.\.)\]\s*$', '…', text)
        start, end = _post_window(title, text, posted)
        if end < now:
            continue
        alert_id = 'sz-news:' + hashlib.sha1((p.get('link') or title).encode()).hexdigest()[:12]
        out.append({
            'id': alert_id, 'title': title[:300], 'message': text[:MAX_TEXT] + ('…' if len(text) > MAX_TEXT else ''),
            'operatorId': SZ_OPERATOR, 'stopIds': [], 'routeIds': [],
            'validFrom': mapping.iso(start), 'validTo': mapping.iso(end), 'from': mapping.iso(start), 'to': mapping.iso(end),
            'sourceUrl': p.get('link') or 'https://potniski.sz.si/', 'kind': mapping.alert_kind(f'{title} {text[:400]}'), 'source': 'operator-site',
            '_from': start, '_to': end, '_aliases': [alert_id],
        })
    return out


ANCHOR = re.compile(r'''<a\b[^>]*?href\s*=\s*["']([^"']+?\.pdf)["'][^>]*>(.*?)</a>''', re.I | re.S)
TIMETABLE_LABEL = re.compile(r'vozni\s+red\s+nadomest[^\s:(]*(?:\s+prevoza)?\s*:?\s*([^()]*)', re.I)


def sz_timetable_records(items: list[dict], today: date) -> list[dict]:
    """The replacement timetables SŽ's posts link, as records of its notices feed (closures.py, szpdf_sync), one per
    timetable still in effect: `Cas` from the link's own days, else the post's (`CasVir` 'listed': the timetable's
    validity decides, closures.notice_spans). They name no trains: every bus of the timetable runs, as with SŽ's old
    feed, and only where the PDF could be read (closures.sz_notice_alerts)."""
    out = []
    for p in items:
        title = _plain(p.get('title') or '')
        if SZ_CATEGORY not in p.get('categories', []) or not zamudil.REPLACEMENT_TITLE.search(mapping.fold(title)):
            continue
        try:
            posted = datetime.fromisoformat(p['date']).date()
        except (KeyError, ValueError, TypeError):
            continue
        for href, words in ANCHOR.findall(p.get('text') or ''):
            url, label = html.unescape(href).strip(), _plain(words)
            named = TIMETABLE_LABEL.search(label)
            if not named:
                continue
            own = _spans(label, posted)
            spans = own or _spans(title, posted)
            if not spans or max(b for _, b in spans) < today:
                continue
            line = re.sub(r'\s+in obratno\s*$', '', named.group(1).strip(), flags=re.I) or zamudil.relation(title) or title
            days = re.search(r'\([^()]*\d[^()]*\)\s*$', label)
            name = f'Vozni red nadomestnega prevoza: {line}{" " + days.group(0).strip() if days else ""}'
            out.append({'ID_ovire': [zamudil.notice_number(url, line)], 'Naslov': [name[:300]], 'Relacija': [line], 'Cas': [zamudil._cas(spans)],
                        'Opis': [f'<p><a href="{html.escape(url)}">{html.escape(label)}</a></p>'], 'CasVir': ['title' if own else 'listed'],
                        'Povezava': [url], 'Vir': ['potniski.sz.si']})
    return sorted(out, key=lambda r: r['ID_ovire'][0])


def sz_alerts(known: list[dict]) -> list[dict]:
    """SŽ's passenger notices as last read, but for those `known` already has by title (never waits for the site)."""
    from . import closures
    snap = sz_news.peek()
    if snap is None:
        _read_later(sz_news)
        return []
    titles = {closures.title_key(a.get('title') or '') for a in known if a.get('source') == 'sz'}
    return [a for a in sz_news_alerts(snap.value) if closures.title_key(a['title']) not in titles]


def alerts(known: list[dict]) -> list[dict]:
    """The operators' site notices as last read (never waits for a site; warm.py keeps them fresh). `known`: the
    alerts from other sources."""
    listed = sz_list.alerts(known)  # first: it can retitle what `known` has, and the posts are checked against both
    return arriva_site_alerts() + listed + sz_alerts([*known, *listed])


def arriva_site_alerts() -> list[dict]:
    posts = _arriva_posts()
    from . import sources
    routes, pats = sources.routes.peek(), sources.patterns.peek()
    if arriva.peek() is None:
        _read_later(arriva)  # not read yet (or the last read failed): in the background, so the next request has them
    if posts is None or not routes:
        if posts is not None:
            _read_later(sources.routes)
        return []
    ids = sorted({r['agencyId'] for r in routes.value.values() if r.get('agencyId') and 'arriva' in mapping.fold(r.get('agencyName') or '')})
    if not ids:
        return []
    key = (id(posts), id(routes.value), id(pats.value) if pats else None)
    with _lock:
        if _routes_memo.get('key') != key:
            names = sources.stop_names()
            served: dict[str, set[str]] = {}
            for pat in (pats.value['patterns'] if pats else []):
                if (routes.value.get(pat['routeId']) or {}).get('agencyId') in ids:
                    served.setdefault(pat['routeId'], set()).update(w for s in pat['stops'] for w in re.findall(r'[a-z]{4,}', mapping.fold(names.get(s, '')))[:1])
            _routes_memo.update(key=key, value=arriva_alerts(posts, ids[0], _place_routes(served)))
        return [a for a in _routes_memo['value'] if a['_to'] >= time.time()]

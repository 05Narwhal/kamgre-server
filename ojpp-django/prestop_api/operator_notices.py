"""Disruption notices from operators' own websites (contract 6, `source: 'operator-site'`).

Checked 2026-10-14, each site's robots.txt and terms first:

- Arriva (arriva.si): robots.txt allows everything but /wp-admin/; its WordPress REST API is public
  (`/wp-json/wp/v2/posts`, a post per notice: road closures, detours, timetable changes, by region); the site's
  terms (splosni-pogoji-uporabe, PDFs on ticket sales and carriage) don't restrict reading or showing its notices.
  Read here, every 15 minutes, with a link back to each post.
- LPP (lpp.si): publishes detours as pages (detour-sitemap.xml) and robots.txt allows them, but its REST API is
  closed and its legal notice (pravno-obvestilo-2) forbids copying, distributing or republishing any of the site's
  material without prior written permission: not used. LPP's own alerts in the GTFS-RT feed still come through OTP.
- Marprom (marprom.si): no notices posts or feed on the site. Nomago (nomago.si): no notices page. Others: none found.
- SŽ (potniski.sz.si, checked 2026-10-26): robots.txt allows all but /wp-admin/; everything but its RSS answers a
  Cloudflare challenge. The RSS (`/feed/`, the 10 newest posts) needs none: its "Obvestila za potnike" posts become
  text alerts (`sz_news_alerts`, Slovenian only, a link to each post), read every 15 minutes with a conditional GET.
  They name no train ids, so they never make a replacement bus, and they show only while SŽ's closure notices don't
  reach us (closures.notices_source): a partial fallback that keeps the app from going silent, not a second copy.

None of them gives a detour's changed trips in machine form, so the planner and line view keep the feed's times
and paths (what the GTFS-RT feed itself changes reaches OTP as before).
"""
import hashlib
import html
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from django.conf import settings

from . import mapping
from .upstream import Cached, UpstreamError, get_json, session, url_list

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
ARRIVA_POSTS = 'https://arriva.si/wp-json/wp/v2/posts'
MAX_AGE_DAYS = 45      # posts older than this are history
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
NOTICE = re.compile(r'sprememb|zapor|obvoz|odpoved|ne vozi|ukin|prestavlj|nadomestn|postajalisc|zamud')


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
        add(match, match.group(1), match.group(3), None)
    return sorted(set(found))


UNTIL = re.compile(r'\bdo( vkljucno)?\s*(\w+,\s*)?$')
FROM = re.compile(r'\b(od|z dnem|s)( dne)?\s*(\w+,\s*)?$')
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
    posts = get_json(ARRIVA_POSTS, params={'per_page': 50, 'after': after, '_fields': 'id,date,link,title,content'},
                     limit=4 * 1024 * 1024, timeout=(5, 20))
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


def _load_sz_news() -> list[dict]:
    """SŽ's RSS items, asked with the last answer's validators: unchanged (HTTP 304) keeps the items read before."""
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
                if resp.status_code != 200:
                    raise UpstreamError(f'{url} returned HTTP {resp.status_code}')
                body = resp.raw.read(RSS_LIMIT + 1, decode_content=True)
                if len(body) > RSS_LIMIT:
                    raise UpstreamError(f'{url} exceeds {RSS_LIMIT} bytes')
                items = rss_items(body)
                _rss.update(url=url, etag=resp.headers.get('ETag'), modified=resp.headers.get('Last-Modified'))
                return items
        except (requests.RequestException, UpstreamError, ValueError, ET.ParseError) as e:
            error = e
    raise UpstreamError(f'SŽ RSS: {error!r}')


sz_news = Cached(_load_sz_news, ttl=15 * 60, max_stale=MAX_AGE_DAYS * 86400, revalidate=15 * 60)


def sz_news_alerts(items: list[dict], now: Optional[float] = None) -> list[dict]:
    """SŽ's "Obvestila za potnike" posts as text alerts for the days they name (`window`), Slovenian only."""
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
        start, end = window(title, text, posted)
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


def sz_alerts() -> list[dict]:
    """SŽ's RSS notices while its closure notices don't reach us (never waits for the site)."""
    from . import closures
    snap = sz_news.peek()
    if snap is None:
        _read_later(sz_news)
        return []
    found = sz_news_alerts(snap.value)
    return found if found and closures.notices_source()['status'] != 'live' else []


def alerts() -> list[dict]:
    """The operators' site notices as last read (never waits for a site; warm.py keeps them fresh)."""
    return arriva_site_alerts() + sz_alerts()


def arriva_site_alerts() -> list[dict]:
    snap = arriva.peek()
    from . import sources
    routes, pats = sources.routes.peek(), sources.patterns.peek()
    if snap is None or not routes:
        # Not read yet (or the last read failed): read in the background, so the next request has them.
        _read_later(arriva if snap is None else sources.routes)
        return []
    ids = sorted({r['agencyId'] for r in routes.value.values() if r.get('agencyId') and 'arriva' in mapping.fold(r.get('agencyName') or '')})
    if not ids:
        return []
    key = (id(snap.value), id(routes.value), id(pats.value) if pats else None)
    with _lock:
        if _routes_memo.get('key') != key:
            names = sources.stop_names()
            served: dict[str, set[str]] = {}
            for pat in (pats.value['patterns'] if pats else []):
                if (routes.value.get(pat['routeId']) or {}).get('agencyId') in ids:
                    served.setdefault(pat['routeId'], set()).update(w for s in pat['stops'] for w in re.findall(r'[a-z]{4,}', mapping.fold(names.get(s, '')))[:1])
            _routes_memo.update(key=key, value=arriva_alerts(snap.value, ids[0], _place_routes(served)))
        return [a for a in _routes_memo['value'] if a['_to'] >= time.time()]

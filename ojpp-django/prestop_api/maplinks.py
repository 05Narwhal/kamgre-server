"""Places from pasted map links and coordinates, so any Google Maps location can be a trip end.

Understands decimal and degree-minute-second coordinates, `geo:` URIs and Google Maps
links (`/place/Name/@lat,lng`, `!3d…!4d…` pins, `?q=`, `?query=`, `?ll=`). Short links
(`maps.app.goo.gl`, `goo.gl/maps`) are expanded by following redirects, but only while
every hop stays on a Google host, so the server never fetches an arbitrary URL.
"""
import re
import time
from typing import Optional
from urllib.parse import parse_qs, unquote_plus, urljoin, urlsplit

import requests

from .upstream import USER_AGENT

SHORT_HOSTS = {'maps.app.goo.gl', 'goo.gl', 'g.co'}
MAX_HOPS = 5
EXPAND_BUDGET = 8.0  # s for all hops together
_NUM = r'[-+]?\d{1,3}(?:\.\d+)?'
_PAIR = re.compile(rf'^\s*\(?\s*({_NUM})\s*[,;\s]\s*({_NUM})\s*\)?\s*$')
_DMS = re.compile(r'''(\d{1,3})\s*°\s*(?:(\d{1,2})\s*['′]\s*)?(?:(\d{1,2}(?:\.\d+)?)\s*(?:"|″|'')\s*)?([NSEW])''', re.I)
_PIN = re.compile(rf'!3d({_NUM})!4d({_NUM})')
_AT = re.compile(rf'@({_NUM}),({_NUM})')


def _valid(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180


def parse_coordinates(text: str) -> Optional[tuple[float, float]]:
    """`46.0514, 14.5060`, `46.0514 14.5060` or `46°03'05.0"N 14°30'21.6"E`."""
    m = _PAIR.match(text)
    if m:
        lat, lon = float(m[1]), float(m[2])
        return (lat, lon) if _valid(lat, lon) else None
    parts = _DMS.findall(text)
    if len(parts) == 2:
        values = {}
        for deg, minutes, seconds, hemi in parts:
            value = int(deg) + int(minutes or 0) / 60 + float(seconds or 0) / 3600
            hemi = hemi.upper()
            values['lat' if hemi in 'NS' else 'lon'] = -value if hemi in 'SW' else value
        if set(values) == {'lat', 'lon'} and _valid(values['lat'], values['lon']):
            return values['lat'], values['lon']
    return None


def is_google_host(host: str) -> bool:
    host = host.lower().rstrip('.')
    return host in SHORT_HOSTS or bool(re.fullmatch(r'(?:[a-z0-9-]+\.)*google\.(?:com|si|de|at|it|hr|hu|fr|es|nl|ch|be|pl|cz|sk|rs|ba|co\.uk|com\.[a-z]{2})', host))


def looks_like_link(text: str) -> bool:
    text = text.strip()
    if text.lower().startswith('geo:'):
        return True
    try:
        parts = urlsplit(text if '://' in text else f'https://{text}')
    except ValueError:
        return False
    return ' ' not in text and is_google_host(parts.hostname or '') and ('/maps' in parts.path or (parts.hostname or '').lower() in SHORT_HOSTS or 'maps.' in (parts.hostname or ''))


def parse_link(url: str) -> Optional[dict]:
    """A place (name may be None) from an expanded map link; `query` is text still to geocode."""
    url = url.strip()
    if url.lower().startswith('geo:'):
        coords = parse_coordinates(url[4:].split('?')[0])
        return {'coords': coords, 'name': None, 'query': None} if coords else None
    parts = urlsplit(url if '://' in url else f'https://{url}')
    if not is_google_host(parts.hostname or ''):
        return None
    path = unquote_plus(parts.path)
    params = {k: v[0] for k, v in parse_qs(parts.query).items() if v}
    name = None
    m = re.search(r'/place/([^/@]+)', path)
    if m:
        name = m[1].strip() or None
    coords = None
    pin = _PIN.search(url)
    if pin:
        coords = (float(pin[1]), float(pin[2]))
    query = None
    for key in ('q', 'query', 'destination', 'daddr', 'll', 'center'):
        if key in params:
            found = parse_coordinates(params[key])
            if found:
                coords = coords or found
            elif key in ('q', 'query', 'destination', 'daddr'):
                query = query or params[key]
    if not coords:
        at = _AT.search(path)
        if at:
            coords = (float(at[1]), float(at[2]))
    if coords and not _valid(*coords):
        coords = None
    if not coords and not name and not query:
        return None
    return {'coords': coords, 'name': name or query, 'query': None if coords else (name or query)}


def expand(url: str, timeout=(3, 5)) -> Optional[str]:
    """Follows a short link's redirects while they stay on Google hosts (http(s), standard ports, EXPAND_BUDGET s)."""
    current = url if '://' in url else f'https://{url}'
    deadline = time.monotonic() + EXPAND_BUDGET
    for _ in range(MAX_HOPS):
        try:
            parts = urlsplit(current)
            port = parts.port
        except ValueError:
            return None
        host = parts.hostname or ''
        if parts.scheme not in ('http', 'https') or port not in (None, 80, 443) or parts.username or not is_google_host(host):
            return None
        if (host.lower() not in SHORT_HOSTS) and '/maps' in parts.path:
            return current
        left = deadline - time.monotonic()
        if left <= 0.5:
            return None
        try:
            resp = requests.get(current, allow_redirects=False, timeout=(min(timeout[0], left), min(timeout[1], left)), stream=True, headers={'User-Agent': USER_AGENT})
            resp.close()
        except requests.RequestException:
            return None
        location = resp.headers.get('Location')
        if resp.status_code not in (301, 302, 303, 307, 308) or not location:
            return current
        current = urljoin(current, location)
    return None

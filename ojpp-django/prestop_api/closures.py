"""Replacement buses that SŽ announces but its feed does not carry.

SŽ publishes a notice for every closure ("Vozni red nadomestnega prevoza: Ljubljana - Jesenice -
Beljak (A) in obratno (26. 9. - 11. 10.)"). OTP has it as an alert whose routes are the trains it
concerns (SŽ has one route per train). For long closures the feed also has the buses ("BUS 18969",
see replacement.py); for short ones it keeps the trains on the closed track and has no bus at all.

For such a notice, each listed train that crosses the closed section while the notice is in effect
gets a synthetic replacement bus: it calls at the replacement stops of the section's stations at
the train's times, is drawn on the roads between them (scheduled.py), carries the notice, and is
always "scheduled", never a GPS position. The train is hidden on the section like for a real bus.

A notice counts as known to the feed (and gets no synthetic buses) when the feed has an SŽ bus
pattern inside the notice's section running on any day the notice is in effect: the feed's
buses then say which trains are replaced on which days, which the notice's route list cannot.

Where a replacement bus stops at a station, in order of trust: `stop_overrides.csv` replacement
rows (hand-checked), SŽ's own list of replacement stops (szstops.py), positions linked from the
notice itself (Google Maps links), SŽ's list where it is only roughly placed, the nearest bus
stop within 500 m named like the station, the station itself. The last three are `unverified`.
"""
import base64
import html
import json
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from django.conf import settings

from . import geometry, leg_alerts, maplinks, mapping, platforms, stopfix, sz, szstops
from .upstream import Cached, UpstreamError, get_json, otp

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
PREFIX = 'sub-'           # synthetic trip ids: "IJPP:sub-20261010-453228-0"; their lines: "IJPP:sub-r-<train route>"
LINE_PREFIX = PREFIX + 'r-'
NOTICE_WALK = 1500        # m: a linked or hand-checked replacement stop further than this is another station's
NEAR_STOP = 500           # m: a bus stop this close and named like the station is where the bus stops
CLOSURE = re.compile(r'nad(?:omestn\w*|\.)\s+prevoz')
LINK = re.compile(r'href="(https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|(?:www\.)?google\.[a-z.]+/maps)[^"]*)"')
NOTICE_ID = re.compile(r'SZ-OVIRA-(\d+)')


def is_synthetic(trip_id: Optional[str]) -> bool:
    """A synthetic replacement bus's trip id (or its line's id, see is_synthetic_line)."""
    return bool(trip_id) and trip_id.split(':', 1)[-1].startswith(PREFIX)


def is_synthetic_line(route_id: Optional[str]) -> bool:
    return bool(route_id) and route_id.split(':', 1)[-1].startswith(LINE_PREFIX)


def synthetic_line_id(train_route_id: str) -> str:
    """The line of the buses that replace one train (SŽ has a route per train): "IJPP:sub-r-<route>"."""
    feed, local = train_route_id.split(':', 1)
    return f'{feed}:{LINE_PREFIX}{local}'


def synthetic_day(trip_id: Optional[str]):
    """The service day in a synthetic trip id ("IJPP:sub-20261012-…" → 2026-10-12), or None."""
    local = (trip_id or '').split(':', 1)[-1]
    if not local.startswith(PREFIX) or local.startswith(LINE_PREFIX):
        return None
    try:
        return datetime.strptime(local[len(PREFIX):len(PREFIX) + 8], '%Y%m%d').date()
    except ValueError:
        return None


# ---------------------------------------------------------------- notices

def is_closure(alert: dict) -> bool:
    """A notice of buses that run *instead of* trains ("Vozni red nadomestnega prevoza"), not extra
    buses ("DODATNO: Avtobusni prevoz za vezo") or trains that end early."""
    title = mapping.fold(alert.get('title') or '')
    return alert.get('kind') == 'replacement' and bool(CLOSURE.search(title)) and not title.startswith('dodatno')


def sides(alert: dict) -> list[list[str]]:
    """The station names on each side of the notice's section, e.g. "Ljubljana / Lesce Bled - Jesenice"
    → [['ljubljana', 'lesce bled'], ['jesenice']]."""
    return [sorted(side) for side in leg_alerts.title_sections(alert.get('title') or '')]


def _tokens(name: str) -> list[str]:
    return re.findall(r'[a-z0-9]+', mapping.fold((name or '').split('(')[0]))


def names_match(notice_name: str, station: str) -> bool:
    """'Ljubljana' ~ 'Ljubljana' (not 'Ljubljana Šiška'), 'B. Bistrica' ~ 'Bohinjska Bistrica', 'Lesce Bled' ~ 'Lesce-Bled'."""
    a, b = _tokens(notice_name), _tokens(station)
    return bool(a) and len(a) == len(b) and all(y.startswith(x) for x, y in zip(a, b))


def notice_id(alert: dict) -> Optional[str]:
    """SŽ's own notice number ("11049") from the OTP alert id ("alert:" + base64 "Alert:IJPP:SZ-OVIRA-11049")."""
    for alias in alert.get('_aliases') or [alert.get('id') or '']:
        raw = alias.split(':', 1)[-1]
        try:
            text = base64.b64decode(raw + '=' * (-len(raw) % 4)).decode('utf-8', 'replace')
        except ValueError:
            text = raw
        m = NOTICE_ID.search(text)
        if m:
            return m.group(1)
    return None


def _days(alert: dict) -> set[str]:
    """Service days (YYYYMMDD) the notice is in effect on, at most a year ahead."""
    start = datetime.fromtimestamp(alert['_from'], LOCAL).date()
    end = datetime.fromtimestamp(alert['_to'], LOCAL).date() if alert.get('_to') else start + timedelta(days=366)
    end = min(end, start + timedelta(days=400))
    return {(start + timedelta(days=i)).strftime('%Y%m%d') for i in range((end - start).days + 1)}


def in_effect(alert: dict, start: float, end: float) -> bool:
    return alert['_from'] <= end and (alert.get('_to') is None or alert['_to'] >= start) and leg_alerts.on_listed_day(alert, start, end)


# ---------------------------------------------------------------- sections

def _hits(stops: list[dict], notice_sides: list[list[str]]) -> list[tuple[int, int]]:
    """(stop index, side index) of each stop named on a side of the section."""
    return [(i, k) for i, s in enumerate(stops) for k, side in enumerate(notice_sides)
            if any(names_match(n, s.get('name') or '') for n in side)]


def corridor(notice_sides: list[list[str]], trains: Iterable[dict]) -> set[str]:
    """Station keys on the closed section: every station a train passes between two of its sides."""
    out: set[str] = set()
    for t in trains:
        hits = _hits(t['stops'], notice_sides)
        if len({k for _, k in hits}) >= 2:
            lo, hi = min(i for i, _ in hits), max(i for i, _ in hits)
            out |= {sz.station_key(s.get('name') or '') for s in t['stops'][lo:hi + 1]}
    return out


def stretch(train: dict, keys: set[str]) -> Optional[tuple[int, int]]:
    """The train's longest run of consecutive stops on the section (at least two), as stop indices."""
    best, start = None, None
    names = [sz.station_key(s.get('name') or '') for s in train['stops']] + [None]
    for i, key in enumerate(names):
        if key in keys:
            start = i if start is None else start
            continue
        if start is not None and i - 1 > start and (best is None or i - 1 - start > best[1] - best[0]):
            best = (start, i - 1)
        start = None
    return best


COVER_SHARE = 0.8  # of a feed bus's service days inside a notice's days: the notice's own buses


def covered(keys: set[str], alert: dict, bus_patterns: list[tuple[str, str, frozenset]]) -> bool:
    """Whether the feed has this notice's own buses inside its section: buses that run on the notice's days and
    mostly only then. Buses running all year belong to another notice: Divača – Koper has year-round buses for
    some trains, and on 19–20 October a closure replaces every train there, which they don't cover."""
    days = _days(alert)
    first_day = datetime.fromtimestamp(alert['_from'], LOCAL).date()
    listed = leg_alerts.title_days(alert.get('title') or '', first_day.year)
    if listed:
        days &= {d.strftime('%Y%m%d') for d in listed}
    return any(first in keys and last in keys and running & days and len(running & days) >= COVER_SHARE * len(running)
               for first, last, running in bus_patterns)


# ---------------------------------------------------------------- replacement stops

def notice_points(raw_notices: list) -> dict[str, list[tuple[float, float]]]:
    """Notice number -> positions its map links point at (short links are expanded, see maplinks.py)."""
    out: dict[str, list[tuple[float, float]]] = {}
    for item in raw_notices if isinstance(raw_notices, list) else []:
        if not isinstance(item, dict):
            continue
        ids, texts = item.get('ID_ovire') or [], item.get('Opis') or []
        for i, number in enumerate(ids):
            text = html.unescape(texts[i]) if i < len(texts) and isinstance(texts[i], str) else ''
            for url in dict.fromkeys(LINK.findall(text)):
                coords = _link_coords(url)
                if coords:
                    out.setdefault(str(number), []).append(coords)
    return out


_expanded: dict[str, Optional[tuple[float, float]]] = {}


def _link_coords(url: str) -> Optional[tuple[float, float]]:
    if url not in _expanded:
        full = url if '/maps' in url and 'goo.gl' not in url else maplinks.expand(url)
        parsed = maplinks.parse_link(full) if full else None
        _expanded[url] = parsed['coords'] if parsed and parsed.get('coords') else None
    return _expanded[url]


def replacement_point(stop: dict, points: Sequence[tuple[float, float]], bus_stops: Sequence[dict], fallback: bool = True,
                      context: Sequence[str] = ()) -> Optional[dict]:
    """Where a replacement bus stops for station `stop`: {'lat', 'lon', 'unverified'} (and 'label' when
    SŽ describes the spot); None (without `fallback`) when only an unverified guess is known.
    `context`: the other stations the bus calls at (to pick the line in SŽ's list)."""
    from .sources import stop_group
    here = [stop['lon'], stop['lat']]
    for r in stopfix.replacement_stops(stop_group(stop['gtfsId'])):
        if geometry.distance(here, [r['lon'], r['lat']]) <= NOTICE_WALK:
            return {'lat': r['lat'], 'lon': r['lon'], 'unverified': False, 'label': r.get('label') or ''}
    listed = szstops.lookup(stop, context)
    if listed and not listed['unverified']:
        return listed
    near = sorted((geometry.distance(here, [lon, lat]), lat, lon) for lat, lon in points)
    if near and near[0][0] <= NOTICE_WALK:
        return {'lat': near[0][1], 'lon': near[0][2], 'unverified': False}
    if listed:  # SŽ's list, but only roughly placed: still better than a guess
        return listed
    if not fallback:
        return None
    base = ' '.join(_tokens(stop.get('name') or ''))
    named = sorted((geometry.distance(here, [s['longitude'], s['latitude']]), s) for s in bus_stops
                   if abs(s['latitude'] - stop['lat']) < 0.006 and abs(s['longitude'] - stop['lon']) < 0.009
                   and base and base in ' '.join(_tokens(s['name'])))
    if named and named[0][0] <= NEAR_STOP:
        s = named[0][1]
        return {'lat': s['latitude'], 'lon': s['longitude'], 'unverified': True}
    return {'lat': stop['lat'], 'lon': stop['lon'], 'unverified': True}


def relocate(stops: list[dict], points: Sequence[tuple[float, float]] = (), bus_stops: Sequence[dict] = (), fallback: bool = False,
             memo: Optional[dict] = None) -> list[dict]:
    """Station stops moved to where the replacement bus stops (copies; `unverified` on guesses,
    `replacementLabel` where SŽ describes the spot). `memo`: shared by the calls of one build, where the
    same stations come up again and again (a dozen trains a day on one closed line)."""
    names = [s.get('name') or '' for s in stops]
    out = []
    for s in stops:
        if s.get('lat') is None or s.get('gtfsId') is None:
            out.append(s)
            continue
        key = (s['gtfsId'], s['lat'], s['lon'], tuple(points), fallback, tuple(names))
        if memo is not None and key in memo:
            at = memo[key]
        else:
            at = replacement_point(s, points, bus_stops, fallback, context=names)
            if memo is not None:
                memo[key] = at
        if not at:
            out.append(s)
            continue
        moved = {**s, 'lat': at['lat'], 'lon': at['lon'], 'unverified': at['unverified']}
        if at.get('label'):
            moved['replacementLabel'] = at['label']
        out.append(moved)
    return out


# ---------------------------------------------------------------- synthesis

def _service_date(trip: dict) -> str:
    day = trip.get('serviceDay')
    stamp = day + 12 * 3600 if day else trip['departures'][0]
    return datetime.fromtimestamp(stamp, LOCAL).strftime('%Y%m%d')


def synthesize(trips: list[dict], real: dict[str, list[dict]], alerts: list[dict],
               bus_patterns: list[tuple[str, str, frozenset]], points: dict[str, list], bus_stops: list[dict]) -> list[dict]:
    """Synthetic replacement-bus trips (timetable trips, see scheduled.py) for SŽ closures the feed has no buses for.

    `real` are the trains real buses already replace (replacement.sections); they get none."""
    trains = [t for t in trips if not mapping.is_replacement(t['route'])
              and (t['route'].get('agency') or {}).get('gtfsId') in mapping.REPLACEMENT_AGENCIES]
    by_route: dict[str, list[dict]] = {}
    for t in trains:
        by_route.setdefault(t['route']['gtfsId'], []).append(t)
    runs: dict[tuple[str, str], dict] = {}
    for alert in alerts:
        notice_sides = sides(alert)
        if not is_closure(alert) or len(notice_sides) < 2:
            continue
        listed = [t for r in alert['routeIds'] for t in by_route.get(r, [])] if alert['routeIds'] else trains
        keys = corridor(notice_sides, listed)
        if not keys or covered(keys, alert, bus_patterns):
            continue
        for t in listed:
            span = stretch(t, keys) if t['id'] not in real else None
            if not span or not in_effect(alert, t['departures'][span[0]], t['arrivals'][span[1]]):
                continue
            run = runs.setdefault((t['id'], _service_date(t)), {'train': t, 'spans': [], 'alerts': [], 'notices': []})
            run['spans'].append(span)
            run['alerts'].append(alert['id'])
            run['notices'].append(notice_id(alert))
    out, memo = [], {}
    for (_, day), run in runs.items():
        for ia, ib in _merged(run['spans']):
            stop_points = [p for n in run['notices'] if n for p in points.get(n, [])]
            out.append(_bus(run['train'], day, ia, ib, list(dict.fromkeys(run['alerts'])), stop_points, bus_stops, memo))
    return out


def _merged(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Overlapping or touching stretches of one train (two notices meeting at a station) as one bus."""
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _bus(train: dict, day: str, ia: int, ib: int, alert_ids: list[str], points: list, bus_stops: list[dict], memo: Optional[dict] = None) -> dict:
    feed, local = train['id'].split(':', 1)
    number = sz.train_parts(mapping.route_name(train['route']))[1] or local
    stops = relocate(train['stops'][ia:ib + 1], points, bus_stops, fallback=True, memo=memo)
    # At a bus station the replacement bus leaves from its bay ("peroni 37, 38 in 39").
    stops, _ = platforms.place(stops, train['departures'][ia], stops[-1].get('name') or '')
    part = slice(ia, ib + 1)
    return {
        'id': f'{feed}:{PREFIX}{day}-{local}-{ia}', 'synthetic': True, 'trainTripId': train['id'], 'fromIndex': ia, 'toIndex': ib,
        # Its own line ("BUS 214"), so the line screen shows the bus on the roads, not the train's railway.
        'route': {'gtfsId': synthetic_line_id(train['route']['gtfsId']), 'shortName': f'BUS {number}', 'longName': '', 'mode': 'BUS',
                  'agency': train['route'].get('agency') or {'gtfsId': mapping.REPLACEMENT_AGENCIES[0]}},
        'trainRouteId': train['route']['gtfsId'], 'trainName': mapping.route_name(train['route']),
        'pattern': f'{PREFIX}{train.get("pattern")}-{ia}-{ib}', 'headsign': stops[-1].get('name'),
        'stops': stops, 'serviceDay': train.get('serviceDay'), 'serviceDate': day,
        'arrivals': train['arrivals'][part], 'departures': train['departures'][part], 'delays': train['delays'][part],
        'scheduledArrivals': (train.get('scheduledArrivals') or train['arrivals'])[part],
        'scheduledDepartures': (train.get('scheduledDepartures') or train['departures'])[part],
        'alertIds': alert_ids,
    }


def sections(buses: list[dict]) -> dict[str, list[dict]]:
    """Train trip id -> the sections synthetic buses replace (same form as replacement.sections)."""
    out: dict[str, list[dict]] = {}
    for b in buses:
        out.setdefault(b['trainTripId'], []).append({'start': b['departures'][0], 'end': b['arrivals'][-1],
                                                     'fromIndex': b['fromIndex'], 'toIndex': b['toIndex'], 'busTripId': b['id']})
    return out


# ---------------------------------------------------------------- inputs (loaded in the background)

BUS_DAYS_Q = 'query($ids: [String]) { routes(ids: $ids) { patterns { stops { name } trips { activeDates } } } }'


def _load_bus_patterns() -> list[tuple[str, str, frozenset]]:
    """(first station key, last station key, service days) of every SŽ bus pattern in the feed."""
    from .scheduled import replacement_ids
    ids = replacement_ids.get().value
    if not ids:
        return []
    out = []
    for route in otp().query(BUS_DAYS_Q, {'ids': ids}, timeout=(5, 90))['routes']:
        for p in route.get('patterns') or []:
            stops = p.get('stops') or []
            if len(stops) >= 2:
                days = frozenset(d for t in p.get('trips') or [] for d in t.get('activeDates') or [])
                out.append((sz.station_key(stops[0]['name']), sz.station_key(stops[-1]['name']), days))
    return out


def _load_points() -> dict[str, list]:
    url = getattr(settings, 'PRESTOP_SZ_NOTICES_URL', '')
    return notice_points(get_json(url, limit=8 * 1024 * 1024, timeout=(4, 20))) if url else {}


bus_patterns = Cached(_load_bus_patterns, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)
points = Cached(_load_points, ttl=6 * 3600, max_stale=7 * 86400, revalidate=6 * 3600)
_warming = threading.Lock()


def warm():
    """Load the inputs in the background (called when the timetable reloads); requests never wait on them."""
    def run():
        from . import sources
        try:
            for cache in (sources.alerts_raw, bus_patterns, points, sources.stops):
                try:
                    cache.get()
                except UpstreamError as e:
                    logger.info('Closure input unavailable: %r', e)
        finally:
            _warming.release()
    if _warming.acquire(blocking=False):
        threading.Thread(target=run, daemon=True, name='prestop-closures').start()


_fingerprint: dict = {'ref': None, 'value': None}


def notices_fingerprint(alerts_raw) -> int:
    """The notices' content: each refresh (every minute) hands back an equal list as a new object, which
    must not rebuild every synthetic bus."""
    if _fingerprint['ref'] is not alerts_raw:
        _fingerprint.update(ref=alerts_raw, value=hash(json.dumps(alerts_raw, sort_keys=True, default=str)))
    return _fingerprint['value']


def inputs():
    """(alerts, bus patterns, notice points, bus stops) when all are loaded, else None (no synthetic buses yet).
    The tuple's members are the cached values themselves, so callers can tell when one changed."""
    from . import sources
    snaps = [sources.alerts_raw.peek(), bus_patterns.peek(), points.peek(), sources.stops.peek()]
    if any(s is None for s in snaps[:2]) or snaps[3] is None:
        return None
    return snaps[0].value, snaps[1].value, snaps[2].value if snaps[2] else {}, snaps[3].value


def build(trips: list[dict], real: dict[str, list[dict]], loaded) -> list[dict]:
    alerts_raw, patterns, linked, stop_index = loaded
    alerts = mapping.build_alerts(alerts_raw, 'sl')
    bus_stops = [s for s in stop_index['list'] if 'bus' in s['modes']]
    return synthesize(trips, real, alerts, patterns, linked, bus_stops)


def unverified(buses: list[dict]) -> list[tuple[str, str]]:
    """(station id, name) of stops placed by a guess, for a person to check."""
    return sorted({(s['gtfsId'], s.get('name') or '') for b in buses for s in b['stops'] if s.get('unverified')})

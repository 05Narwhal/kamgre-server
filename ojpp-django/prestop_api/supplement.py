"""Timetables OTP has wrong, read from the operator's own GTFS.

OTP's Kranj city buses (feed MOKranj) come from a broken rebuild of the operator's GTFS: 5 of its
26 routes and ~65 of ~450 trips. The realtime feed follows the operator's full timetable, so its
buses ran trips OTP did not know: no line drawn, no stops, a line guessed from stops (wrong) and
positions that looked off their route. The operator publishes the full file (Ridango, the same one
gtfs-generators/kranj/fix_gtfs.py rebuilds), so trips, lines and stop boards of these feeds are
built here from it, in the shapes OTP returns, and fed through the same code (trips.py, sources.py).
Journeys still come from OTP.

Timetables nobody publishes as GTFS any more are kept by hand in `data/gtfs/<feedId>/` (GTFS text files,
ids as in OTP's feed so stops and lines keep theirs) and read the same way: Sevnica's file expired on
2026-06-24, so its city bus vanished, while the municipality's page lists the timetable valid from
1. 9. 2026 (see data/gtfs/README.md).
"""
import csv
import io
import logging
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from django.conf import settings

from .upstream import USER_AGENT, Cached, UpstreamError

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
LIMIT = 16 * 1024 * 1024
LOCAL_GTFS = Path(__file__).resolve().parent / 'data' / 'gtfs'

# Line colours the operator's file lacks (gtfs-generators/kranj/fix_gtfs.py).
KRANJ_COLORS = {'1': '00AEEF', '2': 'FFF200', '3': 'A54786', '4': 'EC008C', '5': '231F20', '6': '00A650',
                '7': 'F5821F', '11': '806B64', '14': '81D4F7'}


def feeds() -> dict[str, str]:
    """feedId -> GTFS zip URL, or the directory of a hand-kept feed ('' turns a feed off)."""
    out = {}
    url = getattr(settings, 'PRESTOP_KRANJ_GTFS_URL', '')
    if url:
        out['MOKranj'] = url
    if getattr(settings, 'PRESTOP_LOCAL_GTFS', True) and LOCAL_GTFS.is_dir():
        out.update({d.name: str(d) for d in sorted(LOCAL_GTFS.iterdir()) if (d / 'trips.txt').is_file()})
    return out


def _local_zip(folder: str) -> bytes:
    """A hand-kept feed's text files as a GTFS zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for f in sorted(Path(folder).glob('*.txt')):
            z.write(f, f.name)
    return buf.getvalue()


# ---------------------------------------------------------------- names (as fix_gtfs.py makes them)

def short_name(short: str, long: str) -> str:
    """'PROGA 1: …' -> '1'; a four-digit code is its middle two digits ('4153' -> '15', '4010' -> '1')."""
    if long.startswith('PROGA '):
        return long.split(':')[0].replace('PROGA ', '').strip()
    if len(short) == 4 and short[1:3].isdigit():
        return str(int(short[1:3]))
    return short


def long_name(long: str) -> str:
    """'PROGA 1: Kranj kolodvor-Qlandia' -> 'Kranj kolodvor - Qlandia'."""
    if ':' in long:
        long = long.split(':', 1)[1].strip()
    return ' - '.join(p.strip() for p in long.split('-') if p.strip()) if '-' in long else long.strip()


def seconds(hms: str) -> Optional[int]:
    """GTFS time ('25:10:00' past midnight) -> seconds after the service day's start."""
    try:
        h, m, s = (int(x) for x in hms.strip().split(':'))
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def day_start(day: date) -> int:
    """Unix time of a service day's start (local midnight), OTP's `serviceDay`."""
    return int(datetime(day.year, day.month, day.day, tzinfo=LOCAL).timestamp())


# ---------------------------------------------------------------- loading

def _rows(z: zipfile.ZipFile, name: str) -> list[dict]:
    if name not in z.namelist():
        return []
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), 'utf-8-sig')))


def parse(feed: str, data: bytes) -> dict:
    """A GTFS zip -> routes, trips, stops, shapes and services, ids prefixed with the feed."""
    z = zipfile.ZipFile(io.BytesIO(data))
    q = lambda raw: f'{feed}:{raw}'  # noqa: E731
    agencies = {a['agency_id']: a for a in _rows(z, 'agency.txt')}
    stops = {}
    for s in _rows(z, 'stops.txt'):
        try:
            stops[q(s['stop_id'])] = {'gtfsId': q(s['stop_id']), 'name': s['stop_name'].strip(), 'lat': float(s['stop_lat']), 'lon': float(s['stop_lon'])}
        except (KeyError, ValueError):
            continue
    routes = {}
    for r in _rows(z, 'routes.txt'):
        name = short_name(r.get('route_short_name') or '', r.get('route_long_name') or '')
        color = (KRANJ_COLORS.get(name) if feed == 'MOKranj' else None) or r.get('route_color') or None
        agency = agencies.get(r.get('agency_id') or '') or next(iter(agencies.values()), {})
        routes[q(r['route_id'])] = {
            'gtfsId': q(r['route_id']), 'shortName': name, 'longName': long_name(r.get('route_long_name') or ''),
            'mode': 'BUS' if (r.get('route_type') or '3') in ('3', '700', '704') else 'RAIL' if r.get('route_type') == '2' else 'BUS',
            'color': color,
            'agency': {'gtfsId': q(agency.get('agency_id') or 'unknown'), 'name': agency.get('agency_name') or '', 'url': agency.get('agency_url') or ''},
        }
    shapes: dict[str, list] = {}
    for p in _rows(z, 'shapes.txt'):
        try:
            shapes.setdefault(p['shape_id'], []).append((int(p['shape_pt_sequence']), float(p['shape_pt_lon']), float(p['shape_pt_lat'])))
        except (KeyError, ValueError):
            continue
    shapes = {k: [[round(lon, 6), round(lat, 6)] for _, lon, lat in sorted(v)] for k, v in shapes.items()}
    times: dict[str, list] = {}
    for st in _rows(z, 'stop_times.txt'):
        arr, dep = seconds(st.get('arrival_time') or ''), seconds(st.get('departure_time') or '')
        if arr is None and dep is None:
            continue
        times.setdefault(q(st['trip_id']), []).append({
            'stopId': q(st['stop_id']), 'sequence': int(st['stop_sequence']), 'arrival': arr if arr is not None else dep,
            'departure': dep if dep is not None else arr, 'pickup': st.get('pickup_type') == '1', 'dropoff': st.get('drop_off_type') == '1'})
    trips = {}
    for t in _rows(z, 'trips.txt'):
        tid, rid = q(t['trip_id']), q(t['route_id'])
        stoptimes = sorted((s for s in times.get(tid, []) if s['stopId'] in stops), key=lambda s: s['sequence'])
        if rid not in routes or len(stoptimes) < 2:
            continue
        direction = int(t['direction_id']) if (t.get('direction_id') or '') in ('0', '1') else None
        trips[tid] = {'id': tid, 'routeId': rid, 'serviceId': t['service_id'], 'headsign': long_name(t.get('trip_headsign') or ''),
                      'directionId': direction, 'shapeId': t.get('shape_id') or '', 'stops': stoptimes}
    calendar = {}
    for c in _rows(z, 'calendar.txt'):
        days = [c.get(d) == '1' for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')]
        calendar[c['service_id']] = (c['start_date'], c['end_date'], days)
    exceptions: dict[tuple[str, str], bool] = {}
    for d in _rows(z, 'calendar_dates.txt'):
        exceptions[(d['service_id'], d['date'])] = d.get('exception_type') == '1'
    by_stop: dict[str, list[tuple[str, int]]] = {}
    for tid, t in trips.items():
        for i, s in enumerate(t['stops']):
            by_stop.setdefault(s['stopId'], []).append((tid, i))
    stop_routes: dict[str, set] = {}
    for t in trips.values():
        for s in t['stops']:
            stop_routes.setdefault(s['stopId'], set()).add(t['routeId'])
    return {'feed': feed, 'routes': routes, 'trips': trips, 'stops': stops, 'shapes': shapes, 'calendar': calendar,
            'exceptions': exceptions, 'byStop': by_stop, 'stopRoutes': stop_routes}


def _load() -> dict[str, dict]:
    out = {}
    for feed, url in feeds().items():
        try:
            if not url.startswith(('http://', 'https://')):
                out[feed] = parse(feed, _local_zip(url))
                continue
            with requests.get(url, timeout=(5, 60), stream=True, headers={'User-Agent': USER_AGENT}) as resp:
                if resp.status_code != 200:
                    raise UpstreamError(f'{url} returned HTTP {resp.status_code}')
                data = resp.raw.read(LIMIT + 1, decode_content=True)
            if len(data) > LIMIT:
                raise UpstreamError(f'{url} exceeds {LIMIT} bytes')
            out[feed] = parse(feed, data)
        except (requests.RequestException, zipfile.BadZipFile, KeyError, ValueError, OSError, UpstreamError) as e:
            logger.warning('Supplementary GTFS %s failed: %r', feed, e)
    if feeds() and not out:
        raise UpstreamError('no supplementary GTFS loaded')
    return out


gtfs = Cached(_load, ttl=6 * 3600, max_stale=7 * 24 * 3600, revalidate=6 * 3600)


def _feeds() -> dict[str, dict]:
    """Loaded feeds; empty while none is configured or loadable (callers fall back to OTP)."""
    if not feeds():
        return {}
    try:
        return gtfs.get().value
    except UpstreamError:
        return {}


def _feed_of(gtfs_id: str) -> Optional[dict]:
    return _feeds().get(gtfs_id.split(':', 1)[0]) if ':' in gtfs_id else None


def owns(gtfs_id: str) -> bool:
    """Whether a trip, route or stop id belongs to a feed read here (when it loaded)."""
    return _feed_of(gtfs_id) is not None


def runs(feed: dict, service_id: str, day: date) -> bool:
    key = day.strftime('%Y%m%d')
    if (service_id, key) in feed['exceptions']:
        return feed['exceptions'][(service_id, key)]
    cal = feed['calendar'].get(service_id)
    return bool(cal) and cal[0] <= key <= cal[1] and cal[2][day.weekday()]


# ---------------------------------------------------------------- OTP-shaped records

def _stop(feed: dict, stop_id: str) -> dict:
    return dict(feed['stops'][stop_id])


def routes() -> dict[str, dict]:
    """Routes of every loaded feed, as sources._load_routes keeps OTP's."""
    out = {}
    for feed in _feeds().values():
        for rid, r in feed['routes'].items():
            agency = r['agency']
            heads = sorted({(t['directionId'], t['headsign']) for t in feed['trips'].values() if t['routeId'] == rid}, key=lambda x: (x[0] is None, x[0] or 0, x[1]))
            out[rid] = {**r, 'agencyId': agency['gtfsId'], 'agencyName': agency['name'], 'agencyUrl': agency['url'],
                        'patterns': [{'directionId': d, 'headsign': h} for d, h in heads]}
    return out


def stops() -> list[dict]:
    """Stops with the routes serving them, in the shape of sources.STOPS_Q's."""
    out = []
    for feed in _feeds().values():
        for sid, rids in feed['stopRoutes'].items():
            out.append({**_stop(feed, sid), 'vehicleMode': 'BUS', 'platformCode': None, 'parentStation': None,
                        'routes': [{'gtfsId': rid, 'mode': feed['routes'][rid]['mode'], 'agency': {'gtfsId': feed['routes'][rid]['agency']['gtfsId']}} for rid in sorted(rids)]})
    return out


def sequences() -> list[list[str]]:
    """Each distinct run of stops the trips serve, in order (stop directions, stopgroups.directions)."""
    return [list(run) for feed in _feeds().values() for run in {tuple(s['stopId'] for s in t['stops']) for t in feed['trips'].values()}]


def trip_info(trip_id: str) -> dict:
    """Route, direction and destination of a trip (sources.TripInfo's record); {} when unknown."""
    feed = _feed_of(trip_id)
    t = feed and feed['trips'].get(trip_id)
    if not t:
        return {}
    return {'routeId': t['routeId'], 'directionId': t['directionId'], 'headsign': t['headsign'],
            'destination': feed['stops'][t['stops'][-1]['stopId']]['name']}


def _pattern_code(t: dict) -> str:
    return f'{t["routeId"]}:{t["directionId"] if t["directionId"] is not None else 0}:{t["shapeId"] or len(t["stops"])}'


def _live_times(t: dict, day: date, update: Optional[dict]) -> list[dict]:
    """The trip's times on `day` in OTP's stoptimesForDate shape, with the realtime feed's delays:
    a stop's own update, else the last one before it carried forward (none before the first)."""
    start = day_start(day)
    by_seq = {}
    if update and (update.get('trip') or {}).get('startDate') in (None, '', day.strftime('%Y%m%d')):
        for u in update.get('updates') or []:
            if u.get('stopSequence') is not None:
                by_seq[int(u['stopSequence'])] = u
            elif u.get('stopId'):
                by_seq.setdefault(u['stopId'], u)
    out, delay = [], None
    for s in t['stops']:
        u = by_seq.get(s['sequence']) or by_seq.get(s['stopId'])
        state = 'SCHEDULED'
        if u:
            if u.get('scheduleRelationship') == 'SKIPPED':
                state = 'CANCELED'
            arr, dep = u.get('arrival') or {}, u.get('departure') or {}
            if arr.get('delay') is not None or dep.get('delay') is not None:
                delay_arr = int(arr['delay']) if arr.get('delay') is not None else int(dep['delay'])
                delay = int(dep['delay']) if dep.get('delay') is not None else delay_arr
            else:
                delay_arr = delay
        else:
            delay_arr = delay
        live = delay is not None or delay_arr is not None
        out.append({'stopPosition': s['sequence'], 'serviceDay': start,
                    'scheduledArrival': s['arrival'], 'scheduledDeparture': s['departure'],
                    'realtimeArrival': s['arrival'] + (delay_arr or 0), 'realtimeDeparture': s['departure'] + (delay or delay_arr or 0),
                    'realtime': live, 'realtimeState': 'UPDATED' if live and state != 'CANCELED' else state})
    if update and (update.get('trip') or {}).get('scheduleRelationship') == 'CANCELED':
        for o in out:
            o['realtimeState'] = 'CANCELED'
    return out


def otp_trip(trip_id: str, day: date, update: Optional[dict] = None) -> Optional[dict]:
    """A trip in the shape of trips.STATIC_FIELDS + TIMES_FIELDS (None when it does not run on `day`)."""
    feed = _feed_of(trip_id)
    t = feed and feed['trips'].get(trip_id)
    if not t or not runs(feed, t['serviceId'], day):
        return None
    return {
        'gtfsId': trip_id, 'directionId': t['directionId'], 'tripHeadsign': t['headsign'],
        'route': feed['routes'][t['routeId']], 'pattern': {'code': _pattern_code(t)},
        'shapeCoordinates': feed['shapes'].get(t['shapeId']) or [],
        'stoptimes': [{'stopPosition': s['sequence'], 'stop': _stop(feed, s['stopId'])} for s in t['stops']],
        'stoptimesForDate': _live_times(t, day, update),
    }


def otp_route(route_id: str, day: date) -> Optional[dict]:
    """A route in the shape of trips.LINE_Q: one pattern per distinct run of stops, with the day's trips."""
    feed = _feed_of(route_id)
    route = feed and feed['routes'].get(route_id)
    if not route:
        return None
    start = day_start(day)
    patterns: dict[tuple, dict] = {}
    for t in feed['trips'].values():
        if t['routeId'] != route_id:
            continue
        key = (t['directionId'], tuple(s['stopId'] for s in t['stops']))
        p = patterns.get(key)
        if not p:
            p = patterns[key] = {'code': _pattern_code(t), 'directionId': t['directionId'], 'headsign': t['headsign'],
                                 'stops': [_stop(feed, s['stopId']) for s in t['stops']],
                                 'shapeCoordinates': feed['shapes'].get(t['shapeId']) or [], 'tripsForDate': []}
        if runs(feed, t['serviceId'], day):
            p['tripsForDate'].append({'gtfsId': t['id'], 'departureStoptime': {'scheduledDeparture': t['stops'][0]['departure'], 'serviceDay': start}})
    # Two variants of one run (different shape ids) share a code: keep codes unique.
    seen: dict[str, int] = {}
    for p in patterns.values():
        n = seen[p['code']] = seen.get(p['code'], 0) + 1
        if n > 1:
            p['code'] = f'{p["code"]}:{n}'
    return {**route, 'patterns': list(patterns.values())}


def stoptimes(stop_id: str, start: int, span: int, limit: int, updates: dict) -> Optional[list[dict]]:
    """Calls at a stop from `start` for `span` s, in the shape of sources.BOARD_Q's stoptimesWithoutPatterns
    (None when the stop is not in a loaded feed)."""
    feed = _feed_of(stop_id)
    if not feed or stop_id not in feed['stops']:
        return None
    out = []
    first = datetime.fromtimestamp(start, LOCAL).date()
    for day in (first - timedelta(days=1), first, first + timedelta(days=1)):
        base = day_start(day)
        if base > start + span:
            continue
        for tid, i in feed['byStop'].get(stop_id, []):
            t = feed['trips'][tid]
            s = t['stops'][i]
            if not (start - 3600 <= base + s['departure'] <= start + span) or not runs(feed, t['serviceId'], day):
                continue
            live = _live_times(t, day, updates.get(tid))[i]
            if base + live['realtimeDeparture'] < start:
                continue
            route = feed['routes'][t['routeId']]
            out.append({**live, 'headsign': t['headsign'], 'stopPosition': s['sequence'],
                        'pickupType': 'NONE' if s['pickup'] else 'SCHEDULED', 'dropoffType': 'NONE' if s['dropoff'] else 'SCHEDULED',
                        'stop': {'platformCode': None},
                        'trip': {'gtfsId': tid, 'tripHeadsign': t['headsign'], 'route': route,
                                 'departureStoptime': {'stop': _stop(feed, t['stops'][0]['stopId'])},
                                 'arrivalStoptime': {'stop': _stop(feed, t['stops'][-1]['stopId'])}}})
    out.sort(key=lambda st: st['serviceDay'] + st['scheduledDeparture'])
    return out[:limit]


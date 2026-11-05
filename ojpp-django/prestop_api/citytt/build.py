"""One city's feed: fetch the operator's page and timetables, read them, place the stops, route the shapes, write
the GTFS text files and check them as supplement.py will read them (manage.py city_timetables)."""
import csv
import hashlib
import html
import importlib
import io
import json
import logging
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import requests

from django.conf import settings

from .. import geometry, mapping, roads, supplement
from ..upstream import session
from ..stopgroups import _fullest
from ..sztimetables import holiday
from ..upstream import USER_AGENT
from . import STATUS, City, poles

logger = logging.getLogger(__name__)

LIMIT = 4 * 1024 * 1024  # bytes per fetched file
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter', 'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
# the last good Overpass answer per city, in the git-ignored data/ folder: a build reuses it when no server answers
OSM_KEPT = Path(__file__).resolve().parents[2] / 'data' / 'citytt-osm'
OSM_Q = '''[out:json][timeout:180];
(node["highway"="bus_stop"]({b});node["public_transport"="platform"]["bus"="yes"]({b}););out body;
rel["type"="route"]["route"="bus"]({b});out body;'''
OFF_SHAPE = 50   # m: a stop further than this from its trip's routed shape fails the build
SERVICE = 'redni'
FETCH_GAP = 1.0  # s between two requests to the operator


class BuildError(Exception):
    pass


@dataclass
class Sources:
    """What a build reads: the page, the timetable files ({'url', 'name', 'data'}), the national feed's bus stops
    and runs, and OSM's poles and bus routes."""
    page: str
    files: list
    feed_stops: list = field(default_factory=list)
    feed_runs: list = field(default_factory=list)
    osm_stops: list = field(default_factory=list)
    osm_runs: list = field(default_factory=list)
    feed_legs: dict = field(default_factory=dict)   # a correction's: OTP's drawing of two stops in a row (feed_legs)
    national_stops: list = field(default_factory=list)  # a correction's: the national feed's poles (national_poles)


# ---------------------------------------------------------------- fetching

def _get(url: str) -> bytes:
    with requests.get(url, timeout=(10, 60), stream=True, headers={'User-Agent': USER_AGENT}) as resp:
        if resp.status_code != 200:
            raise BuildError(f'{url}: HTTP {resp.status_code}')
        data = resp.raw.read(LIMIT + 1, decode_content=True)
    if len(data) > LIMIT:
        raise BuildError(f'{url}: more than {LIMIT} bytes')
    return data


def fetch(city: City) -> tuple[str, list[dict]]:
    """The city's page (and `pages`) as text and its timetable files, fetched one after the other, a second apart.
    With `files` set, only those are read, and one that vanished or a new one the pages link (not in `stale`) fails."""
    try:
        texts = []
        for n, url in enumerate([city.page, *city.pages]):
            if n:
                time.sleep(FETCH_GAP)
            texts.append(_get(url).decode('utf-8', 'replace'))
        page = '\n'.join(texts)
        links = list(dict.fromkeys(html.unescape(u) for u in re.findall(city.links, page)))
        if not links:
            raise BuildError(f'no timetable links on {city.page}')
        if city.files:
            names = {}
            for u in links:
                names.setdefault(u.rsplit('/', 1)[-1], u)
            found = [f'{n} is no longer linked from {city.page}' + (f' or {", ".join(city.pages)}' if city.pages else '')
                     for n in city.files if n not in names]
            found += [f'{n} is new on the pages ({u}): read it and add it to the city\'s files or stale names'
                      for n, u in names.items() if n not in city.files and n not in city.stale]
            if found:
                raise BuildError('\n'.join(found))
            links = [names[n] for n in city.files]
        files = []
        for u in links:
            time.sleep(FETCH_GAP)
            files.append({'url': u, 'name': u.rsplit('/', 1)[-1], 'data': _get(u)})
        return page, files
    except requests.RequestException as e:
        raise BuildError(f'{city.name}: {e!r}') from e


def feed_poles(city: City) -> tuple[list[dict], list[list[str]]]:
    """The national feed's bus stops in the city (corrected positions, no railway stations, not this feed's own) and
    every pattern's run of stops."""
    from .. import sources
    south, west, north, east = _wider(city.bbox)
    own = lambda s: s['id'].startswith(f'{city.feed}:')  # noqa: E731
    stops = [{'id': s['id'], 'name': s['name'], 'lat': s['latitude'], 'lon': s['longitude']} for s in sources.stops.get().value['all']
             if 'rail' not in s['modes'] and own(s) == city.own_stops and south <= s['latitude'] <= north and west <= s['longitude'] <= east
             # an own OSM or national pole ('osm<node>', 'ijpp<id>', written by stop_id) comes from there again; OTP's own
             # 'osm=<node>' ids stay (Postojna)
             and not (city.own_stops and re.match(r'(osm|ijpp)\d', s['id'].split(':', 1)[1]))]
    return stops, [p['stops'] for p in sources.patterns.get().value['patterns']]


def national_poles(city: City) -> list[dict]:
    """A correction's fallback (`own_stops`): the national feed's bus stops in the city, for a stop its own feed and
    OSM both lack (Celje line 5's Čret and Teharje poles are only in IJPP)."""
    from .. import sources
    south, west, north, east = _wider(city.bbox)
    return [{'id': s['id'], 'name': s['name'], 'lat': s['latitude'], 'lon': s['longitude']} for s in sources.stops.get().value['all']
            if s['id'].startswith('IJPP:') and 'rail' not in s['modes'] and south <= s['latitude'] <= north and west <= s['longitude'] <= east]


def osm_poles(city: City) -> tuple[list[dict], list[list[str]]]:
    """OSM's bus poles in the city ({'id': 'osm:<node>', 'name', 'lat', 'lon', 'refs': {feed: stop id}}) and its bus
    route relations as runs of those poles."""
    south, west, north, east = _wider(city.bbox)
    query = OSM_Q.format(b=f'{south},{west},{north},{east}')
    elements = _overpass(city, query)
    stops = {}
    for e in elements:
        if e['type'] == 'node':
            tags = e.get('tags') or {}
            refs = {k.rsplit(':', 1)[-1].upper(): v for k, v in tags.items() if k.startswith('gtfs:stop_id:')}
            stops[e['id']] = {'id': f'osm:{e["id"]}', 'name': (tags.get('name') or '').strip(), 'lat': e['lat'], 'lon': e['lon'], 'refs': refs}
    runs = [[f'osm:{m["ref"]}' for m in e.get('members') or [] if m['type'] == 'node' and m['ref'] in stops and m['role'].startswith('platform')]
            for e in elements if e['type'] == 'relation']
    return [stops[k] for k in sorted(stops)], [r for r in runs if len(r) > 1]


def _overpass(city: City, query: str) -> list[dict]:
    """Overpass's answer to the query; with no server answering, the last answer kept for the same query."""
    kept = OSM_KEPT / f'{city.name}.json'
    for url in OVERPASS:
        try:
            resp = requests.post(url, data={'data': query}, timeout=200, headers={'User-Agent': USER_AGENT})
            resp.raise_for_status()
            elements = resp.json()['elements']
        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning('Overpass %s: %r', url, e)
            continue
        try:
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_text(json.dumps({'query': query, 'on': date.today().isoformat(), 'elements': elements}), encoding='utf-8')
        except OSError as e:
            logger.warning('Overpass answer not kept: %r', e)
        return elements
    try:
        last = json.loads(kept.read_text(encoding='utf-8'))
        if last['query'] == query:
            logger.warning('%s: no Overpass server answered, using the answer kept on %s', city.name, last['on'])
            return last['elements']
    except (OSError, ValueError, KeyError):
        pass
    raise BuildError('no Overpass server answered')


def _wider(bbox: tuple, margin: float = 0.01) -> tuple:
    south, west, north, east = bbox
    return south - margin, west - margin, north + margin, east + margin


# ---------------------------------------------------------------- the feed

def calendar(city: City, used: Optional[set] = None) -> tuple[list[dict], list[dict]]:
    """calendar.txt and calendar_dates.txt rows: the weekdays it runs, without public holidays but those it runs on
    anyway (which it then runs on whatever the weekday). A city with `services` gets rows per service (those in
    `used`, when given): a service runs on public holidays only when declared so, whatever the weekday."""
    days = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
    services = [(s[0], s[1], bool(s[2]), s[3] if len(s) > 3 else ()) for s in city.services if used is None or s[0] in used] or \
               [(SERVICE, city.weekdays, None, ())]
    breaks = dict(city.breaks)
    rows, dates = [], []
    for sid, weekdays, on_holidays, months in services:
        rows.append({'service_id': sid, **{d: str(weekdays[i]) for i, d in enumerate(days)},
                     'start_date': city.start.strftime('%Y%m%d'), 'end_date': city.end.strftime('%Y%m%d')})
        day = city.start
        while day <= city.end:
            runs = want = bool(weekdays[day.weekday()])
            if holiday(day):
                want = on_holidays if on_holidays is not None else (day.month, day.day) in city.holidays_too
            if months and day.month not in months:  # Ptuj's lines 2-5: no summer service
                want = False
            if any(first <= day <= last for first, last in breaks.get(sid, ())):  # Postojna's school runs: holidays
                want = False
            if runs != want:
                dates.append({'service_id': sid, 'date': day.strftime('%Y%m%d'), 'exception_type': '2' if runs else '1'})
            day += timedelta(days=1)
    return rows, dates


def title_case(title: str) -> str:
    """'KOROŠKA BELA (trgovina) –TOMŠIČEVA' -> 'Koroška Bela (trgovina) – Tomšičeva'."""
    title = re.sub(r'\s*[–-]\s*', ' – ', title)
    return ' '.join(w.capitalize() if w.isupper() and len(w) > 1 else w for w in title.split())


def _seconds(hhmm: str) -> int:
    h, m = hhmm.split(':')
    return int(h) * 3600 + int(m) * 60


def _hms(s: int) -> str:
    return f'{s // 3600:02d}:{s % 3600 // 60:02d}:00'


def stop_id(pole_id: str, own: str = '') -> str:
    """The feed's id for a pole: the national stop's number ('IJPP:1121067' -> '1121067'), 'osm<node>' for an OSM pole,
    and a stop of the feed the folder replaces (`own`, 'Ptuj:21' -> '21') its own id; there a national pole is
    'ijpp<number>', apart from the feed's own numbers."""
    feed, raw = pole_id.split(':', 1)
    if own and feed == 'IJPP':
        return f'ijpp{raw}'
    return raw if feed in ('IJPP', own) else f'osm{raw}' if feed == 'osm' else f'{feed}-{raw}'


def compose(city: City, tables: list[dict], place: Callable[[dict], list[str]], shape: Callable[[list[dict]], list],
            all_poles: dict[str, dict]) -> tuple[dict[str, list[dict]], list[str]]:
    """GTFS rows per file name from the read timetables. `place`: a pole id per stop of a timetable (raises
    BuildError); `shape`: the road coordinates through a run of stops."""
    problems = []
    own_id = lambda pid: stop_id(pid, city.feed if city.own_stops else '')  # noqa: E731
    used: dict[str, list[str]] = {}  # pole id -> the timetables' names for it
    routes, trips, times, shapes = [], [], [], []
    shape_ids: dict[tuple, str] = {}      # (route, direction, poles, stops) -> shape id
    trip_ids: set[str] = set()
    services: set[str] = set()
    numbers = {rid: number for _, rid, number in city.line_ids}
    # A table without a 'service' is a whole line (Jesenice); the grid reader's are per (line, direction, service).
    for t in sorted(tables, key=lambda t: (t['line'], t.get('direction', 0), t.get('service', ''))):
        route = t['line']
        ids = place(t)
        for pid, name in zip(ids, t['stops']):
            used.setdefault(pid, []).append(name)
        if not any(r['route_id'] == route for r in routes):
            routes.append({'route_id': route, 'agency_id': city.agency[0], 'route_short_name': numbers.get(route, route),
                           'route_long_name': title_case(t['title']), 'route_type': '3'})
        service, direction = t.get('service') or SERVICE, str(t.get('direction', 0))
        services.add(service)
        latest = 0  # the latest start so far: runs are printed in time order, so a start half a day earlier is after midnight
        for run in t['runs']:
            calls = [(i, _seconds(v)) for i, v in enumerate(run) if v]
            if len(calls) < 2:
                problems.append(f'{route}: a run with {len(calls)} stops')
                continue
            day = 24 * 3600 if calls[0][1] < latest - 12 * 3600 else 0  # Piran's "00:05" after 23:50 leaves that night
            latest = max(latest, calls[0][1] + day)
            fixed = []
            for i, s in calls:  # a time earlier than the one before is after midnight
                if fixed and s + day < fixed[-1][1]:
                    day += 24 * 3600
                fixed.append((i, s + day))
            # A stop printed twice in a row (Ptuj line 4: Ptuj AP 08:46, then 09:00 on) is one call, arriving and leaving.
            leaves: dict[int, int] = {}  # row of a call -> when it leaves, when later than it arrives
            calls_once: list[tuple[int, int]] = []
            for i, s in fixed:
                if calls_once and ids[calls_once[-1][0]] == ids[i]:
                    leaves[calls_once[-1][0]] = s
                else:
                    calls_once.append((i, s))
            fixed = calls_once
            key = tuple(i for i, _ in fixed)
            shape_key = (route, direction, tuple(ids[i] for i in key), tuple(t['stops'][i] for i in key))
            if shape_key not in shape_ids:
                mine = sum(1 for k in shape_ids if k[0] == route)
                shape_ids[shape_key] = route if not mine else f'{route}-{mine + 1}'
                coords = shape([{**all_poles[ids[i]], 'name': t['stops'][i]} for i in key])
                shapes += [{'shape_id': shape_ids[shape_key], 'shape_pt_lat': f'{lat:.6f}', 'shape_pt_lon': f'{lon:.6f}', 'shape_pt_sequence': str(n + 1)}
                           for n, (lon, lat) in enumerate(coords)]
            trip = f'{route}-{run[fixed[0][0]].replace(":", "")}'
            if 'service' in t:  # one line has several directions and services, and two buses may leave at one minute
                trip = f'{route}-{direction}-{service}-{run[fixed[0][0]].replace(":", "")}'
                n = 1
                while trip in trip_ids:
                    n += 1
                    trip = f'{route}-{direction}-{service}-{run[fixed[0][0]].replace(":", "")}-{n}'
            trip_ids.add(trip)
            trips.append({'route_id': route, 'service_id': service, 'trip_id': trip, 'trip_headsign': t['stops'][fixed[-1][0]],
                          'direction_id': direction, 'shape_id': shape_ids[shape_key]})
            times += [{'trip_id': trip, 'arrival_time': _hms(s), 'departure_time': _hms(leaves.get(i, s)), 'stop_id': own_id(ids[i]),
                       'stop_sequence': str(i + 1)} for i, s in fixed]
    stops = []
    for pid in sorted(used, key=own_id):
        pole = all_poles[pid]
        # A feed's pole keeps the feed's name, so the two are one marker (stopgroups merges alike names only).
        name = pole['name'] if not pid.startswith('osm:') else _fullest(sorted(set(used[pid])) + [pole['name']])
        stops.append({'stop_id': own_id(pid),'stop_name': name, 'stop_lat': f'{pole["lat"]:.6f}', 'stop_lon': f'{pole["lon"]:.6f}'})
    cal, dates = calendar(city, services if city.services else None)
    return {
        'agency.txt': [{'agency_id': city.agency[0], 'agency_name': city.agency[1], 'agency_url': city.agency[2],
                        'agency_timezone': 'Europe/Ljubljana', 'agency_lang': 'sl'}],
        'routes.txt': routes, 'stops.txt': stops, 'trips.txt': trips, 'stop_times.txt': times,
        'calendar.txt': cal, 'calendar_dates.txt': dates, 'shapes.txt': shapes,
    }, problems


def to_text(rows: list[dict]) -> str:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def check(city: City, files: dict[str, str], tables: list[dict], today: date) -> list[str]:
    """Problems with the written files as supplement.py reads them."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, text in files.items():
            z.writestr(name, text)
    feed = supplement.parse(city.feed, buf.getvalue())
    problems = []
    for line in sorted({t['line'] for t in tables}):
        n = sum(1 for trip in feed['trips'].values() if trip['routeId'] == f'{city.feed}:{line}')
        columns = sum(len(t['runs']) for t in tables if t['line'] == line)
        if n != columns:
            problems.append(f'{line}: {n} trips read back, the timetable has {columns} columns')
    for trip in feed['trips'].values():
        deps = [s['departure'] for s in trip['stops']]
        if len(deps) < 2 or deps != sorted(deps):
            problems.append(f'{trip["id"]}: {len(deps)} stops, times not in order')
        coords = feed['shapes'].get(trip['shapeId']) or []
        stops = [{'lat': feed['stops'][s['stopId']]['lat'], 'lon': feed['stops'][s['stopId']]['lon']} for s in trip['stops']]
        far = [feed['stops'][s['stopId']]['name'] for s, (_, off) in zip(trip['stops'], geometry.project_stops(coords, stops)) if off > OFF_SHAPE]
        if far:
            problems.append(f'{trip["id"]}: shape passes more than {OFF_SHAPE} m from {", ".join(far)}')
    south, west, north, east = city.bbox
    problems += [f'stop {s["name"]} lies outside {city.name}' for s in feed['stops'].values()
                 if not (south <= s['lat'] <= north and west <= s['lon'] <= east)]
    if not city.start <= today <= city.end:
        problems.append(f'the calendar {city.start}…{city.end} does not cover {today}')
    return problems


# ---------------------------------------------------------------- one build

def feed_legs(city: City) -> dict[tuple[str, str], list]:
    """For a correction (city.replaces): OTP's own drawing of every two stops in a row on the lines it corrects,
    (pole id, pole id) -> coordinates. Valhalla routes Koper's Zeleni park → Potniški terminal (2 minutes by the
    timetable) 2.2 km round the town, as OSM closes Pristaniška ulica / Kopališko nabrežje to buses; ignoring the
    access tags sends it through the old town's pedestrian streets on the local tiles (2026-11-04). OTP's line 9 has
    the same two stops in a row, drawn along the quay."""
    from .. import trips
    from ..upstream import otp
    out: dict[tuple[str, str], list] = {}
    for line, _ in city.replaces:
        route = otp().query(trips.LINE_Q, {'id': f'{city.feed}:{line}', 'date': date.today().strftime('%Y%m%d')}).get('route') or {}
        for p in route.get('patterns') or []:
            coords = mapping.decode_polyline((p.get('patternGeometry') or {}).get('points') or '')
            stops = p.get('stops') or []
            if len(coords) < 2 or len(stops) < 2:
                continue
            cum = geometry.cumulative(coords)
            at = geometry.project_stops(coords, stops)
            for (a, (da, off_a)), (b, (db, off_b)) in zip(zip(stops, at), zip(stops[1:], at[1:])):
                if off_a <= OFF_SHAPE and off_b <= OFF_SHAPE and db > da:
                    out.setdefault((a['gtfsId'], b['gtfsId']), geometry.slice_between(coords, cum, da, db))
    return out


def road_shape(points: list[dict], route=roads.route_window, known: Optional[dict] = None, borrowed: Optional[list] = None) -> list:
    """Coordinates along the roads through the stops (Valhalla, bus costing); raises BuildError on a missing or
    implausible leg. A leg that loops out of its first stop or into its last to turn round is cut where the bus first
    passes the stop, as the national feed's legs are (Piran: Bernardin K → Pirat looped 1.3 km round the roundabout).
    A leg still implausible takes the feed's own drawing of the same two poles (`known`, feed_legs), noted in `borrowed`."""
    coords: list = []
    for start in range(0, len(points) - 1, roads.MAX_LOCATIONS - 1):
        window = points[start:start + roads.MAX_LOCATIONS]
        legs = route(window)
        if not legs or len(legs) != len(window) - 1:
            raise BuildError(f'no road route through {window[0]["name"]} … {window[-1]["name"]}')
        for a, b, leg in zip(window, window[1:], legs):
            if len(leg) > 2 and not roads.plausible(leg, a, b):
                leg = roads.untangle(leg)
            if (len(leg) < 2 or not roads.plausible(leg, a, b)) and (a.get('id'), b.get('id')) in (known or {}):
                leg = known[(a['id'], b['id'])]
                if borrowed is not None:
                    borrowed.append(f'{a["name"]} → {b["name"]}')
            if len(leg) < 2 or not roads.plausible(leg, a, b):
                raise BuildError(f'no plausible road from {a["name"]} to {b["name"]}')
            coords += leg if not coords else leg[1:]
    return geometry.simplify(coords, geometry.SHAPE_POINTS)


SIDE_TOLERANCE = 2  # m: a pole this far off the road's centre line stands on a side of it (Valhalla's default is 5)


def road_length(points: list[dict]) -> Optional[float]:
    """Metres of road (Valhalla, bus costing) through the poles in order, the bus stopping with each on its right;
    None when there is no route."""
    body = {'locations': [{'lat': p['lat'], 'lon': p['lon'], 'type': 'break', 'preferred_side': 'same',
                           'street_side_tolerance': SIDE_TOLERANCE} for p in points],
            'costing': 'bus', 'directions_type': 'none'}
    resp = session().post(settings.PRESTOP_VALHALLA_URL, json=body, timeout=(5, 20))
    if resp.status_code == 400:
        return None
    resp.raise_for_status()
    return resp.json()['trip']['summary']['length'] * 1000


def spelled(city: City, tables: list[dict]) -> tuple[list[dict], list[str]]:
    """The tables with the city's own spellings named as their poles (`names`) and its stops with no pole anywhere
    left out of every run (`unplaced`), and a note for each stop left out."""
    names, out, notes = dict(city.names), [], []
    for t in tables:
        keep = [i for i, n in enumerate(t['stops']) if n not in city.unplaced]
        if len(keep) < len(t['stops']):
            notes.append(f'{t["line"]} {t.get("direction", 0)} {t.get("service", "")}: left out, no pole: '
                         + ', '.join(n for n in t['stops'] if n in city.unplaced))
        out.append({**t, 'stops': [names.get(t['stops'][i], t['stops'][i]) for i in keep],
                    'runs': [[run[i] for i in keep] for run in t['runs']]})
    return out, notes


def retitled(city: City, tables: list[dict]) -> tuple[list[dict], list[str]]:
    """A reader's line titles as OTP's route ids (city.line_ids); `unread` titles are left out, and a title the city
    knows neither way is a new line on the poster: a problem, so nobody's runs vanish unseen."""
    ids = {title: rid for title, rid, _ in city.line_ids}
    problems = [f'"{t["line"]}" is not in line_ids' for t in tables if t['line'] not in ids and t['line'] not in city.unread]
    return [{**t, 'line': ids[t['line']]} for t in tables if t['line'] in ids], problems


def corrected(city: City, tables: list[dict]) -> tuple[list[dict], list[str]]:
    """A correction's tables (city.replaces): only its lines, and of a line in `only` only the listed runs (by their
    first departure); a listed run the files no longer print is a problem, so the correction never quietly shrinks."""
    lines = {line for line, _ in city.replaces}
    only = {(line, direction): set(starts) for line, direction, starts in city.only}
    kept = dict(city.only_services)
    out, problems = [], []
    for t in tables:
        if t['line'] not in lines or t['line'] in kept and t.get('service') not in kept[t['line']]:
            continue
        wanted = only.get((t['line'], t.get('direction', 0)))
        if wanted is None:
            if not any(line == t['line'] for line, _ in only):  # a line in `only` keeps nothing else, either direction
                out.append(t)
            continue
        runs = [r for r in t['runs'] if next((v for v in r if v), None) in wanted]
        if runs:
            out.append({**t, 'runs': runs})
    for (line, direction), starts in only.items():
        found = {next((v for v in r if v), None) for t in out if (t['line'], t.get('direction', 0)) == (line, direction) for r in t['runs']}
        problems += [f'line {line} {direction}: no run leaves at {s} any more' for s in sorted(starts - found)]
    problems += [f'line {line}: not in the files' for line in sorted(lines - {t['line'] for t in out})]
    return out, problems


def build(city: City, src: Sources, today: date, route=roads.route_window, length=road_length) -> tuple[dict[str, str], dict]:
    """The feed's files (name -> text) and its status; raises BuildError with every problem found."""
    page = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', src.page)))
    problems = [] if city.days in page else [f'the page no longer says "{city.days}": the running days may have changed']
    reader = importlib.import_module(f'{__package__}.{city.reader}')
    tables = []
    for f in src.files:
        with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
            tmp.write(f['data'])
            tmp.flush()
            try:
                read = reader.parse(tmp.name)  # one table per file, or (the grid reader) one per line, direction and service
                tables += [{**t, 'file': f['name']} for t in (read if isinstance(read, list) else [read])]
            except ValueError as e:
                problems.append(f'{f["name"]}: {e}')
    notes = [f'{t["line"]} {t["direction"]} {t["service"]} ({t["file"]}): {n}' for t in tables for n in t.get('notes') or []]
    keys = [(t['line'], t.get('direction'), t.get('service')) for t in tables]
    problems += [f'line {x[0]}{" " + str(x[1]) + " " + x[2] if x[2] else ""} read from two files' for x in sorted({x for x in keys if keys.count(x) > 1}, key=str)]
    if city.line_ids:
        tables, found = retitled(city, tables)
        problems += found
    if city.replaces and not problems:
        tables, found = corrected(city, tables)
        problems += found
    if hasattr(reader, 'combine') and not problems:
        try:
            tables, found = reader.combine(tables, city)
            notes += found
        except ValueError as e:
            problems.append(str(e))
    tables, found = spelled(city, tables)
    notes += found
    renamed = {(line, code): sid for line, code, sid in city.line_services}
    tables = [{**t, 'service': renamed.get((t['line'], t['service']), t['service'])} if 'service' in t else t for t in tables]
    all_poles, alias = poles.unify(src.feed_stops, src.osm_stops)
    if src.national_stops:  # a stop neither the feed nor OSM has a pole for takes the national feed's
        lacking = {n for t in tables for n in t['stops'] if not poles.candidates(n, all_poles, city.name)}
        all_poles.update(poles.fallback(lacking, src.national_stops, city.name))
    if getattr(reader, 'OCR', False):  # a misread name no pole is named like takes the pole name it clearly is
        read_as = {n: poles.misread(n, all_poles) for t in tables for n in t['stops'] if not poles.candidates(n, all_poles, city.name)}
        tables = [{**t, 'stops': [read_as.get(n) or n for n in t['stops']]} for t in tables]
        notes += [f'read "{n}" as "{m}"' for n, m in sorted(read_as.items()) if m]
    pairs = poles.merged(poles.adjacent(src.feed_runs), poles.adjacent(src.osm_runs, alias))
    # Every distinct run of stops is placed once; one the road leaves tied then avoids the poles the other direction
    # of its line took for the same name.
    key = lambda t: (t['line'], t.get('direction', 0), tuple(t['stops']))  # noqa: E731
    placed = {key(t): poles.choose(t['stops'], all_poles, pairs, length, town=city.name) for t in tables} if not problems else {}
    for k, (chosen, found) in list(placed.items()):
        if found and not any('no pole named' in f for f in found):
            avoid: dict[str, set] = {}
            for (line, direction, stops), (other, bad) in placed.items():
                if line == k[0] and direction != k[1] and not bad:
                    for n, pid in zip(stops, other):
                        avoid.setdefault(n, set()).add(pid)
            placed[k] = poles.choose(list(k[2]), all_poles, pairs, length, avoid, town=city.name)

    def place(table: dict) -> list[str]:
        chosen, found = placed[key(table)]
        if found:
            raise BuildError('; '.join(f'{table["line"]}: {p}' for p in found))
        return chosen

    files: dict[str, str] = {}
    if not problems:
        try:
            borrowed: list[str] = []
            rows, found = compose(city, tables, place, lambda pts: road_shape(pts, route, src.feed_legs, borrowed), all_poles)
            problems += found
            notes += [f'drawn as the feed draws it (no plausible road route): {leg}' for leg in dict.fromkeys(borrowed)]
            files = {name: to_text(r) for name, r in rows.items()}
            if city.replaces:
                files['replaces.txt'] = to_text([{'route_id': line, 'mode': mode} for line, mode in city.replaces])
        except BuildError as e:
            problems.append(str(e))
    if not problems:
        problems += check(city, files, tables, today)
    if problems:
        raise BuildError('\n'.join(problems))
    hashes = [{'file': f['name'], 'url': f['url'], 'sha256': hashlib.sha256(f['data']).hexdigest()} for f in src.files]
    version = hashlib.sha256(''.join(files[k] for k in sorted(files)).encode()).hexdigest()[:12]
    files['feed_info.txt'] = to_text([{'feed_publisher_name': 'KamGre', 'feed_publisher_url': 'https://kamgre.si', 'feed_lang': 'sl',
                                       'feed_start_date': city.start.strftime('%Y%m%d'), 'feed_end_date': city.end.strftime('%Y%m%d'),
                                       'feed_version': version}])
    lines: dict[str, int] = {}
    for t in sorted(tables, key=lambda t: t['line']):
        lines[t['line']] = lines.get(t['line'], 0) + len(t['runs'])
    status = {'status': 'ok', 'version': version, 'end': city.end.isoformat(), 'source': city.page, 'files': hashes, 'lines': lines}
    if any('service' in t for t in tables):
        status['services'] = {f'{t["line"]} {"out" if t["direction"] == 0 else "back"} {t["service"]}': len(t['runs'])
                              for t in sorted(tables, key=lambda t: (t['line'], t['direction'], t['service'])) if t['runs']}
    if notes:
        status['notes'] = notes
    return files, status


def folder(city: City) -> Path:
    return supplement.LOCAL_GTFS / city.feed


def read_status(city: City) -> dict:
    try:
        return json.loads((folder(city) / STATUS).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def changes(city: City, files: dict[str, str]) -> list[str]:
    """File names whose text differs from the folder's (or that the folder lacks or has in excess)."""
    here = folder(city)
    old = {p.name: p.read_text(encoding='utf-8') for p in here.glob('*.txt')} if here.is_dir() else {}
    return sorted(n for n in set(old) | set(files) if old.get(n) != files.get(n))


def write(city: City, files: dict[str, str], status: dict, today: date) -> list[str]:
    """Replace the folder's GTFS files and status when they changed; returns the changed file names ([] when
    nothing did). `built` in the status is the day the files last changed."""
    changed = changes(city, files)
    old = read_status(city)
    if not changed and old.get('status') == 'ok' and old.get('files') == status['files']:
        return []
    here = folder(city)
    staging = Path(tempfile.mkdtemp(prefix=f'citytt-{city.feed}-'))
    try:
        for name, text in files.items():
            (staging / name).write_text(text, encoding='utf-8', newline='\n')
        here.mkdir(parents=True, exist_ok=True)
        for p in here.glob('*.txt'):
            if p.name not in files:
                p.unlink()
        for name in files:
            shutil.copyfile(staging / name, here / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _write_status(city, {**status, 'built': today.isoformat() if changed else old.get('built') or today.isoformat()})
    return changed or [STATUS]


def fail(city: City, problems: str, today: date) -> None:
    """Keep the last good files; say in the status that the newest build failed (once per distinct failure)."""
    old = read_status(city)
    found = problems.splitlines()
    if old.get('status') == 'failed' and old.get('problems') == found:
        return
    folder(city).mkdir(parents=True, exist_ok=True)
    _write_status(city, {**old, 'status': 'failed', 'problems': found, 'failedOn': today.isoformat(), 'end': old.get('end') or city.end.isoformat()})


def _write_status(city: City, status: dict) -> None:
    (folder(city) / STATUS).write_text(json.dumps(status, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')

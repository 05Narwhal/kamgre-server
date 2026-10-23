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
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import requests

from .. import geometry, roads, supplement
from ..stopgroups import _fullest
from ..sztimetables import holiday
from ..upstream import USER_AGENT
from . import STATUS, City, poles

logger = logging.getLogger(__name__)

LIMIT = 4 * 1024 * 1024  # bytes per fetched file
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter', 'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
OSM_Q = '''[out:json][timeout:90];
(node["highway"="bus_stop"]({b});node["public_transport"="platform"]["bus"="yes"]({b}););out body;
rel["type"="route"]["route"="bus"]({b});out body;'''
OFF_SHAPE = 50   # m: a stop further than this from its trip's routed shape fails the build
SERVICE = 'redni'


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
    """The city's page as text and its timetable files."""
    try:
        page = _get(city.page).decode('utf-8', 'replace')
        links = list(dict.fromkeys(html.unescape(u) for u in re.findall(city.links, page)))
        if not links:
            raise BuildError(f'no timetable links on {city.page}')
        return page, [{'url': u, 'name': u.rsplit('/', 1)[-1], 'data': _get(u)} for u in links]
    except requests.RequestException as e:
        raise BuildError(f'{city.name}: {e!r}') from e


def feed_poles(city: City) -> tuple[list[dict], list[list[str]]]:
    """The national feed's bus stops in the city (corrected positions, no railway stations, not this feed's own) and
    every pattern's run of stops."""
    from .. import sources
    south, west, north, east = _wider(city.bbox)
    stops = [{'id': s['id'], 'name': s['name'], 'lat': s['latitude'], 'lon': s['longitude']} for s in sources.stops.get().value['all']
             if 'rail' not in s['modes'] and not s['id'].startswith(f'{city.feed}:') and south <= s['latitude'] <= north and west <= s['longitude'] <= east]
    return stops, [p['stops'] for p in sources.patterns.get().value['patterns']]


def osm_poles(city: City) -> tuple[list[dict], list[list[str]]]:
    """OSM's bus poles in the city ({'id': 'osm:<node>', 'name', 'lat', 'lon', 'refs': {feed: stop id}}) and its bus
    route relations as runs of those poles."""
    south, west, north, east = _wider(city.bbox)
    query = OSM_Q.format(b=f'{south},{west},{north},{east}')
    for url in OVERPASS:
        try:
            resp = requests.post(url, data={'data': query}, timeout=150, headers={'User-Agent': USER_AGENT})
            resp.raise_for_status()
            elements = resp.json()['elements']
            break
        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning('Overpass %s: %r', url, e)
    else:
        raise BuildError('no Overpass server answered')
    stops = {}
    for e in elements:
        if e['type'] == 'node':
            tags = e.get('tags') or {}
            refs = {k.rsplit(':', 1)[-1].upper(): v for k, v in tags.items() if k.startswith('gtfs:stop_id:')}
            stops[e['id']] = {'id': f'osm:{e["id"]}', 'name': (tags.get('name') or '').strip(), 'lat': e['lat'], 'lon': e['lon'], 'refs': refs}
    runs = [[f'osm:{m["ref"]}' for m in e.get('members') or [] if m['type'] == 'node' and m['ref'] in stops and m['role'].startswith('platform')]
            for e in elements if e['type'] == 'relation']
    return [stops[k] for k in sorted(stops)], [r for r in runs if len(r) > 1]


def _wider(bbox: tuple, margin: float = 0.01) -> tuple:
    south, west, north, east = bbox
    return south - margin, west - margin, north + margin, east + margin


# ---------------------------------------------------------------- the feed

def calendar(city: City) -> tuple[list[dict], list[dict]]:
    """calendar.txt and calendar_dates.txt rows: the weekdays it runs, without public holidays but those it runs on
    anyway (which it then runs on whatever the weekday)."""
    days = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
    rows = [{'service_id': SERVICE, **{d: str(city.weekdays[i]) for i, d in enumerate(days)},
             'start_date': city.start.strftime('%Y%m%d'), 'end_date': city.end.strftime('%Y%m%d')}]
    dates, day = [], city.start
    while day <= city.end:
        runs = bool(city.weekdays[day.weekday()])
        if holiday(day) and runs != ((day.month, day.day) in city.holidays_too):
            dates.append({'service_id': SERVICE, 'date': day.strftime('%Y%m%d'), 'exception_type': '2' if runs else '1'})
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


def stop_id(pole_id: str) -> str:
    """The feed's id for a pole: the national stop's number ('IJPP:1121067' -> '1121067'), 'osm<node>' for an OSM pole."""
    feed, raw = pole_id.split(':', 1)
    return raw if feed == 'IJPP' else f'osm{raw}' if feed == 'osm' else f'{feed}-{raw}'


def compose(city: City, tables: list[dict], place: Callable[[dict], list[str]], shape: Callable[[list[dict]], list],
            all_poles: dict[str, dict]) -> tuple[dict[str, list[dict]], list[str]]:
    """GTFS rows per file name from the read timetables. `place`: a pole id per stop of a timetable (raises
    BuildError); `shape`: the road coordinates through a run of stops."""
    problems = []
    used: dict[str, list[str]] = {}  # pole id -> the timetables' names for it
    routes, trips, times, shapes = [], [], [], []
    for t in sorted(tables, key=lambda t: t['line']):
        route = t['line']
        ids = place(t)
        for pid, name in zip(ids, t['stops']):
            used.setdefault(pid, []).append(name)
        routes.append({'route_id': route, 'agency_id': city.agency[0], 'route_short_name': route,
                       'route_long_name': title_case(t['title']), 'route_type': '3'})
        shape_ids: dict[tuple, str] = {}
        for run in t['runs']:
            calls = [(i, _seconds(v)) for i, v in enumerate(run) if v]
            if len(calls) < 2:
                problems.append(f'{route}: a run with {len(calls)} stops')
                continue
            fixed, day = [], 0
            for i, s in calls:  # a time earlier than the one before is after midnight
                if fixed and s + day < fixed[-1][1]:
                    day += 24 * 3600
                fixed.append((i, s + day))
            key = tuple(i for i, _ in fixed)
            if key not in shape_ids:
                shape_ids[key] = route if not shape_ids else f'{route}-{len(shape_ids) + 1}'
                coords = shape([{**all_poles[ids[i]], 'name': t['stops'][i]} for i in key])
                shapes += [{'shape_id': shape_ids[key], 'shape_pt_lat': f'{lat:.6f}', 'shape_pt_lon': f'{lon:.6f}', 'shape_pt_sequence': str(n + 1)}
                           for n, (lon, lat) in enumerate(coords)]
            trip = f'{route}-{run[fixed[0][0]].replace(":", "")}'
            trips.append({'route_id': route, 'service_id': SERVICE, 'trip_id': trip, 'trip_headsign': t['stops'][fixed[-1][0]],
                          'direction_id': '0', 'shape_id': shape_ids[key]})
            times += [{'trip_id': trip, 'arrival_time': _hms(s), 'departure_time': _hms(s), 'stop_id': stop_id(ids[i]), 'stop_sequence': str(i + 1)}
                      for i, s in fixed]
    stops = []
    for pid in sorted(used, key=stop_id):
        pole = all_poles[pid]
        # A feed's pole keeps the feed's name, so the two are one marker (stopgroups merges alike names only).
        name = pole['name'] if not pid.startswith('osm:') else _fullest(sorted(set(used[pid])) + [pole['name']])
        stops.append({'stop_id': stop_id(pid), 'stop_name': name, 'stop_lat': f'{pole["lat"]:.6f}', 'stop_lon': f'{pole["lon"]:.6f}'})
    cal, dates = calendar(city)
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
    for t in tables:
        n = sum(1 for trip in feed['trips'].values() if trip['routeId'] == f'{city.feed}:{t["line"]}')
        if n != len(t['runs']):
            problems.append(f'{t["line"]}: {n} trips read back, the timetable has {len(t["runs"])} columns')
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

def road_shape(points: list[dict], route=roads.route_window) -> list:
    """Coordinates along the roads through the stops (Valhalla, bus costing); raises BuildError on a missing or
    implausible leg."""
    coords: list = []
    for start in range(0, len(points) - 1, roads.MAX_LOCATIONS - 1):
        window = points[start:start + roads.MAX_LOCATIONS]
        legs = route(window)
        if not legs or len(legs) != len(window) - 1:
            raise BuildError(f'no road route through {window[0]["name"]} … {window[-1]["name"]}')
        for a, b, leg in zip(window, window[1:], legs):
            if len(leg) < 2 or not roads.plausible(leg, a, b):
                raise BuildError(f'no plausible road from {a["name"]} to {b["name"]}')
            coords += leg if not coords else leg[1:]
    return geometry.simplify(coords, geometry.SHAPE_POINTS)


def build(city: City, src: Sources, today: date, route=roads.route_window) -> tuple[dict[str, str], dict]:
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
                tables.append({**reader.parse(tmp.name), 'file': f['name']})
            except ValueError as e:
                problems.append(f'{f["name"]}: {e}')
    lines = [t['line'] for t in tables]
    problems += [f'line {x} read from two files' for x in sorted({x for x in lines if lines.count(x) > 1})]
    all_poles, alias = poles.unify(src.feed_stops, src.osm_stops)
    pairs = poles.merged(poles.adjacent(src.feed_runs), poles.adjacent(src.osm_runs, alias))

    def place(table: dict) -> list[str]:
        chosen, found = poles.choose(table['stops'], all_poles, pairs)
        if found:
            raise BuildError('; '.join(f'{table["line"]}: {p}' for p in found))
        return chosen

    files: dict[str, str] = {}
    if not problems:
        try:
            rows, found = compose(city, tables, place, lambda pts: road_shape(pts, route), all_poles)
            problems += found
            files = {name: to_text(r) for name, r in rows.items()}
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
    status = {'status': 'ok', 'version': version, 'end': city.end.isoformat(), 'source': city.page, 'files': hashes,
              'lines': {t['line']: len(t['runs']) for t in sorted(tables, key=lambda t: t['line'])}}
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

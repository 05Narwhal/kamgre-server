"""Place bus stops on the road the lines through them use (M9, rules in stopplace.py). Report first, then apply.

    manage.py place_stops --poles poles.json            # report only (docs/research/2026-11-04-stop-placement.csv)
    manage.py place_stops --poles poles.json --write    # also write data/stop_places.json, which stopfix applies
    manage.py place_stops --feeds IJPP --stops IJPP:1123642,IJPP:1123643

Each bus pattern's shape is its feed shape map-matched onto the roads, as served (`roads.matched`), read from the
RoadLeg cache only: the command sends no Valhalla request (a pattern not matched yet gives no answer; run
`manage.py road_shapes --match` first). `--poles` is a JSON {stop id: [lat, lon]} of OSM poles tagged
`gtfs:stop_id:<feed>` (extracted from the OSM file with pyosmium, which the server's venv lacks).

Positions start from what is served without placement (stop_overrides.csv, then the old road snap, then the feed);
stops with a hand row in stop_overrides.csv and bus stations (their bays) are left alone. A move that would change
the order of stops along any line through the stop is dropped ('order'). The cache is keyed by the feed position,
so a re-run gives the same file and a stop the feed moves is placed afresh.
"""
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand

from prestop_api import geometry, mapping, roads, stopfix, stopplace
from prestop_api.upstream import otp

ROUTES_Q = '{ routes(transportModes: [BUS, COACH]) { gtfsId } }'
PATTERNS_Q = '''query($ids: [String]) { routes(ids: $ids) { gtfsId shortName mode agency { gtfsId }
  patterns { code stops { gtfsId name lat lon } patternGeometry { points } } } }'''
CHUNK = 100
REPORT = Path(__file__).resolve().parents[5] / 'docs' / 'research' / '2026-11-04-stop-placement.csv'
ORDER_SLACK = 5.0  # m: in stop order, a moved stop must project where it would on its own near its line's pass
AROUND = 80.0      # m along the line either side of the pass searched for that projection
BUCKETS = ((8, '< 8 m'), (15, '8-15 m'), (30, '15-30 m'), (60, '30-60 m'), (float('inf'), '> 60 m'))


def bucket(metres: float) -> str:
    return next(label for top, label in BUCKETS if metres < top or top == float('inf'))


def local_along(coords: list, cum: list[float], lat: float, lon: float, near: float) -> float:
    """Metres along the shape of the point nearest (lat, lon) within AROUND of `near` (the stop's pass)."""
    kx = stopplace._kx(lat)
    px, py = lon * kx, lat * geometry.KY
    best = (float('inf'), near)
    for i in range(len(coords) - 1):
        if cum[i + 1] < near - AROUND or cum[i] > near + AROUND:
            continue
        ax, ay, bx, by = coords[i][0] * kx, coords[i][1] * geometry.KY, coords[i + 1][0] * kx, coords[i + 1][1] * geometry.KY
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
        d = math.hypot(ax + t * dx - px, ay + t * dy - py)
        if d < best[0]:
            best = (d, cum[i] + t * (cum[i + 1] - cum[i]))
    return best[1]


class Command(BaseCommand):
    help = 'Place bus stops on the road their lines use (stopplace.py): report, and with --write the stop_places.json cache.'

    def add_arguments(self, parser):
        parser.add_argument('--feeds', default='', help='comma-separated feed prefixes')
        parser.add_argument('--stops', default='', help='comma-separated stop ids: report only these')
        parser.add_argument('--poles', default='', help='JSON {stop id: [lat, lon]} of OSM poles tagged with the stop id')
        parser.add_argument('--report', default=str(REPORT), help='CSV report path')
        parser.add_argument('--write', action='store_true', help='write data/stop_places.json')

    def handle(self, *args, feeds='', stops='', poles='', report=str(REPORT), write=False, **options):
        overrides, snaps = stopfix.tables()
        base = {k: v for k, v in snaps.items() if k != stopfix.PLACED}  # served positions without placement
        tagged = {k: tuple(v) for k, v in json.loads(Path(poles).read_text(encoding='utf-8')).items()} if poles else {}
        patterns = self._patterns([f for f in feeds.split(',') if f], overrides, base)
        only = {s for s in stops.split(',') if s}
        self.stdout.write(f'{len(patterns)} bus patterns, {sum(1 for p in patterns if p["shape"])} map-matched; {len(tagged)} tagged OSM poles')

        passes, info = self._passes(patterns, overrides)
        answers = {}
        for sid, stop in info.items():
            if stop.get('skip'):
                answers[sid] = {'lat': stop['lat'], 'lon': stop['lon'], 'metres': 0.0, 'why': stop['skip'], 'move': False}
            else:
                answers[sid] = stopplace.place(stop['lat'], stop['lon'], [p[:3] for p in passes[sid]], tagged.get(sid))
        dropped = self._keep_order(patterns, answers, passes)
        legs = self._legs(patterns, answers)

        rows = [self._row(sid, info[sid], answers[sid], len(passes[sid])) for sid in sorted(info) if not only or sid in only]
        if not only:  # stops already within MIN_MOVE of their place are only counted
            self._report(Path(report), [r for r in rows if r['why'] != 'close'])
        moved = {sid: a for sid, a in answers.items() if a['move']}
        self.stdout.write(f'{len(info)} bus stops; {len(moved)} to move ({dropped} moves dropped to keep stop order)')
        self.stdout.write('by distance (all with a place): ' + ', '.join(
            f'{label} {n}' for label, n in sorted(Counter(bucket(a['metres']) for a in answers.values() if a['why'] not in ('no line', 'no matched shape', 'override', 'bus station')).items(),
                                                  key=lambda kv: [b[1] for b in BUCKETS].index(kv[0]))))
        self.stdout.write('why: ' + ', '.join(f'{w} {n}' for w, n in Counter(a['why'] for a in answers.values()).most_common()))
        self.stdout.write(f'legs: {legs["before"]} stop-to-stop legs routed before, {legs["after"]} after; '
                          f'{legs["new"]} not in the RoadLeg cache yet (manage.py road_shapes routes them)')
        if only:
            for row in rows:
                self.stdout.write(json.dumps(row, ensure_ascii=False))
        if write:
            cache = {stopfix.snap_key(sid, info[sid]['feedLat'], info[sid]['feedLon']): [a['lat'], a['lon'], a['metres'], a['why']]
                     for sid, a in sorted(moved.items())}
            stopfix.PLACES.write_text(json.dumps(cache, indent=0, sort_keys=True) + '\n', encoding='utf-8')
            self.stdout.write(f'wrote {len(cache)} places to {stopfix.PLACES}')

    # ------------------------------------------------------------ input

    def _patterns(self, feeds: list[str], overrides: dict, snaps: dict) -> list[dict]:
        ids = [r['gtfsId'] for r in otp().query(ROUTES_Q, timeout=(5, 90))['routes']]
        if feeds:
            ids = [i for i in ids if i.split(':', 1)[0] in feeds]
        out = []
        for n in range(0, len(ids), CHUNK):
            for route in otp().query(PATTERNS_Q, {'ids': ids[n:n + CHUNK]}, timeout=(5, 120))['routes']:
                if mapping.is_replacement(route):
                    continue  # SŽ replacement buses stop at closures.py's replacement stops
                for p in route.get('patterns') or []:
                    raw = [s for s in p.get('stops') or [] if s.get('lat') is not None]
                    if len(raw) < 2:
                        continue
                    stops = [{**c, 'feedLat': s['lat'], 'feedLon': s['lon']} for s, c in zip(raw, stopfix.correct(raw, overrides, snaps))]
                    coords = mapping.decode_polyline((p.get('patternGeometry') or {}).get('points') or '')
                    out.append({'route': route['gtfsId'], 'code': p['code'], 'stops': stops, 'coords': coords})
        keys = {roads.match_key(p['coords']) for p in out if not roads.shapeless(p['coords'], p['stops'])}
        found = {}
        keys = sorted(keys)
        for n in range(0, len(keys), 500):
            found.update(roads.legs.get_many(keys[n:n + 500]))
        for p in out:
            shape = None if roads.shapeless(p['coords'], p['stops']) else found.get(roads.match_key(p['coords']))
            p['shape'] = shape if shape and len(shape) >= 2 else None
            p['cum'] = geometry.cumulative(p['shape']) if p['shape'] else None
        return out

    def _passes(self, patterns: list[dict], overrides: dict) -> tuple[dict, dict]:
        """stop id -> [(lat, lon, heading, pattern index, stop index, along)] where each matched pattern passes it, and
        stop id -> its served position (and why it is skipped)."""
        passes, info = defaultdict(list), {}
        for n, p in enumerate(patterns):
            proj = geometry.project_stops(p['shape'], p['stops']) if p['shape'] else None
            cum = p['cum']
            for i, s in enumerate(p['stops']):
                sid = s['gtfsId']
                if sid not in info:
                    skip = 'override' if sid in overrides['stops'] else 'bus station' if roads.bus_station(s) else None
                    info[sid] = {'name': s.get('name') or '', 'lat': s['lat'], 'lon': s['lon'],
                                 'feedLat': s['feedLat'], 'feedLon': s['feedLon'], 'skip': skip}
                if proj and proj[i][1] <= roads.OFF_SHAPE:
                    passes[sid].append((*stopplace.passing(p['shape'], cum, proj[i][0]), n, i, proj[i][0]))
        on_matched = {s['gtfsId'] for p in patterns if p['shape'] for s in p['stops']}
        for sid, stop in info.items():
            if not stop['skip'] and not passes[sid]:
                stop['skip'] = 'no line' if sid in on_matched else 'no matched shape'
        return passes, info

    def _keep_order(self, patterns: list[dict], answers: dict, passes: dict) -> int:
        """Drop moves after which a stop no longer projects where its line passes it (order along a line changed)."""
        dropped = 0
        for _ in range(3):
            bad = set()
            for n, p in enumerate(patterns):
                if not p['shape'] or not any(answers[s['gtfsId']]['move'] for s in p['stops']):
                    continue
                moved = [{**s, 'lat': answers[s['gtfsId']]['lat'], 'lon': answers[s['gtfsId']]['lon']} if answers[s['gtfsId']]['move'] else s
                         for s in p['stops']]
                proj = geometry.project_stops(p['shape'], moved)
                for i, s in enumerate(p['stops']):
                    a = answers[s['gtfsId']]
                    if not a['move']:
                        continue
                    near = next((x[5] for x in passes[s['gtfsId']] if x[3] == n and x[4] == i), None)
                    want = None if near is None else local_along(p['shape'], p['cum'], a['lat'], a['lon'], near)
                    if want is None or abs(proj[i][0] - want) > ORDER_SLACK:
                        bad.add(s['gtfsId'])
            if not bad:
                break
            for sid in bad:
                answers[sid] = {**answers[sid], 'move': False, 'why': 'order'}
            dropped += len(bad)
        return dropped

    def _legs(self, patterns: list[dict], answers: dict) -> dict:
        """Routed stop-to-stop legs (as roads.repair would route them) before and after the moves."""
        before, after = set(), set()
        for p in patterns:
            if not p['shape']:
                continue
            moved = [{**s, 'lat': answers[s['gtfsId']]['lat'], 'lon': answers[s['gtfsId']]['lon']} if answers[s['gtfsId']]['move'] else s
                     for s in p['stops']]
            for stops, keys in ((p['stops'], before), (moved, after)):
                bad = roads.into_stations(p['shape'], stops, roads.bad_segments(p['shape'], stops, {}))
                keys.update(roads.leg_key(stops[i], stops[i + 1]) for i, b in enumerate(bad) if b)
        new = sorted(after - before)
        cached = set()
        for n in range(0, len(new), 500):
            cached.update(roads.legs.get_many(new[n:n + 500]))
        return {'before': len(before), 'after': len(after), 'new': len(set(new) - cached)}

    # ------------------------------------------------------------ output

    @staticmethod
    def _row(sid: str, stop: dict, answer: dict, lines: int) -> dict:
        return {'stop': sid, 'name': stop['name'], 'from_lat': stop['lat'], 'from_lon': stop['lon'],
                'to_lat': answer['lat'], 'to_lon': answer['lon'], 'metres': answer['metres'], 'why': answer['why'],
                'applied': 'yes' if answer['move'] else '', 'passes': lines}

    @staticmethod
    def _report(path: Path, rows: list[dict]):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['stop', 'name', 'from_lat', 'from_lon', 'to_lat', 'to_lon', 'metres', 'why', 'applied', 'passes'])
            writer.writeheader()
            writer.writerows(rows)

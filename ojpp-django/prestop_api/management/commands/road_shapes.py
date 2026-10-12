"""Check every bus shape against the roads and route the stretches that are off them, ahead of serving.

    manage.py road_shapes                         # all bus patterns: check, then route what is off the road
    manage.py road_shapes --routes LPP:6,IJPP:x   # only these routes
    manage.py road_shapes --feeds LPP,MARPROM     # only these feeds
    manage.py road_shapes --max-requests 200      # stop after this many Valhalla requests (re-run to continue)
    manage.py road_shapes --dry-run               # count only, no requests
    manage.py road_shapes --match --gap 0         # also map-match every feed shape (local router: no gap)

Two passes, both resumable and rate-limited (one request per `--gap` seconds, 10 locations each):
1. Check: where a feed shape's points lie more than roads.SPARSE metres apart between two stops, the
   point half-way across the gap is located on the bus road network. The distance to the road is
   kept per stop pair in `data/shape_checks.json` (version-controlled, like the stop snaps), so each
   pair is checked once, ever.
2. Route: every stop-to-stop leg roads.repair would replace (missing shape, straight line, stop off the
   shape, checked off the road, SŽ replacement bus) and that is not in the RoadLeg table yet is routed
   and stored there. Serving then finds all legs in the database and never sends a burst of requests.

3. Match (with --match): every bus pattern's feed shape is map-matched onto the roads
   (roads.match_shape, stored under roads.match_key), so serving draws it along the streets.

A re-run with nothing new makes no Valhalla request.
"""
import json
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from prestop_api import geometry, mapping, roads, stopfix
from prestop_api.trips import _corrected
from prestop_api.upstream import USER_AGENT, otp

ROUTES_Q = '{ routes(transportModes: [BUS, COACH]) { gtfsId } }'
PATTERNS_Q = '''query($ids: [String]) { routes(ids: $ids) { gtfsId shortName mode agency { gtfsId }
  patterns { code stops { gtfsId name lat lon } patternGeometry { points } } } }'''
CHUNK = 100


class Command(BaseCommand):
    help = 'Check bus shapes against the roads (Valhalla locate, cached) and route the legs that are off them (RoadLeg).'

    def add_arguments(self, parser):
        parser.add_argument('--routes', default='', help='comma-separated route ids')
        parser.add_argument('--feeds', default='', help='comma-separated feed prefixes (LPP, IJPP, MARPROM, ...)')
        parser.add_argument('--max-requests', type=int, default=0, help='stop after this many Valhalla requests')
        parser.add_argument('--gap', type=float, default=1.0, help='seconds between Valhalla requests')
        parser.add_argument('--dry-run', action='store_true', help='only count what would be requested')
        parser.add_argument('--match', action='store_true', help='also map-match every feed shape onto the roads')

    def handle(self, *args, routes='', feeds='', max_requests=0, gap=1.0, dry_run=False, match=False, **options):
        if not settings.PRESTOP_VALHALLA_URL and not dry_run:
            self.stderr.write('PRESTOP_VALHALLA_URL is empty: nothing can be routed.')
            return
        self.budget, self.gap, self.dry, self.requests = max_requests, gap, dry_run, 0
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        patterns = self._patterns([r for r in routes.split(',') if r], [f for f in feeds.split(',') if f])
        self.stdout.write(f'{len(patterns)} bus patterns')
        if match:
            self._match(patterns)
        checked = self._check(patterns)
        self._route(patterns, checked)
        self.stdout.write(f'done: {self.requests} Valhalla requests')

    # ------------------------------------------------------------ input

    def _patterns(self, route_ids: list[str], feeds: list[str]) -> list[dict]:
        ids = route_ids or [r['gtfsId'] for r in otp().query(ROUTES_Q, timeout=(5, 90))['routes']]
        if feeds:
            ids = [i for i in ids if i.split(':', 1)[0] in feeds]
        out = []
        for n in range(0, len(ids), CHUNK):
            for route in otp().query(PATTERNS_Q, {'ids': ids[n:n + CHUNK]}, timeout=(5, 120))['routes']:
                replacement = mapping.is_replacement(route)
                for p in route.get('patterns') or []:
                    stops = [s for s in _corrected(p.get('stops') or [], replacement) if s.get('lat') is not None]
                    if len(stops) >= 2:
                        coords = mapping.decode_polyline((p.get('patternGeometry') or {}).get('points') or '')
                        out.append({'route': route['gtfsId'], 'code': p['code'], 'stops': stops,
                                    'coords': [[s['lon'], s['lat']] for s in stops] if replacement else coords, 'replacement': replacement})
        return out

    def _spend(self) -> bool:
        """Whether another request may be sent (and wait the gap before it)."""
        if self.budget and self.requests >= self.budget:
            return False
        if self.requests:
            time.sleep(self.gap)
        self.requests += 1
        return True

    # ------------------------------------------------------------ pass 1: check sparse shapes

    def _check(self, patterns: list[dict]) -> dict:
        checked = roads.checks().copy()
        todo: dict[str, list[list]] = {}
        for p in patterns:
            if p['replacement'] or roads.shapeless(p['coords'], p['stops']):
                continue
            cum = geometry.cumulative(p['coords'])
            along = [a for a, _ in geometry.project_stops(p['coords'], p['stops'])]
            bad = roads.bad_segments(p['coords'], p['stops'], {})
            for i in range(len(p['stops']) - 1):
                key = roads.leg_key(p['stops'][i], p['stops'][i + 1])
                if bad[i] or key in checked or key in todo:
                    continue
                samples = roads.sparse_points(p['coords'], cum, along[i], along[i + 1])
                if samples:  # dense stretches need no check
                    todo[key] = samples
        # Requests of up to 10 points; a stop pair's points always go in the same request.
        batches: list[list[tuple[str, list]]] = [[]]
        for key, samples in todo.items():
            if len(batches[-1]) + len(samples) > roads.MAX_LOCATIONS:
                batches.append([])
            batches[-1].extend((key, pt) for pt in samples)
        batches = [b for b in batches if b]
        self.stdout.write(f'check: {len(todo)} sparse stop pairs, {len(batches)} requests')
        if self.dry:
            return checked
        url = settings.PRESTOP_VALHALLA_URL.rsplit('/', 1)[0] + '/locate'
        for n, batch in enumerate(batches):
            if not self._spend():
                self.stdout.write('request budget used up; re-run to continue')
                break
            body = {'locations': [{'lat': pt[1], 'lon': pt[0]} for _, pt in batch], 'costing': 'bus', 'verbose': False}
            try:
                response = self.session.post(url, json=body, timeout=30)
                response.raise_for_status()
                answers = response.json()
            except (requests.RequestException, ValueError) as error:
                self.stderr.write(f'locate failed: {error}; stopping (re-run to continue)')
                break
            for (key, _), answer in zip(batch, answers):
                hit = stopfix.road_point(answer)  # none: no bus road within Valhalla's search radius
                checked[key] = max(checked.get(key, 0), round(hit[2], 1) if hit else 9999)
            if n % 20 == 0:
                self._save(checked)
                self.stdout.write(f'check: {n + 1}/{len(batches)} requests')
        self._save(checked)
        off = sum(1 for v in checked.values() if v > roads.OFF_ROAD)
        self.stdout.write(f'check: {len(checked)} stop pairs known, {off} off the road (> {roads.OFF_ROAD} m)')
        return checked

    def _save(self, checked: dict):
        roads.CHECKS.write_text(json.dumps(checked, separators=(',', ':'), sort_keys=True), encoding='utf-8')

    # ------------------------------------------------------------ pass 2: route bad legs

    def _route(self, patterns: list[dict], checked: dict):
        runs, keys = [], set()
        for p in patterns:
            bad = roads.bad_segments(p['coords'], p['stops'], checked)
            i = 0
            while i < len(bad):  # each run of consecutive bad segments, as in roads.repair
                if not bad[i]:
                    i += 1
                    continue
                j = i
                while j < len(bad) and bad[j]:
                    j += 1
                runs.append(p['stops'][i:j + 1])
                keys |= {roads.leg_key(a, b) for a, b in zip(p['stops'][i:j + 1], p['stops'][i + 1:j + 1])}
                i = j
        cached = set(roads.legs.get_many(sorted(keys)))
        missing = keys - cached
        windows = []
        for stops in runs:
            for start in range(0, len(stops) - 1, roads.MAX_LOCATIONS - 1):
                window = stops[start:start + roads.MAX_LOCATIONS]
                wanted = {roads.leg_key(a, b) for a, b in zip(window, window[1:])} & missing
                if wanted:
                    windows.append(window)
                    missing -= wanted
        self.stdout.write(f'route: {len(keys)} legs to replace, {len(cached)} already stored, {len(windows)} requests')
        if self.dry:
            return
        routed = 0
        for window in windows:
            if not self._spend():
                self.stdout.write('request budget used up; re-run to continue')
                break
            try:
                legs = roads.route_window(window)
            except requests.RequestException as error:
                self.stderr.write(f'route failed: {error}; stopping (re-run to continue)')
                break
            pairs = [roads.leg_key(a, b) for a, b in zip(window, window[1:])]
            roads.legs.put_many({k: (legs[i] if legs and i < len(legs) else []) for i, k in enumerate(pairs)})
            routed += len(pairs)
        self.stdout.write(f'route: {routed} legs stored')

    # ------------------------------------------------------------ pass 3: map-match feed shapes

    def _match(self, patterns: list[dict]):
        shapes = {}
        for p in patterns:
            if not p['replacement'] and not roads.shapeless(p['coords'], p['stops']):
                shapes.setdefault(roads.match_key(p['coords']), p['coords'])
        stored = set(roads.legs.get_many(sorted(shapes)))
        todo = [(k, c) for k, c in shapes.items() if k not in stored]
        self.stdout.write(f'match: {len(shapes)} feed shapes, {len(stored)} already matched, {len(todo)} to match')
        if self.dry:
            return

        def request(points):
            if not self._spend():
                raise _Budget()
            return roads.trace(points)
        done = failed = 0
        for n, (key, coords) in enumerate(todo):
            try:
                line = roads.match_shape(coords, request)
            except _Budget:
                self.stdout.write('request budget used up; re-run to continue')
                break
            except requests.RequestException as error:
                self.stderr.write(f'match failed: {error}; stopping (re-run to continue)')
                break
            roads.legs.put_many({key: line})
            done += 1
            failed += not line
            if n % 100 == 0:
                self.stdout.write(f'match: {n + 1}/{len(todo)}')
        self.stdout.write(f'match: {done} shapes stored ({failed} without a usable match: drawn as the feed has them)')


class _Budget(Exception):
    pass

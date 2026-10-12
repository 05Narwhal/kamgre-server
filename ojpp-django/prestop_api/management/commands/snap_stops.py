"""Fill the road-snap cache for every stop and write the stop correction report.

    manage.py snap_stops            # locate uncached stops (10 per request), then write the report
    manage.py snap_stops --report   # only rewrite the report from the cache

Each stop is located once per position (the cache key includes it), so later runs only ask
Valhalla about new or moved stops. The report (`data/stop_report.csv`) lists every automatic
merge and snap with its distance, and the stops too far from a road to snap (check those by
hand and add a row to `stop_overrides.csv`).
"""
import csv
import json
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from prestop_api import mapping, roads, stopfix, stopgroups
from prestop_api.sources import STOPS_Q
from prestop_api.upstream import USER_AGENT, otp


class Command(BaseCommand):
    help = 'Snap stops onto bus roads (Valhalla locate, cached) and write the stop correction report.'

    def add_arguments(self, parser):
        parser.add_argument('--report', action='store_true', help='only rewrite the report from the cache')
        parser.add_argument('--limit', type=int, default=0, help='locate at most this many stops')

    def handle(self, *args, report=False, limit=0, **options):
        overrides = stopfix.read_overrides()
        snaps = stopfix.read_snaps()
        raw = [s for s in otp().query(STOPS_Q, timeout=(5, 120))['stops'] if s.get('routes') and s.get('lat') is not None]
        # Only bus stops: a railway station is where the tracks are, not on the nearest road.
        rail = {s['gtfsId'] for s in raw if any(mapping.mode_of(r.get('mode')) == 'rail' for r in s['routes'])}
        for key in [k for k in snaps if k.split('@', 1)[0] in rail]:
            del snaps[key]
        raw = [s for s in raw if s['gtfsId'] not in rail]
        todo = [s for s in raw if s['gtfsId'] not in overrides['stops']
                and stopfix.snap_key(s['gtfsId'], s['lat'], s['lon']) not in snaps]
        if limit:
            todo = todo[:limit]
        if not report and todo:
            self._locate(todo, snaps)
        self._save(snaps)
        self._report(raw, overrides, snaps)

    def _locate(self, todo: list[dict], snaps: dict):
        url = settings.PRESTOP_VALHALLA_URL.rsplit('/', 1)[0] + '/locate'
        session = requests.Session()
        session.headers['User-Agent'] = USER_AGENT
        for n in range(0, len(todo), roads.MAX_LOCATIONS):
            batch = todo[n:n + roads.MAX_LOCATIONS]
            body = {'locations': [{'lat': s['lat'], 'lon': s['lon']} for s in batch], 'costing': 'bus'}
            try:
                response = session.post(url, json=body, timeout=30)
                response.raise_for_status()
                answers = response.json()
            except (requests.RequestException, ValueError) as error:
                self.stderr.write(f'locate failed at {n}: {error}; stopping (re-run to continue)')
                break
            for s, answer in zip(batch, answers):
                hit = stopfix.road_point(answer)
                # No bus road within Valhalla's search radius: record it as far off, for the report.
                snaps[stopfix.snap_key(s['gtfsId'], s['lat'], s['lon'])] = list(hit) if hit else [s['lat'], s['lon'], 9999]
            if n // roads.MAX_LOCATIONS % 20 == 0:
                self._save(snaps)
                self.stdout.write(f'{n + len(batch)}/{len(todo)} located')
            time.sleep(roads.REQUEST_GAP)
        self._save(snaps)

    def _save(self, snaps: dict):
        stopfix.SNAPS.write_text(json.dumps(snaps, separators=(',', ':'), sort_keys=True), encoding='utf-8')

    def _report(self, raw: list[dict], overrides: dict, snaps: dict):
        rows = []
        for s in raw:
            hit = snaps.get(stopfix.snap_key(s['gtfsId'], s['lat'], s['lon']))
            if s['gtfsId'] in overrides['stops'] or not hit or hit[2] <= stopfix.SNAP_METERS:
                continue
            kind = 'snap' if hit[2] <= stopfix.MAX_SNAP_METERS else 'too-far'
            rows.append({'kind': kind, 'stop_id': s['gtfsId'], 'name': s.get('name') or '', 'into': '',
                         'meters': hit[2], 'lat': hit[0], 'lon': hit[1]})
        everything = otp().query(STOPS_Q, timeout=(5, 120))['stops']
        built = mapping.build_stops(stopfix.correct(everything, overrides, snaps))
        merged, _ = stopgroups.merge(built, overrides['merge'], overrides['stations'])
        rows += stopgroups.report(built, merged)
        with open(stopfix.REPORT, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, ['kind', 'stop_id', 'name', 'into', 'meters', 'lat', 'lon'])
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda r: (r['kind'], r['into'], r['stop_id'])))
        counts = {k: sum(1 for r in rows if r['kind'] == k) for k in ('merge', 'snap', 'too-far')}
        self.stdout.write(f'report: {stopfix.REPORT} {counts}')

"""Audit the map's stops over all feeds (spec 2026-10-19 A3, 2026-10-23 E6).

    manage.py stop_audit                    # counts
    manage.py stop_audit --list 30          # and the first 30 of each kind, with evidence
    manage.py stop_audit --csv              # every row, with evidence, to docs/research/2026-10-23-stop-audit.csv
    manage.py stop_audit --against prod     # prod's markers (api.kamgre.si /stops) against this server's feeds

- clusters: namesakes (stopgroups.similar) within SAME_SPOT_METERS that are separate markers, though not
  served in opposite directions (a bus station's bays, one pole twice);
- off road: stops whose feed position is more than OFF_ROAD_METERS from a bus road (the snap cache,
  data/stop_snaps.json, filled by `snap_stops`);
- same side: namesake markers within MERGE_METERS served in opposite directions where the one for a direction
  is not to the right of the other (Slovenia drives on the right): both on one side, or swapped;
- empty: markers none of whose member stops has a trip in the next SERVICE_DAYS days: no OTP pattern, or none
  with a departure or arrival in that time (OTP's board, asked in batches), no trip of a feed read here
  (supplement.py) and no live vehicle of a line serving it in the collector's last SERVICE_DAYS days (TripDelay);
- twins: separate markers with alike names (stopgroups.similar, which folds case: "KOLODVOR" is "Kolodvor")
  within MERGE_METERS whose vehicles go the same way (main way, or every way alike: two termini at one spot),
  LPP-only and IJPP copies of one pole included;
- far namesakes: the same beyond MERGE_METERS, up to FAR_METERS. Twins further apart than NEAR_METERS are far
  namesakes too; both kinds carry evidence (lines, patterns, departures in the next SERVICE_DAYS days, the
  nearest OSM pole) to tell where the pole is and which one the trips use;
- wide: merged markers with a member stop more than NEAR_METERS from the marker (the marker sits at one pole
  of a group that took in a far one), with the farthest member.
"""
import csv
import json
import math
import time
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand

from prestop_api import sources, stopfix, stopgroups, supplement, trips, views
from prestop_api.upstream import UpstreamError, otp, session

OFF_ROAD_METERS = 25
FAR_METERS = 400
SERVICE_DAYS = 7
BATCH = 200  # stops per OTP query (200 boards of one departure: ~0.4 s)
CSV = Path(__file__).resolve().parents[5] / 'docs' / 'research' / '2026-10-23-stop-audit.csv'
PROD = 'https://api.kamgre.si/api/v1'
KINDS = ('empty', 'twins', 'far', 'wide', 'clusters', 'sameSide', 'offRoad')


def members(marker: dict) -> list[str]:
    return marker.get('memberIds') or [marker['id']]


def audit(snap: dict, snaps: dict, placed: dict, served: set = None) -> dict:
    """`placed`: stops placed by hand (stop_overrides.csv), not counted as off the road. `served`: stop ids with a trip
    in the next SERVICE_DAYS days (see `served_stops`); without it no marker counts as empty."""
    built, merged, ways = snap['all'], snap['list'], snap['directions']
    by_id = {s['id']: s for s in built}

    def way(marker: dict):
        return stopgroups.group_ways([by_id[i] for i in members(marker) if i in by_id], ways)

    bus = [m for m in merged if 'rail' not in m['modes']]
    cells: dict = {}
    for m in bus:
        cells.setdefault(stopgroups._cell(m), []).append(m)
    reach = math.ceil(FAR_METERS / stopgroups.MERGE_METERS)
    clusters, same_side, twins, far = [], [], [], []
    for a in bus:
        cy, cx = stopgroups._cell(a)
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                for b in cells.get((cy + dy, cx + dx), ()):
                    if b['id'] <= a['id'] or not stopgroups.similar(a['name'], b['name']):
                        continue
                    d = stopgroups.meters(a, b)
                    if d > FAR_METERS:
                        continue
                    wa, wb = way(a), way(b)
                    one_way = bool(stopgroups.main_way(wa, wb) or stopgroups.alike(wa, wb))
                    if d > stopgroups.MERGE_METERS:
                        if one_way:
                            far.append((a, b, d))
                        continue
                    opposite = stopgroups.opposite(wa, wb)
                    if d <= stopgroups.SAME_SPOT_METERS and not opposite:
                        clusters.append((a, b, d))
                    if opposite and stopgroups.right_of(a, b, wa[0]) < stopgroups.SIDE_METERS:
                        same_side.append((a, b, d))
                    if one_way:
                        twins.append((a, b, d))
                        if d > stopgroups.NEAR_METERS:
                            far.append((a, b, d))
    off_road = []
    for s in built:
        if 'rail' in s['modes']:
            continue
        lat, lon = s.get('feedLat', s['latitude']), s.get('feedLon', s['longitude'])
        hit = snaps.get(stopfix.snap_key(s['id'], lat, lon))
        if hit and hit[2] > OFF_ROAD_METERS and s['id'] not in placed:
            off_road.append((s, hit[2]))
    wide = []
    for m in merged:
        spread = sorted((stopgroups.meters(m, by_id[i]), i) for i in m.get('memberIds') or () if i in by_id)
        if spread and spread[-1][0] > stopgroups.NEAR_METERS:
            wide.append((m, by_id[spread[-1][1]], spread[-1][0]))
    empty = [] if served is None else [m for m in merged if not any(i in served for i in members(m))]
    return {'markers': len(merged), 'clusters': clusters, 'offRoad': off_road, 'sameSide': same_side, 'empty': empty,
            'twins': sorted(twins, key=lambda p: p[2]), 'far': sorted(far, key=lambda p: p[2]), 'wide': sorted(wide, key=lambda p: -p[2])}


def departures(ids: list[str], most: int, batch: int = BATCH) -> dict[str, int]:
    """Stop id -> departures and arrivals in the next SERVICE_DAYS days, at most `most` (0 for a stop OTP lacks)."""
    out, now = {}, int(time.time())
    for i in range(0, len(ids), batch):
        part = ids[i:i + batch]
        q = '{ ' + ' '.join(
            f's{k}: stop(id: {json.dumps(sid)}) {{ stoptimesWithoutPatterns(startTime: {now}, timeRange: {SERVICE_DAYS * 86400}, '
            f'numberOfDepartures: {most}, omitNonPickups: false) {{ serviceDay }} }}' for k, sid in enumerate(part)) + ' }'
        data = otp().query(q, timeout=(5, 120))
        for k, sid in enumerate(part):
            stop = data.get(f's{k}')
            out[sid] = len(stop.get('stoptimesWithoutPatterns') or []) if stop else 0
    return out


def live_routes() -> set[str]:
    """Routes the collector saw a vehicle of in the last SERVICE_DAYS days."""
    from prestop_statistics.models import TripDelay
    since = trips.service_day() - timedelta(days=SERVICE_DAYS)
    return set(TripDelay.objects.filter(service_date__gte=since).values_list('route_id', flat=True).distinct())


def served_stops(snap: dict) -> tuple[set, dict]:
    """(stop ids with a trip in the next SERVICE_DAYS days, stop id -> why one has none)."""
    today = trips.service_day()
    by_stop = sources.patterns.get().value['by_stop']
    ids = [s['id'] for s in snap['all']]
    served = supplement.running_stops(today + timedelta(days=i) for i in range(SERVICE_DAYS))
    counts = departures([i for i in ids if i in by_stop and not supplement.owns(i)], 1)
    served |= {i for i, n in counts.items() if n}
    seen = live_routes()
    served |= {i for i in ids if (snap['routes'].get(i) or set()) & seen}
    why = {i: 'no OTP pattern' if i not in by_stop and not supplement.owns(i) else f'no trip in {SERVICE_DAYS} days'
           for i in ids if i not in served}
    return served, why


def prod_markers() -> list[dict]:
    out, cursor = [], None
    while True:
        params = {'bbox': ','.join(map(str, views.SLOVENIA)), **({'cursor': cursor} if cursor else {})}
        r = session().get(f'{PROD}/stops', params=params, timeout=(5, 120))
        r.raise_for_status()
        data = r.json()['data']
        out += data['items']
        cursor = data.get('cursor')
        if not cursor:
            return out


class Evidence:
    """Per marker: its lines, OTP patterns, departures in the next days and the nearest OSM pole."""

    def __init__(self, snap: dict, counted: dict):
        self.snap, self.counted = snap, counted
        self.by_stop = sources.patterns.get().value['by_stop']
        try:
            self.routes = sources.routes.get().value
        except UpstreamError:
            self.routes = {}
        self.poles: dict = {}
        for lat, lon in stopfix.osm_poles():
            self.poles.setdefault(stopgroups._cell({'latitude': lat, 'longitude': lon}), []).append((lat, lon))

    def osm(self, marker: dict):
        cy, cx = stopgroups._cell(marker)
        near = [stopgroups.meters(marker, {'latitude': lat, 'longitude': lon})
                for dy in (-1, 0, 1) for dx in (-1, 0, 1) for lat, lon in self.poles.get((cy + dy, cx + dx), ())]
        return round(min(near)) if near else None

    def of(self, marker: dict) -> dict:
        ids = members(marker)
        lines = sorted({(self.routes.get(r) or {}).get('shortName') or r for i in ids for r in self.snap['routes'].get(i) or ()})
        return {'id': marker['id'], 'name': marker['name'], 'lat': marker['latitude'], 'lon': marker['longitude'],
                'members': ' '.join(ids), 'lines': ' '.join(lines),
                'patterns': sum(len(self.by_stop.get(i, ())) for i in ids),
                'departures': sum(self.counted.get(i, 0) for i in ids) if any(i in self.counted for i in ids) else '',
                'osm_m': self.osm(marker)}


class Command(BaseCommand):
    help = 'Count stop clusters, stops off the road, opposite-direction stops on one side, empty stops, twins and far namesakes.'

    def add_arguments(self, parser):
        parser.add_argument('--list', type=int, default=0, help='list this many of each kind')
        parser.add_argument('--csv', nargs='?', const=str(CSV), default=None, help=f'write every row to this file ({CSV.name})')
        parser.add_argument('--against', choices=['local', 'prod'], default='local',
                            help="whose markers: this server's, or prod's /stops (feeds, patterns and service from here)")
        parser.add_argument('--most', type=int, default=500, help='departures counted per stop of a twin or far namesake')

    def handle(self, *args, list=0, csv=None, against='local', most=500, **options):
        snap = sources.stops.get().value
        if against == 'prod':
            snap = {**snap, 'list': prod_markers()}
        served, why = served_stops(snap)
        found = audit(snap, stopfix.read_snaps(), stopfix.read_overrides()['stops'], served)
        self.stdout.write(f'{found["markers"]} markers ({against}); {len(found["empty"])} empty (no trip in {SERVICE_DAYS} days); '
                          f'{len(found["twins"])} twins within {stopgroups.MERGE_METERS} m; {len(found["far"])} far namesakes '
                          f'{stopgroups.NEAR_METERS}-{FAR_METERS} m; {len(found["wide"])} merged markers wider than '
                          f'{stopgroups.NEAR_METERS} m; {len(found["clusters"])} namesake clusters within '
                          f'{stopgroups.SAME_SPOT_METERS} m; {len(found["offRoad"])} stops > {OFF_ROAD_METERS} m off a bus road; '
                          f'{len(found["sameSide"])} opposite-direction pairs not on their own side')
        if not (list or csv):
            return
        pairs = {m['id']: m for kind in ('twins', 'far', 'wide') for p in found[kind] for m in p[:2]}
        evidence = Evidence(snap, departures(sorted({i for m in pairs.values() for i in members(m)}), most, BATCH // 4))
        rows = self._rows(found, evidence, why)
        if csv:
            self._csv(rows, Path(csv))
        for kind in KINDS if list else ():
            self.stdout.write(f'-- {kind}')
            for row in [r for r in rows if r['kind'] == kind][:list]:
                self.stdout.write('   ' + self._line(row))

    def _rows(self, found: dict, evidence: Evidence, why: dict) -> list[dict]:
        rows = []
        for m in found['empty']:
            rows.append({'kind': 'empty', 'meters': '', **self._side('a', evidence.of(m)),
                         'note': '; '.join(sorted({why.get(i, '?') for i in members(m)}))})
        for kind in ('twins', 'far', 'wide', 'clusters', 'sameSide'):
            for a, b, d in found[kind]:
                feeds = {i.split(':', 1)[0] for i in members(a) + members(b)}
                note = 'member of a' if kind == 'wide' else 'one feed' if len(feeds) == 1 else 'feeds ' + ' '.join(sorted(feeds))
                rows.append({'kind': kind, 'meters': round(d), **self._side('a', evidence.of(a)), **self._side('b', evidence.of(b)), 'note': note})
        for s, d in sorted(found['offRoad'], key=lambda x: -x[1]):
            rows.append({'kind': 'offRoad', 'meters': round(d), **self._side('a', evidence.of(s)), 'note': 'metres off a bus road'})
        return rows

    @staticmethod
    def _side(prefix: str, ev: dict) -> dict:
        return {f'{prefix}_{k}': v for k, v in ev.items()}

    @staticmethod
    def _line(row: dict) -> str:
        def side(p):
            return (f'{row[p + "_name"]!r} {row[p + "_id"]} [{row[p + "_lines"][:40]}] pat={row[p + "_patterns"]} '
                    f'dep={row[p + "_departures"]} osm={row[p + "_osm_m"]}m')
        text = side('a') + (f' / {side("b")}' if row.get('b_id') else '')
        return text + (f': {row["meters"]} m' if row['meters'] != '' else '') + (f' ({row["note"]})' if row['note'] else '')

    def _csv(self, rows: list[dict], path: Path):
        fields = ['kind', 'meters'] + [f'{p}_{k}' for p in 'ab' for k in ('id', 'name', 'lat', 'lon', 'members', 'lines', 'patterns', 'departures', 'osm_m')] + ['note']
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
        self.stdout.write(f'{len(rows)} rows -> {path}')

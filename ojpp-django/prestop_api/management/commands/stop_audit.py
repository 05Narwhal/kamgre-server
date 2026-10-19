"""Audit the map's stops over all feeds (spec 2026-10-19 A3).

    manage.py stop_audit             # counts
    manage.py stop_audit --list 30   # and the first 30 of each kind

- clusters: namesakes (stopgroups.similar) within SAME_SPOT_METERS that are separate markers, though not
  served in opposite directions (a bus station's bays, one pole twice);
- off road: stops whose feed position is more than OFF_ROAD_METERS from a bus road (the snap cache,
  data/stop_snaps.json, filled by `snap_stops`);
- same side: namesake markers within MERGE_METERS served in opposite directions where the one for a direction
  is not to the right of the other (Slovenia drives on the right): both on one side, or swapped.
"""
from django.core.management.base import BaseCommand

from prestop_api import sources, stopfix, stopgroups

OFF_ROAD_METERS = 25


def audit(snap: dict, snaps: dict, placed: dict) -> dict:
    """`placed`: stops placed by hand (stop_overrides.csv), not counted as off the road."""
    built, merged, ways, groups = snap['all'], snap['list'], snap['directions'], snap['groups']
    by_id = {s['id']: s for s in built}

    def way(marker: dict):
        return stopgroups.group_way([by_id[i] for i in marker.get('memberIds') or [marker['id']] if i in by_id], ways)

    bus = [m for m in merged if 'rail' not in m['modes']]
    cells: dict = {}
    for m in bus:
        cells.setdefault(stopgroups._cell(m), []).append(m)
    clusters, same_side = [], []
    for a in bus:
        cy, cx = stopgroups._cell(a)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for b in cells.get((cy + dy, cx + dx), ()):
                    if b['id'] <= a['id'] or not stopgroups.similar(a['name'], b['name']):
                        continue
                    d = stopgroups.meters(a, b)
                    if d > stopgroups.MERGE_METERS:
                        continue
                    wa, wb = way(a), way(b)
                    opposite = bool(wa and wb and wa[0] * wb[0] + wa[1] * wb[1] <= -stopgroups.SAME_WAY)
                    if d <= stopgroups.SAME_SPOT_METERS and not opposite:
                        clusters.append((a, b, d))
                    if opposite and stopgroups.right_of(a, b, wa) < stopgroups.SIDE_METERS:
                        same_side.append((a, b, d))
    off_road = []
    for s in built:
        if 'rail' in s['modes']:
            continue
        lat, lon = s.get('feedLat', s['latitude']), s.get('feedLon', s['longitude'])
        hit = snaps.get(stopfix.snap_key(s['id'], lat, lon))
        if hit and hit[2] > OFF_ROAD_METERS and s['id'] not in placed:
            off_road.append((s, hit[2]))
    return {'markers': len(merged), 'clusters': clusters, 'offRoad': off_road, 'sameSide': same_side}


class Command(BaseCommand):
    help = 'Count stop clusters, stops off the road and opposite-direction stops on one side of the road.'

    def add_arguments(self, parser):
        parser.add_argument('--list', type=int, default=0, help='list this many of each kind')

    def handle(self, *args, list=0, **options):
        snap = sources.stops.get().value
        found = audit(snap, stopfix.read_snaps(), stopfix.read_overrides()['stops'])
        self.stdout.write(f'{found["markers"]} markers; {len(found["clusters"])} namesake clusters within '
                          f'{stopgroups.SAME_SPOT_METERS} m; {len(found["offRoad"])} stops > {OFF_ROAD_METERS} m off a bus road; '
                          f'{len(found["sameSide"])} opposite-direction pairs not on their own side')
        if not list:
            return
        for kind in ('clusters', 'sameSide'):
            self.stdout.write(f'-- {kind}')
            for a, b, d in found[kind][:list]:
                self.stdout.write(f'   {a["name"]!r} {a["id"]} / {b["name"]!r} {b["id"]}: {d:.0f} m')
        self.stdout.write('-- offRoad')
        for s, d in sorted(found['offRoad'], key=lambda x: -x[1])[:list]:
            self.stdout.write(f'   {s["name"]!r} {s["id"]}: {d:.0f} m')

"""Read a bus station's bays from OpenStreetMap into data/platform_bays.json (see platforms.py).

    manage.py platform_bays                      # every station in platforms.STATIONS
    manage.py platform_bays --station IJPP:1126954

For each platform node with a `local_ref` (the bay number riders see) the command finds where a
bus stands at it: a bay with a short driveway of its own (sawtooth bays, like bays 1-29 at
Ljubljana AP) has the bus on that driveway, facing the way it is drawn (one-way, entry to exit);
a bay along an aisle has the bus on the aisle beside it. Each bay keeps the points of its piece of
road, so a departing bus's line starts in the bay. The file is checked in: re-run when the station
changes in OSM, and correct a bay by hand there if OSM is wrong.
"""
import json
import math

import requests
from django.core.management.base import BaseCommand, CommandError

from prestop_api import geometry, platforms
from prestop_api.upstream import USER_AGENT

OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
QUERY = '''[out:json][timeout:90];
(node["public_transport"="platform"]["local_ref"](around:{r},{lat},{lon});
 way["highway"~"^(service|bus_guideway|unclassified|residential|tertiary)$"](around:{r},{lat},{lon}););
out geom tags;'''
NEAR = 15         # m: the bus stands on a road this close to the bay's platform
OWN_WAY = 45      # m: a road piece shorter than this is the bay's own driveway
BUS = 12          # m of road kept around a bay along an aisle


class Command(BaseCommand):
    help = "Read bus station bays (platform local_ref) from OSM into data/platform_bays.json."

    def add_arguments(self, parser):
        parser.add_argument('--station', default='', help='only this station stop id')

    def handle(self, *args, station='', **options):
        out = platforms.read_bays()
        for stop_id, spec in platforms.STATIONS.items():
            if station and stop_id != station:
                continue
            data = self._overpass(QUERY.format(r=spec['radius'], lat=spec['lat'], lon=spec['lon']))
            bays = bays_from(data['elements'])
            out[stop_id] = {'name': spec['name'], 'bays': bays}
            self.stdout.write(f'{spec["name"]}: {len(bays)} bays ({", ".join(sorted(bays, key=_num))})')
        platforms.BAYS.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')

    def _overpass(self, query: str) -> dict:
        for url in OVERPASS:
            try:
                resp = requests.post(url, data={'data': query}, timeout=120, headers={'User-Agent': USER_AGENT})
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as e:
                self.stderr.write(f'{url}: {e}')
        raise CommandError('No Overpass server answered.')


def _num(ref: str):
    return (int(ref), ref) if ref.isdigit() else (10_000, ref)


def bearing(a: list, b: list) -> float:
    kx = math.cos(math.radians(a[1]))
    return (math.degrees(math.atan2((b[0] - a[0]) * kx, b[1] - a[1])) + 360) % 360


def bays_from(elements: list) -> dict:
    """ref -> {'lat', 'lon', 'heading', 'path'}: where a bus stands at each bay, facing which way,
    and the piece of road it stands on ([lon, lat] in driving order)."""
    roads = []
    for e in elements:
        if e['type'] == 'way' and e.get('geometry'):
            line = [[p['lon'], p['lat']] for p in e['geometry']]
            if (e.get('tags') or {}).get('oneway') == '-1':
                line.reverse()
            roads.append(line)
    # Every (bay, road) pair within reach, closest first. A bay's platform often sits between two
    # sawtooth driveways, so each driveway goes to one bay only; an aisle serves any number.
    pairs = []
    for e in elements:
        ref = (e.get('tags') or {}).get('local_ref', '').strip() if e['type'] == 'node' else ''
        if not ref:
            continue
        for k, line in enumerate(roads):
            (along, off), = geometry.project_stops(line, [{'lat': e['lat'], 'lon': e['lon']}])
            if off <= NEAR:
                pairs.append((off, ref, k, along))
    chosen: dict[str, tuple[int, float]] = {}
    taken: set[int] = set()
    for off, ref, k, along in sorted(pairs, key=lambda p: (p[0], _num(p[1]))):
        own = geometry.cumulative(roads[k])[-1] <= OWN_WAY
        if ref in chosen or (own and k in taken):
            continue
        chosen[ref] = (k, along)
        if own:
            taken.add(k)
    out = {}
    for ref, (k, along) in chosen.items():
        line = roads[k]
        cum = geometry.cumulative(line)
        if cum[-1] <= OWN_WAY:  # the bay's own driveway: the bus stands on all of it
            path, middle = line, cum[-1] / 2
        else:  # an aisle: the bus stands beside the platform
            start, end = max(0.0, along - BUS / 2), min(cum[-1], along + BUS / 2)
            path, middle = geometry.slice_between(line, cum, start, end), along
        at = geometry.point_at(line, cum, middle)
        ahead = geometry.point_at(line, cum, min(cum[-1], middle + 2))
        behind = geometry.point_at(line, cum, max(0.0, middle - 2))
        out[ref] = {'lat': round(at[1], 7), 'lon': round(at[0], 7), 'heading': round(bearing(behind, ahead), 1),
                    'path': [[round(x, 7), round(y, 7)] for x, y in path]}
    return out

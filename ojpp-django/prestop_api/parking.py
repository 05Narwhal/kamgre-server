"""Where a drive + park + ride parks, and what the car park costs (spec 2026-10-19 A5).

OTP's own CAR_PARKING search knows only a few car parks: from Kropa it always drove 22 km to a shopping centre in
Kranj, never to Podnart's station (train) or Naklo (bus). Here the car parks come from OpenStreetMap
(data/osm_parkings.json, scripts/build-osm-points.py) and `candidates` picks at most two places to park along the
way: a railway station (the station's own parking when none is mapped: it may not be free), a bus station or main
bus stop with a public car park, or a park and ride. journeys.with_extras drives there (a cached OTP drive) and
rides on from there (one OTP search each), within the 4-query budget.

Fees (`fee`): a P+R with a known tariff (tariffs.json driving.parking); OpenStreetMap fee=no: free; fee=yes in a city
whose tariff is known (driving.zones: Ljubljana's LPT zones, by distance from the centre, an estimate): that city's
hourly price, one hour counted; anything else unknown ("parking may not be free"), never €0.
"""
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from . import geometry

DATA = Path(__file__).resolve().parent / 'data' / 'osm_parkings.json'
CELL = 0.01            # degrees of the lookup grid (~1.1 x 0.77 km)
STOP_PARKING = 300     # m: a bus stop's car park is at most this far from it
STATION_PARKING = 400  # m: a railway station's
AT = 80                # m: a car stopping this close to a mapped car park parks there
MIN_DRIVE = 1500       # m (straight): nearer than this, walk
MAX_DRIVE = 45_000     # m (straight): drive at most this far before riding on
ALONG = (0.04, 0.92)   # share of the way to the destination a place to park may lie at
SIDEWAYS = (3000, 0.25)  # m off the straight line: at most max(3 km, 25 % of the way so far)
DETOUR = 1.3           # roads are this much longer than the straight line
SPEED = {'car': 60, 'rail': 60, 'bus': 35}  # km/h, for choosing only
MAIN_STOP_ROUTES = 4   # a bus stop served by this many lines is a main one


@lru_cache(maxsize=1)
def _all() -> tuple[list[dict], dict]:
    try:
        rows = json.loads(DATA.read_text(encoding='utf-8'))['parkings']
    except (OSError, ValueError, KeyError):
        rows = []
    out = [{'lat': r[0], 'lon': r[1], 'name': r[2], 'osmFee': r[3], 'parkRide': bool(r[4]), 'capacity': r[5]} for r in rows]
    grid: dict[tuple[int, int], list[dict]] = {}
    for p in out:
        grid.setdefault((int(p['lat'] / CELL), int(p['lon'] / CELL)), []).append(p)
    return out, grid


def near(lat: float, lon: float, radius: float) -> list[dict]:
    """Car parks within `radius` m, best first: park and ride, then free, then the biggest, then the nearest."""
    _, grid = _all()
    cy, cx = int(lat / CELL), int(lon / CELL)
    found = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for p in grid.get((cy + dy, cx + dx), ()):
                d = geometry.distance([lon, lat], [p['lon'], p['lat']])
                if d <= radius:
                    found.append((not p['parkRide'], p['osmFee'] != 'no', -p['capacity'], d, p))
    return [f[-1] for f in sorted(found, key=lambda f: f[:4])]


def at(lat: float, lon: float, radius: float = AT) -> Optional[dict]:
    """The mapped car park a car stops at (the nearest within `radius` m), or None."""
    here = [lon, lat]
    return min(near(lat, lon, radius), key=lambda p: geometry.distance(here, [p['lon'], p['lat']]), default=None)


def fee(name: str, osm_fee: str, lat: float, lon: float, rules: dict) -> dict:
    """{'fee': free|paid|unknown, 'feeCents', 'basis' ('pr', 'hourly', 'osm' or None), 'tariff'} of a car park."""
    folded = (name or '').lower()
    known = next((dict(v, name=k) for k, v in (rules.get('parking') or {}).items() if k.lower() in folded), None)
    if known:
        return {'fee': 'paid' if known['cents'] else 'free', 'feeCents': known['cents'], 'basis': 'pr', 'tariff': known}
    if osm_fee == 'no':
        return {'fee': 'free', 'feeCents': 0, 'basis': 'osm', 'tariff': None}
    if osm_fee == 'yes':
        for zone in rules.get('zones') or []:
            d = geometry.distance([lon, lat], [zone['centre'][1], zone['centre'][0]])
            band = next((b for b in zone['bands'] if d <= b['withinMeters']), None)
            if band:
                return {'fee': 'paid', 'feeCents': band['centsPerHour'], 'basis': 'hourly', 'tariff': {**zone, 'band': band}}
    return {'fee': 'unknown', 'feeCents': None, 'basis': None, 'tariff': None}


def _corridor(origin: dict, destination: dict, lat: float, lon: float) -> Optional[tuple[float, float, float]]:
    """(metres along the straight way, metres off it, its length) of a point, when it lies in the corridor."""
    a, b, p = [origin['longitude'], origin['latitude']], [destination['longitude'], destination['latitude']], [lon, lat]
    length = geometry.distance(a, b)
    if not length:
        return None
    kx = 111_320 * math.cos(math.radians(a[1]))
    ux, uy = (b[0] - a[0]) * kx / length, (b[1] - a[1]) * 110_574 / length
    px, py = (p[0] - a[0]) * kx, (p[1] - a[1]) * 110_574
    along, off = px * ux + py * uy, abs(px * uy - py * ux)
    if not ALONG[0] * length <= along <= ALONG[1] * length or off > max(SIDEWAYS[0], SIDEWAYS[1] * along):
        return None
    return along, off, length


def candidates(origin: dict, destination: dict, stops: Iterable[dict], routes: dict, limit: int = 2) -> list[dict]:
    """At most `limit` places to park and ride on from, between the origin and the destination: the quickest railway
    station first, then the quickest bus place (a bus station, a main bus stop or a park and ride), by a rough
    drive + ride time. Each: {'kind': 'rail'|'bus', 'stop' (the station), 'parking' {name, lat, lon, osmFee}}."""
    best: dict[str, tuple[float, dict]] = {}
    for s in stops:
        modes = s.get('modes') or []
        kind = 'rail' if 'rail' in modes else 'bus' if 'bus' in modes else None
        if not kind:
            continue
        place = _corridor(origin, destination, s['latitude'], s['longitude'])
        if not place:
            continue
        along, off, length = place
        straight = geometry.distance([origin['longitude'], origin['latitude']], [s['longitude'], s['latitude']])
        if not MIN_DRIVE <= straight <= MAX_DRIVE:
            continue
        lines = len(set().union(*(routes.get(i, set()) for i in s.get('memberIds') or [s['id']])))
        main = kind == 'rail' or lines >= MAIN_STOP_ROUTES or ' AP' in f" {s['name']}" or 'avtobusna postaja' in s['name'].lower()
        parks = near(s['latitude'], s['longitude'], STATION_PARKING if kind == 'rail' else STOP_PARKING)
        if not parks and kind == 'bus':
            continue
        if not main and not (parks and parks[0]['parkRide']):
            continue
        park = parks[0] if parks else {'lat': s['latitude'], 'lon': s['longitude'], 'name': '', 'osmFee': '', 'parkRide': False}
        minutes = straight * DETOUR / 1000 / SPEED['car'] * 60 + max(0.0, length - along) * DETOUR / 1000 / SPEED[kind] * 60
        if kind not in best or minutes < best[kind][0]:
            best[kind] = (minutes, {'kind': kind, 'stop': s, 'parking': {**park, 'name': park['name'] or s['name']}})
    ranked = sorted(best.values(), key=lambda m: (m[1]['kind'] != 'rail', m[0]))
    return [c for _, c in ranked][:limit]


def nearest_drivable(place: dict, radius: float = 1000) -> Optional[dict]:
    """The nearest car park to a place in a car-free zone (Prešernov trg): where a drive from there starts."""
    found = near(place['latitude'], place['longitude'], radius)
    if not found:
        return None
    here = [place['longitude'], place['latitude']]
    return min(found, key=lambda p: geometry.distance(here, [p['lon'], p['lat']]))

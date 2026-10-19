"""Where a drive + park + ride parks, and what the car park costs (spec 2026-10-19 A5, C4).

OTP's own CAR_PARKING search knows only a few car parks: from Kropa it always drove 22 km to a shopping centre in
Kranj, never to Podnart's station (train) or Naklo (bus). Here the car parks come from OpenStreetMap
(data/osm_parkings.json, scripts/build-osm-points.py; public ones only): journeys.park_and_ride lets OTP drive to any
stop (its real drive and departures), and `place_at` says where the car parks there: the car park in walking distance
with the least walk and fee, a railway station's own parking when none is mapped (it may not be free), none at a bus
stop without one.

Fees (`fee`): a P+R with a known tariff (tariffs.json driving.parking); OpenStreetMap fee=no: free; fee=yes in a city
whose tariff is known (driving.zones: Ljubljana's LPT zones, by distance from the centre, an estimate): that city's
hourly price, one hour counted; anything else unknown ("parking may not be free"), never €0.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import geometry

DATA = Path(__file__).resolve().parent / 'data' / 'osm_parkings.json'
CELL = 0.01            # degrees of the lookup grid (~1.1 x 0.77 km)
STOP_PARKING = 300     # m: a bus stop's car park is at most this far from it
STATION_PARKING = 400  # m: a railway station's
AT = 80                # m: a car stopping this close to a mapped car park parks there
MIN_DRIVE = 1500       # m (straight): nearer than this, walk
MAX_DRIVE = 45_000     # m (straight): drive at most this far before riding on
MIN_TRIP = 8000        # m (straight): a shorter trip has no drive + park + ride (11 of them for 5 km across Ljubljana)
DETOUR = 1.3           # roads and paths are this much longer than the straight line
WALK_SPEED = 1.2       # m/s from the car to the stop
# A car park's fee counted as minutes more walking: a park and ride or free one none, an unknown fee some, a paid one more.
FEE_MINUTES = {'free': 0, 'unknown': 3, 'paid': 6}


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


def _walk_and_fee(stop: dict, park: dict) -> float:
    """Minutes a car park costs a rider of that stop: the walk, and its fee as minutes more (FEE_MINUTES)."""
    walk = geometry.distance([stop['longitude'], stop['latitude']], [park['lon'], park['lat']]) * DETOUR / WALK_SPEED / 60
    fee = 'free' if park['parkRide'] or park['osmFee'] == 'no' else 'paid' if park['osmFee'] == 'yes' else 'unknown'
    return walk + FEE_MINUTES[fee]


def stop_parking(stop: dict, parks: list[dict]) -> Optional[dict]:
    """Of the car parks near a stop, the one its riders park at: the least walk and fee (_walk_and_fee), the bigger
    one when even. Only public car parks are in the data (no private, customers-only or permit ones)."""
    return min(parks, key=lambda p: (round(_walk_and_fee(stop, p), 1), -p['capacity']), default=None)


def place_at(stop: dict, kind: str) -> Optional[dict]:
    """A stop as a place to park and ride on from: {'kind', 'stop', 'parking'} with its car park (stop_parking within
    STATION_PARKING of a railway station, STOP_PARKING of a bus stop), or a railway station's own parking when none
    is mapped (it may not be free); None for a bus stop without a car park."""
    parks = near(stop['latitude'], stop['longitude'], STATION_PARKING if kind == 'rail' else STOP_PARKING)
    park = stop_parking(stop, parks)
    if not park and kind != 'rail':
        return None
    park = park or {'lat': stop['latitude'], 'lon': stop['longitude'], 'name': '', 'osmFee': '', 'parkRide': False, 'capacity': 0}
    return {'kind': kind, 'stop': stop, 'parking': {**park, 'name': park['name'] or stop['name']}}


def nearest_drivable(place: dict, radius: float = 1000) -> Optional[dict]:
    """The nearest car park to a place in a car-free zone (Prešernov trg): where a drive from there starts."""
    found = near(place['latitude'], place['longitude'], radius)
    if not found:
        return None
    here = [place['longitude'], place['latitude']]
    return min(found, key=lambda p: geometry.distance(here, [p['lon'], p['lat']]))

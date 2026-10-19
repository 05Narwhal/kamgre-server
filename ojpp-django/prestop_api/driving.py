"""Driving: what a car leg uses (motorways, the car park it ends at) and what it costs (fuel, vignette, parking).

Motorways and expressways need the DARS vignette; data/motorways.json marks them (scripts/build-no-scooter.py, from
OpenStreetMap). Fuel: the government's regulated prices, read once a day (fuel_prices); parking and the vignette from the
dated tariff file (data/tariffs.json `driving`).
"""
import csv
import io
import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests

from . import geometry
from .upstream import Cached, UpstreamError, session

logger = logging.getLogger(__name__)

MOTORWAYS = Path(__file__).resolve().parent / 'data' / 'motorways.json'
MOTORWAY_SAMPLE = 50.0   # m between checked points along a drive
MOTORWAY_MIN_KM = 2.0    # driven this far on vignette roads: the vignette is needed (shorter is a crossing or a parallel road)


@lru_cache(maxsize=1)
def _motorway_cells() -> tuple[float, set]:
    data = json.loads(MOTORWAYS.read_text(encoding='utf-8'))
    return data['cell'], {(int(iy), ix) for iy, spans in data['rows'].items() for a, b in spans for ix in range(a, b + 1)}


def motorway_km(coords: list) -> float:
    """Kilometres of a line that run on motorways or expressways."""
    if len(coords) < 2:
        return 0.0
    cell, cells = _motorway_cells()
    on = 0
    cum = geometry.cumulative(coords)
    i = 1
    for k in range(int(cum[-1] // MOTORWAY_SAMPLE) + 1):
        d = k * MOTORWAY_SAMPLE
        while i < len(coords) - 1 and cum[i] < d:
            i += 1
        t = (d - cum[i - 1]) / ((cum[i] - cum[i - 1]) or 1.0)
        a, b = coords[i - 1], coords[i]
        lon, lat = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        on += (round(lat / cell), round(lon / cell)) in cells
    return on * MOTORWAY_SAMPLE / 1000


def leg_car(leg: dict, coords: list) -> dict:
    """The `car` of a driven OTP leg (contract legCarSchema); fuel and fees are filled in by pricing (showPrices)."""
    end = leg.get('to') or {}
    out = {'distanceMeters': round(leg.get('distance') or (geometry.cumulative(coords)[-1] if len(coords) > 1 else 0)),
           'fuelLitres': None, 'fuelCents': None, 'motorway': motorway_km(coords) >= MOTORWAY_MIN_KM}
    parking = (end.get('vehicleParking') or {}).get('name')
    if parking:
        out['parking'] = {'name': parking, 'feeCents': None, 'fee': 'unknown', 'parkAndRide': 'P+R' in parking.upper().replace(' ', ''),
                          'lat': end.get('lat'), 'lon': end.get('lon')}
    return out


def parking(name: str, rules: dict) -> Optional[dict]:
    """A known car park's tariff (Ljubljana's P+R sites), else None: its fee is unknown, never 0."""
    folded = name.lower()
    return next((dict(v, name=k) for k, v in (rules.get('parking') or {}).items() if k.lower() in folded), None)


def _load_fuel() -> dict:
    """The government's regulated prices (newest row of the gov.si CSV): {'petrol': €/l, 'diesel': €/l, 'valid': text}."""
    from .pricing import tariffs
    url = tariffs()['driving']['fuel']['csvUrl']
    try:
        with session().get(url, timeout=(5, 15), stream=True) as resp:
            if resp.status_code != 200:
                raise UpstreamError(f'{url} returned HTTP {resp.status_code}')
            text = resp.raw.read(256 * 1024, decode_content=True).decode('utf-8-sig')
    except requests.RequestException as e:
        raise UpstreamError(f'{url}: {e.__class__.__name__}') from e
    rows = list(csv.reader(io.StringIO(text)))
    try:
        valid, petrol, diesel = rows[1][:3]
        return {'petrol': float(petrol), 'diesel': float(diesel), 'valid': valid.strip()}
    except (IndexError, ValueError) as e:
        raise UpstreamError(f'{url}: unexpected CSV') from e


fuel_prices = Cached(_load_fuel, ttl=24 * 3600, max_stale=21 * 24 * 3600, revalidate=6 * 3600)  # read once a day


def fuel() -> dict:
    """Today's regulated prices, or the last ones in the tariff file when gov.si cannot be read."""
    from .pricing import tariffs
    try:
        return fuel_prices.get().value
    except UpstreamError as e:
        logger.info('Fuel prices unavailable: %r', e)
        return tariffs()['driving']['fuel']['fallback']


def cost(car_leg: dict, car: dict, rules: dict, vignette_due: bool) -> tuple[Optional[int], dict]:
    """(cents, the leg's `car` with fuel, vignette and parking filled in) for one driven leg; cents None when a part is
    unknown (LPG, an unknown car park)."""
    out = dict(car_leg)
    amount = fuel_amount(out['distanceMeters'], car['litresPer100km'])
    if car['fuel'] == 'electric':
        out.update(fuelLitres=None, energyKwh=amount, fuelCents=ceil_cents(amount * rules['electric']['eurPerKwh']))
    elif car['fuel'] == 'lpg':
        out.update(fuelLitres=amount, fuelCents=None)
    else:
        out.update(fuelLitres=amount, fuelCents=ceil_cents(amount * fuel()[car['fuel']]))
    parts = [out['fuelCents']]
    if vignette_due:
        out['vignetteCents'] = rules['vignette']['weekCents']
        parts.append(out['vignetteCents'])
    if out.get('parking'):
        known = parking(out['parking']['name'], rules)
        cents = known['cents'] if known else None
        out['parking'] = {**out['parking'], 'feeCents': cents, 'fee': 'unknown' if cents is None else 'paid' if cents else 'free'}
        parts.append(out['parking']['feeCents'])
    return (None if any(c is None for c in parts) else sum(parts)), out


def fuel_amount(distance_m: float, per_100km: float) -> float:
    return round(distance_m / 1000 * per_100km / 100, 2)


def ceil_cents(euros: float) -> int:
    return int(math.ceil(euros * 100))

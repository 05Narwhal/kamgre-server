"""Driving: what a car leg uses (motorways, the car park it ends at) and what it costs (fuel, vignette, parking).

Motorways and expressways need the DARS vignette; data/motorways.json marks them (scripts/build-no-scooter.py, from
OpenStreetMap). Fuel: the government's regulated prices, read every 6 h (fuel_prices), and LPG's usual station price
(lpg_prices, goriva.si, daily); parking and the vignette from the
dated tariff file (data/tariffs.json `driving`).
"""
import csv
import io
import json
import logging
import math
import re
import statistics
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from . import geometry
from . import parking as car_parks
from .upstream import Cached, UpstreamError, session

logger = logging.getLogger(__name__)

LOCAL = ZoneInfo('Europe/Ljubljana')
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


def parking_fee(park: dict, rules: dict) -> dict:
    """The fee of the car park a leg ends at (parking.fee): its P+R tariff, else what OpenStreetMap says of the car
    park mapped there (fee=no: free; fee=yes in a city with a known tariff: one hour of it), else unknown."""
    lat, lon = park.get('lat'), park.get('lon')
    mapped = car_parks.at(lat, lon) if lat is not None and lon is not None else None
    return car_parks.fee(park.get('name') or '', (mapped or {}).get('osmFee') or '', lat, lon, rules)


PERIOD = re.compile(r'od\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})?\s*do\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})')
FUEL_ROWS = 8  # periods kept from the CSV (newest first; it goes back years)


def period(valid: str) -> tuple[date, date]:
    """'od 29. 9. do 5. 10. 2026' as its first and last day; the year is written once, at the end, so a period over
    New Year starts the year before."""
    m = PERIOD.search(valid)
    if not m:
        raise ValueError(f'not a period: {valid!r}')
    d1, m1, y1, d2, m2, y2 = m.groups()
    end = date(int(y2), int(m2), int(d2))
    start = date(int(y1 or y2), int(m1), int(d1))
    return (start.replace(year=start.year - 1) if not y1 and start > end else start), end


def fuel_row(valid: str, petrol, diesel) -> dict:
    start, end = period(valid)
    return {'petrol': float(petrol), 'diesel': float(diesel), 'valid': valid.strip(), 'from': start.isoformat(), 'to': end.isoformat()}


def _load_fuel() -> list[dict]:
    """The government's regulated prices, one row per period, newest first: [{'petrol': €/l, 'diesel': €/l, 'valid':
    text, 'from', 'to'}]. gov.si lists the next period on the Monday before it starts."""
    from .pricing import tariffs
    url = tariffs()['driving']['fuel']['csvUrl']
    try:
        with session().get(url, timeout=(5, 15), stream=True) as resp:
            if resp.status_code != 200:
                raise UpstreamError(f'{url} returned HTTP {resp.status_code}')
            text = resp.raw.read(256 * 1024, decode_content=True).decode('utf-8-sig')
    except requests.RequestException as e:
        raise UpstreamError(f'{url}: {e.__class__.__name__}') from e
    rows = []
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        try:
            rows.append(fuel_row(*row[:3]))
        except (TypeError, ValueError):
            continue
    if not rows:
        raise UpstreamError(f'{url}: unexpected CSV')
    return sorted(rows, key=lambda r: r['from'], reverse=True)[:FUEL_ROWS]


fuel_prices = Cached(_load_fuel, ttl=6 * 3600, max_stale=21 * 24 * 3600, revalidate=3600)  # read every 6 h


def fuel(day: Optional[date] = None) -> dict:
    """The regulated prices on a day (default today, in Slovenia): the newest period begun by then, so a plan for
    tomorrow already uses the prices listed for it and one for today never does. Adds 'checked', the day they were
    read; when gov.si cannot be read, the last ones kept in the tariff file."""
    from .pricing import tariffs
    rules = tariffs()['driving']['fuel']
    day = (day or datetime.now(LOCAL).date()).isoformat()
    try:
        snap = fuel_prices.get()
        rows, checked = snap.value, datetime.fromtimestamp(snap.fetched_at, LOCAL).date().isoformat()
    except UpstreamError as e:
        logger.info('Fuel prices unavailable: %r', e)
        rows, checked = [fuel_row(r['valid'], r['petrol'], r['diesel']) for r in rules['fallback']], rules['fallbackChecked']
    begun = [r for r in rows if r['from'] <= day]
    row = max(begun, key=lambda r: r['from']) if begun else min(rows, key=lambda r: r['from'])
    return {**row, 'checked': checked}


AC = re.compile(r'\bAC\b')  # goriva.si names motorway service areas "PETROL ZALOKE AC - JUG"
LPG_MIN_STATIONS = 20       # fewer stations giving an LPG price: unknown
LPG_PAGES = 40              # goriva.si pages of 25 stations (23 in Oct 2026)


def _load_lpg() -> dict:
    """The median LPG price at stations off the motorways, from goriva.si (the government's per-station prices; LPG is
    not regulated): {'lpg': €/l, 'stations': how many gave one}."""
    from .pricing import tariffs
    url, prices = tariffs()['driving']['lpg']['apiUrl'], []
    for _ in range(LPG_PAGES):
        try:
            with session().get(url, timeout=(5, 15), stream=True) as resp:
                if resp.status_code != 200:
                    raise UpstreamError(f'{url} returned HTTP {resp.status_code}')
                page = json.loads(resp.raw.read(256 * 1024, decode_content=True))
        except requests.RequestException as e:
            raise UpstreamError(f'{url}: {e.__class__.__name__}') from e
        except ValueError as e:
            raise UpstreamError(f'{url}: not JSON') from e
        for station in page.get('results') or []:
            price = (station.get('prices') or {}).get('avtoplin-lpg')
            if isinstance(price, (int, float)) and 0.4 <= price <= 2.5 and not AC.search(station.get('name') or ''):
                prices.append(price)
        url = page.get('next')
        if not isinstance(url, str) or not url.startswith('https://goriva.si/'):
            break
    if len(prices) < LPG_MIN_STATIONS:
        raise UpstreamError(f'goriva.si: LPG prices at {len(prices)} stations only')
    return {'lpg': round(statistics.median(prices), 3), 'stations': len(prices)}


lpg_prices = Cached(_load_lpg, ttl=24 * 3600, max_stale=21 * 24 * 3600, revalidate=6 * 3600)  # 23 pages: once a day


def lpg() -> Optional[dict]:
    """The usual LPG price {'lpg': €/l, 'stations', 'checked'}, never waiting on goriva.si: until it is read (or when it
    cannot be), the last one kept in the tariff file; None when there is none."""
    from .pricing import tariffs
    snap = lpg_prices.get_nowait()
    if snap is None:
        return tariffs()['driving']['lpg'].get('fallback')
    return {**snap.value, 'checked': datetime.fromtimestamp(snap.fetched_at, LOCAL).date().isoformat()}


def cost(car_leg: dict, car: dict, rules: dict, vignette_due: bool, prices: Optional[dict] = None) -> tuple[Optional[int], dict]:
    """(cents, the leg's `car` with fuel, vignette and parking filled in) for one driven leg at the fuel prices of its
    day (fuel(), lpg()); cents None when a part is unknown (LPG without a price, an unknown car park)."""
    out = dict(car_leg)
    amount = fuel_amount(out['distanceMeters'], car['litresPer100km'])
    if car['fuel'] == 'electric':
        out.update(fuelLitres=None, energyKwh=amount, fuelCents=ceil_cents(amount * rules['electric']['eurPerKwh']))
    elif car['fuel'] == 'lpg' and not (prices or {}).get('lpg'):
        out.update(fuelLitres=amount, fuelCents=None)
    else:
        out.update(fuelLitres=amount, fuelCents=ceil_cents(amount * (prices or fuel())[car['fuel']]))
    parts = [out['fuelCents']]
    if vignette_due:
        out['vignetteCents'] = rules['vignette']['weekCents']
        parts.append(out['vignetteCents'])
    if out.get('parking'):
        found = parking_fee(out['parking'], rules)
        out['parking'] = {**out['parking'], 'feeCents': found['feeCents'], 'fee': found['fee']}
        parts.append(out['parking']['feeCents'])
    return (None if any(c is None for c in parts) else sum(parts)), out


def fuel_amount(distance_m: float, per_100km: float) -> float:
    return round(distance_m / 1000 * per_100km / 100, 2)


def ceil_cents(euros: float) -> int:
    return int(math.ceil(euros * 100))

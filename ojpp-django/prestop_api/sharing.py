"""Bike and scooter sharing: the rental details of a planned leg, free periods and bike swaps.

OTP (sources.RENTALS_Q) serves every public system in Slovenia that has a feed and plans rides on them
(BICYCLE_RENTAL / SCOOTER_RENTAL); mapping.PROVIDER_NAMES names its network ids. Systems without a usable feed
(Bicy in Velenje and Šoštanj; nothing running in Koper, Izola, Piran) are listed in
docs/research/2026-10-18-sharing-systems.md and are never scraped.
"""
import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import geometry, mapping

FORM_FACTORS = {'BICYCLE': 'bicycle', 'CARGO_BICYCLE': 'cargo_bicycle', 'SCOOTER': 'scooter', 'SCOOTER_STANDING': 'scooter',
                'SCOOTER_SEATED': 'scooter', 'MOPED': 'moped'}


def leg_rental(leg: dict) -> Optional[dict]:
    """The `rental` of an OTP leg ridden on a shared bike or scooter (contract legRentalSchema), else None."""
    if not leg.get('rentedBike'):
        return None
    start, end = leg.get('from') or {}, leg.get('to') or {}
    station, vehicle = start.get('vehicleRentalStation') or {}, start.get('rentalVehicle') or {}
    network = ((station or vehicle).get('rentalNetwork') or {}).get('networkId')
    if not network:
        return None
    kind = ((vehicle.get('vehicleType') or {}).get('formFactor') or '').upper()
    out = {'network': network, 'operator': mapping.provider_name(network),
           'formFactor': FORM_FACTORS.get(kind, 'scooter' if leg.get('mode') == 'SCOOTER' else 'bicycle')}
    if station.get('stationId'):
        out['fromStationId'] = mapping.qualify(station['stationId'], network)
    if (end.get('vehicleRentalStation') or {}).get('stationId'):
        out['toStationId'] = mapping.qualify(end['vehicleRentalStation']['stationId'], network)
    return out


# ---------------------------------------------------------------- free periods and swaps (A3)

TARIFFS = Path(__file__).resolve().parent / 'data' / 'tariffs.json'
SWAP_MARGIN = 4 * 60      # s: swap this long before the free time runs out
SWAP_DETOUR = 300         # m: the swap station's furthest distance from the ride
SWAP_MAX_ADDED = 3 * 60   # s: a swap may make the journey this much longer at most
SWAP_HANDLING = 60        # s: dock the bike and take another (plus the network's own wait)
RIDE_SPEED = 4.0          # m/s: to and from the swap station
MAX_SWAPS = 3             # per journey


@lru_cache(maxsize=1)
def rules() -> dict[str, dict]:
    """{network: free minutes, charges, ...} from the dated tariff file (data/tariffs.json)."""
    return json.loads(TARIFFS.read_text(encoding='utf-8'))['sharing']['networks']


def ride_cents(rule: dict, seconds: float) -> Optional[int]:
    """What one rental of this length costs a member (data/tariffs.json `sharing.about`); None when the price list
    does not say (an unknown unlock fee, charges past the free time, or longer than allowed)."""
    minutes = seconds / 60
    if 'perMinuteCents' in rule:
        if rule.get('unlockCents') is None or rule['perMinuteCents'] is None:
            return None
        return rule['unlockCents'] + rule['perMinuteCents'] * math.ceil(minutes)
    if rule.get('freeMinutes') is None or minutes > (rule.get('maxMinutes') or math.inf):
        return None
    if minutes > rule['freeMinutes'] and not (rule.get('charges') or rule.get('every')):
        return None
    cents = sum(add for after, add in rule.get('charges') or [] if minutes > after)
    if rule.get('every'):
        after, step, add = rule['every']
        cents += add * max(0, math.ceil((minutes - after) / step))
    return min(cents, rule.get('capCents') or math.inf)


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _point_at(coords: list, fraction: float) -> tuple[list, int]:
    """The point `fraction` along a line and the index of the vertex after it."""
    cum = geometry.cumulative(coords)
    want = cum[-1] * min(max(fraction, 0.0), 1.0)
    for i in range(1, len(coords)):
        if cum[i] >= want:
            span = cum[i] - cum[i - 1] or 1.0
            t = (want - cum[i - 1]) / span
            a, b = coords[i - 1], coords[i]
            return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], i
    return list(coords[-1]), len(coords) - 1


def _swap_station(network: str, point: list, rentals: list[dict], used: set) -> Optional[tuple[dict, float]]:
    """The nearest station of the network within SWAP_DETOUR of `point` with a bike to take and a free dock now."""
    best = None
    for r in rentals:
        if r['id'].split(':')[0] != network or r['id'] in used or r.get('zone') or not (r.get('canPickup') and r.get('canReturn')):
            continue
        if (r.get('availableCount') or 0) < 1 or r.get('docksAvailable') == 0:
            continue
        d = geometry.distance(point, [r['longitude'], r['latitude']])
        if d <= SWAP_DETOUR and (best is None or d < best[1]):
            best = (r, d)
    return best


def _slack_after(legs: list[dict], i: int) -> float:
    """Seconds the legs after leg i may slip before the next bus or train leaves; unlimited when none does."""
    walked = 0.0
    for leg in legs[i + 1:]:
        if leg.get('tripId'):
            return _ts(leg['effectiveDeparture']) - _ts(legs[i]['effectiveArrival']) - walked
        walked += _ts(leg['effectiveArrival']) - _ts(leg['effectiveDeparture'])
    return math.inf


def _shift(leg: dict, seconds: float) -> None:
    for key in ('scheduledDeparture', 'scheduledArrival', 'effectiveDeparture', 'effectiveArrival'):
        leg[key] = mapping.iso(_ts(leg[key]) + seconds)


def free_periods(journey: dict, rentals: list[dict]) -> dict:
    """Marks when each shared ride's free time ends (`freeUntil`) and, for a ride longer than that, returns the bike
    at a station along the way and takes another (`swapAt`; the ride splits there) when the network restarts the
    free time on a new rental, the swap is cheaper and it adds at most SWAP_MAX_ADDED."""
    legs, i, swaps = journey['legs'], 0, 0
    while i < len(legs):
        leg = legs[i]
        rental = leg.get('rental')
        rule = rules().get(rental['network']) if rental else None
        if not rule or not rule.get('freeMinutes'):
            i += 1
            continue
        start, end = _ts(leg['effectiveDeparture']), _ts(leg['effectiveArrival'])
        free = rule['freeMinutes'] * 60
        rental['freeUntil'] = mapping.iso(start + free)
        split = None
        if end - start > free and rule.get('resetOnReturn') and swaps < MAX_SWAPS and len(leg['geometry']) >= 2:
            split = _split(leg, rule, rentals, start, end, free, _slack_after(legs, i))
        if split:
            first, second, added = split
            legs[i:i + 1] = [first, second]
            for later in legs[i + 2:]:
                if later.get('tripId'):
                    break
                _shift(later, added)
            swaps += 1
        i += 1
    journey['scheduledArrival'] = max(journey['scheduledArrival'], legs[-1]['scheduledArrival'], key=_ts)
    journey['effectiveArrival'] = max(journey['effectiveArrival'], legs[-1]['effectiveArrival'], key=_ts)
    return journey


def _split(leg: dict, rule: dict, rentals: list[dict], start: float, end: float, free: float, slack: float):
    duration = end - start
    fraction = (free - SWAP_MARGIN) / duration
    point, index = _point_at(leg['geometry'], fraction)
    found = _swap_station(leg['rental']['network'], point, rentals, {leg['rental'].get('fromStationId'), leg['rental'].get('toStationId')})
    if not found:
        return None
    station, metres = found
    wait = SWAP_HANDLING + (rule.get('waitSeconds') or 0)
    added = 2 * metres / RIDE_SPEED + wait
    arrive = start + fraction * duration + metres / RIDE_SPEED
    if added > SWAP_MAX_ADDED or added > slack or arrive > start + free:
        return None
    # Only when it saves money: both halves cost less than the one long rental.
    first_part, second_part = arrive - start, duration * (1 - fraction) + metres / RIDE_SPEED
    costs = [ride_cents(rule, s) for s in (first_part, second_part, duration)]
    if None in costs or costs[0] + costs[1] >= costs[2]:
        return None
    here = [station['longitude'], station['latitude']]
    resume = arrive + wait
    place = {'name': station['name'], 'latitude': station['latitude'], 'longitude': station['longitude']}
    swap_at = {'stationId': station['id'], 'name': station['name'], 'lat': station['latitude'], 'lon': station['longitude'], 'at': mapping.iso(arrive)}
    first = {**leg, 'geometry': leg['geometry'][:index] + [point, here], 'destination': {**leg['destination'], **place},
             'scheduledArrival': mapping.iso(arrive), 'effectiveArrival': mapping.iso(arrive),
             'rental': {**leg['rental'], 'toStationId': station['id'], 'swapAt': swap_at}}
    second = {**leg, 'id': f"{leg['id']}-swap{station['id'].split(':')[-1]}", 'geometry': [here, point] + leg['geometry'][index:],
              'origin': {**leg['origin'], **place}, 'scheduledDeparture': mapping.iso(resume), 'effectiveDeparture': mapping.iso(resume),
              'scheduledArrival': mapping.iso(_ts(leg['scheduledArrival']) + added), 'effectiveArrival': mapping.iso(end + added),
              'rental': {k: v for k, v in leg['rental'].items() if k != 'freeUntil'} | {'fromStationId': station['id']}}
    return first, second, added

"""Bike and scooter sharing: the rental details of a planned leg.

OTP (sources.RENTALS_Q) serves every public system in Slovenia that has a feed and plans rides on them
(BICYCLE_RENTAL / SCOOTER_RENTAL); mapping.PROVIDER_NAMES names its network ids. Systems without a usable feed
(Bicy in Velenje and Šoštanj; nothing running in Koper, Izola, Piran) are listed in
docs/research/2026-10-18-sharing-systems.md and are never scraped.
"""
from typing import Optional

from . import mapping

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

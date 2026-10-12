"""Address and place search: Photon (OpenStreetMap, with categories) and Pelias
(OpenAddresses house numbers, localities) queried together and merged.

Every result carries a short `name`, a `detail` line (street and town) and a
`category` from a small fixed vocabulary that the app maps to icons. Transit stops
are left out: stations come from Prestop's own stop search, which knows their lines.
"""
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from django.conf import settings

from .mapping import fold
from .upstream import UpstreamError, get_json

logger = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='geocode')

# OpenStreetMap key=value (or key=*) -> category. First match wins.
OSM_CATEGORIES = [
    ('shop', 'supermarket', 'supermarket'), ('shop', 'convenience', 'supermarket'), ('shop', 'mall', 'mall'),
    ('shop', 'department_store', 'mall'), ('shop', 'bakery', 'bakery'), ('shop', 'car', 'car'), ('shop', 'car_repair', 'car'),
    ('shop', 'bicycle', 'bike'), ('shop', '*', 'shop'),
    ('amenity', 'restaurant', 'food'), ('amenity', 'fast_food', 'food'), ('amenity', 'food_court', 'food'),
    ('amenity', 'cafe', 'cafe'), ('amenity', 'ice_cream', 'cafe'), ('amenity', 'bar', 'bar'), ('amenity', 'pub', 'bar'),
    ('amenity', 'nightclub', 'bar'), ('amenity', 'fuel', 'fuel'), ('amenity', 'charging_station', 'charging'),
    ('amenity', 'parking', 'parking'), ('amenity', 'parking_entrance', 'parking'), ('amenity', 'bicycle_parking', 'bike'),
    ('amenity', 'bicycle_rental', 'bike'), ('amenity', 'car_sharing', 'car'), ('amenity', 'car_rental', 'car'),
    ('amenity', 'hospital', 'hospital'), ('amenity', 'clinic', 'doctor'), ('amenity', 'doctors', 'doctor'),
    ('amenity', 'dentist', 'doctor'), ('amenity', 'pharmacy', 'pharmacy'), ('amenity', 'school', 'school'),
    ('amenity', 'kindergarten', 'kindergarten'), ('amenity', 'university', 'university'), ('amenity', 'college', 'university'),
    ('amenity', 'library', 'library'), ('amenity', 'bank', 'bank'), ('amenity', 'atm', 'bank'),
    ('amenity', 'post_office', 'post'), ('amenity', 'parcel_locker', 'post'), ('amenity', 'place_of_worship', 'worship'),
    ('amenity', 'cinema', 'cinema'), ('amenity', 'theatre', 'theatre'), ('amenity', 'arts_centre', 'culture'),
    ('amenity', 'townhall', 'government'), ('amenity', 'courthouse', 'government'), ('amenity', 'police', 'police'),
    ('amenity', 'fire_station', 'police'), ('amenity', 'toilets', 'toilet'), ('amenity', '*', 'place'),
    ('tourism', 'hotel', 'hotel'), ('tourism', 'hostel', 'hotel'), ('tourism', 'guest_house', 'hotel'),
    ('tourism', 'apartment', 'hotel'), ('tourism', 'camp_site', 'camping'), ('tourism', 'museum', 'museum'),
    ('tourism', 'gallery', 'museum'), ('tourism', 'zoo', 'attraction'), ('tourism', 'theme_park', 'attraction'),
    ('tourism', 'viewpoint', 'mountain'), ('tourism', '*', 'attraction'),
    ('leisure', 'park', 'park'), ('leisure', 'garden', 'park'), ('leisure', 'playground', 'park'),
    ('leisure', 'swimming_pool', 'swimming'), ('leisure', 'water_park', 'swimming'), ('leisure', 'sports_centre', 'sport'),
    ('leisure', 'stadium', 'sport'), ('leisure', 'pitch', 'sport'), ('leisure', 'fitness_centre', 'sport'), ('leisure', '*', 'park'),
    ('historic', 'castle', 'castle'), ('historic', '*', 'attraction'),
    ('aeroway', '*', 'airport'), ('natural', 'peak', 'mountain'), ('natural', 'water', 'lake'), ('water', '*', 'lake'),
    ('natural', '*', 'nature'), ('landuse', 'retail', 'mall'), ('landuse', 'forest', 'nature'),
    ('office', 'government', 'government'), ('office', '*', 'office'), ('building', '*', 'address'),
    ('place', 'city', 'town'), ('place', 'town', 'town'), ('place', 'village', 'town'), ('place', 'hamlet', 'town'),
    ('place', 'suburb', 'town'), ('place', 'neighbourhood', 'town'), ('place', 'municipality', 'town'),
    ('place', 'locality', 'town'), ('place', 'house', 'address'), ('place', '*', 'town'),
    ('highway', '*', 'street'),
]
# Shown in Slovenia often enough that the name alone tells the category.
BRANDS = [
    (r'\b(hofer|lidl|spar|interspar|mercator|tu[sš]|eurospin|jager|e\.?leclerc|kaufland)\b', 'supermarket'),
    (r'\b(petrol|omv|mol|shell|lukoil)\b', 'fuel'),
    (r"\b(mcdonald'?s|burger king|kfc|subway)\b", 'food'),
    (r'\b(dm|m[uü]ller|bauhaus|merkur|obi|ikea|decathlon|big bang)\b', 'shop'),
    (r'\b(nlb|nkbm|unicredit|sparkasse|intesa|ok banka|abanka|delavska hranilnica|bankomat)\b', 'bank'),
    (r'\b(po[sš]ta|paketomat)\b', 'post'),
    (r'\b(lekarna)\b', 'pharmacy'),
    (r'\b(bolni[sš]nica|ukc|klinika)\b', 'hospital'),
    (r'\b(zdravstveni dom|ambulanta)\b', 'doctor'),
    (r'\b(o[sš]|osnovna [sš]ola|gimnazija|srednja [sš]ola)\b', 'school'),
    (r'\b(fakulteta|univerza)\b', 'university'),
    (r'\b(vrtec)\b', 'kindergarten'),
    (r'\b(hotel|hostel)\b', 'hotel'),
    (r'\b(cerkev|župnija|zupnija)\b', 'worship'),
    (r'\b(muzej|galerija)\b', 'museum'),
    (r'\b(grad)\b', 'castle'),
    (r'\b(parkiri[sš]{1,2}e|parking|p\+r)\b', 'parking'),
    (r'\b(letali[sš]{1,2}e|airport)\b', 'airport'),
]
TRANSIT = {('highway', 'bus_stop'), ('highway', 'platform'), ('railway', 'station'), ('railway', 'halt'), ('railway', 'stop'),
           ('railway', 'platform'), ('railway', 'tram_stop'), ('public_transport', '*'), ('amenity', 'bus_station')}
# Pelias layers that are areas, not points of interest.
PELIAS_AREAS = {'locality', 'localadmin', 'county', 'region', 'neighbourhood', 'borough', 'macrocounty', 'country'}


def category_for(key: Optional[str], value: Optional[str], name: str = '') -> Optional[str]:
    """Category from OSM tags, else from a well-known name (a brand, a hospital, a school)."""
    by_name = None
    folded = fold(name or '')
    for pattern, category in BRANDS:
        if re.search(pattern, folded):
            by_name = category
            break
    if key:
        for k, v, category in OSM_CATEGORIES:
            if k == key and (v == '*' or v == value):
                # Generic tags lose to a recognisable name ("Hofer" tagged only as a building).
                if category in ('address', 'place', 'shop', 'office', 'attraction') and by_name:
                    return by_name
                return category
    return by_name


def is_transit(key: Optional[str], value: Optional[str]) -> bool:
    return (key, value) in TRANSIT or (key, '*') in TRANSIT


def _join(*parts) -> str:
    return ', '.join(p for p in parts if p)


def from_photon(feature: dict) -> Optional[dict]:
    p = feature.get('properties') or {}
    try:
        lon, lat = feature['geometry']['coordinates'][:2]
    except (KeyError, TypeError, ValueError):
        return None
    key, value = p.get('osm_key'), p.get('osm_value')
    if is_transit(key, value) or p.get('countrycode', 'SI') not in ('SI', None):
        return None
    street = _join(p.get('street'), p.get('housenumber')).replace(', ', ' ')
    town = p.get('city') or p.get('town') or p.get('village') or p.get('county')
    name = p.get('name')
    if not name:
        if not street:
            return None
        name, street = street, ''
    category = category_for(key, value, name)
    detail = _join(street, town if fold(town or '') != fold(name) else None)
    kind = 'address' if category in ('address', 'street', 'town', None) else 'poi'
    return {'id': f'osm:{(p.get("osm_type") or "")[:1]}{p.get("osm_id", "")}', 'name': name, 'detail': detail or None,
            'category': category or ('address' if kind == 'address' else 'place'), 'kind': kind,
            'latitude': round(lat, 6), 'longitude': round(lon, 6)}


def from_pelias(feature: dict) -> Optional[dict]:
    p = feature.get('properties') or {}
    try:
        lon, lat = feature['geometry']['coordinates'][:2]
    except (KeyError, TypeError, ValueError):
        return None
    layer = p.get('layer')
    if layer in ('stops', 'station'):
        return None
    name = p.get('name') or p.get('label')
    if not name:
        return None
    town = p.get('locality') or p.get('localadmin') or p.get('county')
    if layer in PELIAS_AREAS:
        category, kind, detail = 'town', 'address', p.get('region') or p.get('county')
    elif layer in ('address', 'street'):
        category, kind, detail = ('address' if layer == 'address' else 'street'), 'address', town
    else:
        category, kind = category_for(None, None, name) or 'place', 'poi'
        detail = _join(_join(p.get('street'), p.get('housenumber')).replace(', ', ' '), town)
    return {'id': f'pelias:{p.get("gid") or p.get("id")}', 'name': name, 'detail': detail or None, 'category': category, 'kind': kind,
            'latitude': round(lat, 6), 'longitude': round(lon, 6)}


def _meters(a: dict, b: dict) -> float:
    kx = 111_320 * math.cos(math.radians(a['latitude']))
    return math.hypot((a['longitude'] - b['longitude']) * kx, (a['latitude'] - b['latitude']) * 110_574)


def merge(q: str, photon: list[dict], pelias: list[dict], near: Optional[tuple[float, float]], limit: int) -> list[dict]:
    """One list without duplicates (same name within 150 m), best matches first.

    Ranking: names that start with the query, then names containing it, then the rest;
    within a tier, a query with a house number prefers addresses; then nearer to `near`;
    then the upstream's own order.
    """
    needle = fold(q.strip())
    words = [w for w in re.split(r'\W+', needle) if w]
    wants_number = bool(re.search(r'\d', q))
    out: list[dict] = []
    for order, place in enumerate(photon + pelias):
        # Same name close by is the same place; a town and its municipality (or another source's centre) can lie km apart.
        if any(fold(place['name']) == fold(other['name']) and _meters(place, other) < (15000 if place['category'] == other['category'] == 'town' else 150) for other in out):
            continue
        name = fold(place['name'])
        tier = 0 if name.startswith(needle) else 1 if needle in name else 2 if words and all(w in fold(_join(place['name'], place.get('detail'))) for w in words) else 3
        distance = _meters(place, {'latitude': near[0], 'longitude': near[1]}) if near else 0
        place['_rank'] = (tier, not (wants_number and place['category'] == 'address'), round(math.log1p(distance / 500), 1), order)
        out.append(place)
    out.sort(key=lambda p: p.pop('_rank'))
    return out[:limit]


def _photon(q: str, limit: int, language: str, near):
    params = {'q': q, 'limit': limit + 6, 'bbox': '13.3,45.4,16.7,46.9', 'lang': 'en' if language == 'en' else 'default'}
    if near:
        params.update({'lat': near[0], 'lon': near[1], 'location_bias_scale': 0.3})
    data = get_json(settings.PRESTOP_PHOTON_URL, params, limit=2 * 1024 * 1024, timeout=(3, 6))
    return [p for p in map(from_photon, data.get('features') or []) if p]


def _pelias(q: str, limit: int, language: str, near):
    lat, lon = near or (46.05, 14.5)
    data = get_json(settings.PRESTOP_PELIAS_URL.rstrip('/') + '/autocomplete', {
        'text': q, 'size': limit, 'lang': language, 'boundary.country': 'SVN', 'focus.point.lat': lat, 'focus.point.lon': lon,
    }, limit=2 * 1024 * 1024, timeout=(3, 6))
    return [p for p in map(from_pelias, data.get('features') or []) if p]


def geocode(q: str, limit: int, language: str, near: Optional[tuple[float, float]] = None) -> list[dict]:
    """Both services at once; either may fail alone. Raises UpstreamError only if both do."""
    jobs = {'photon': _pool.submit(_photon, q, limit, language, near), 'pelias': _pool.submit(_pelias, q, limit, language, near)}
    results, errors = {}, []
    for name, job in jobs.items():
        try:
            results[name] = job.result(timeout=8)
        except Exception as e:  # noqa: BLE001 — one geocoder failing must not hide the other
            logger.info('%s failed: %r', name, e)
            errors.append(e)
            results[name] = []
    if len(errors) == len(jobs):
        raise UpstreamError(f'Geocoders failed: {errors[0]!r}')
    return merge(q, results['photon'], results['pelias'], near, limit)

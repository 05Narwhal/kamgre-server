"""Bike-share straight from the operators' GBFS feeds (v1, v2 and v3).

OTP already merges every network it knows (see sources.RENTALS_Q), but not when a
feed last published. Feeds listed here are read directly: their station status,
normalised to one shape, overrides OTP's numbers and carries the feed's own time,
so the app can tell fresh data from stale. A feed that fails is skipped and shown
as unavailable in the sources list; its stations keep OTP's numbers.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional

from django.conf import settings

from . import mapping
from .upstream import Cached, UpstreamError, get_json

logger = logging.getLogger(__name__)

# OTP rental network id -> GBFS discovery URL (gbfs.json). Found by asking each operator's
# public GBFS endpoint for the networks OTP reports (2026-10-10).
DEFAULT_FEEDS = {
    'jcdecaux_ljubljana': 'https://api.cyclocity.fr/contracts/ljubljana/gbfs/v3/gbfs.json',
    'jcdecaux_maribor': 'https://api.cyclocity.fr/contracts/maribor/gbfs/v3/gbfs.json',
    **{f'nextbike_{c}': f'https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_{c}/gbfs.json' for c in ('cc', 'cd', 'ce', 'cf', 'cn', 'cx')},
}
ELECTRIC = {'electric_assist', 'electric'}


def feeds() -> dict[str, str]:
    return getattr(settings, 'PRESTOP_GBFS_FEEDS', None) or DEFAULT_FEEDS


def _epoch(value: Any) -> Optional[float]:
    """GBFS times: POSIX seconds up to v2, RFC 3339 from v3."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _count(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _flag(value: Any) -> Optional[bool]:
    """v1 sends 0/1, later versions booleans."""
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None


def version_of(discovery: dict) -> str:
    """'1.x' feeds have no version field; v2 and v3 say so."""
    return str(discovery.get('version') or '1.0')


def feed_urls(discovery: dict, prefer: tuple[str, ...] = ('en', 'sl')) -> dict[str, str]:
    """{feed name: url}. v3 lists feeds directly; earlier versions per language."""
    data = discovery.get('data') or {}
    if isinstance(data.get('feeds'), list):
        listed = data['feeds']
    else:
        language = next((lang for lang in prefer if lang in data), next(iter(data), None))
        listed = (data.get(language) or {}).get('feeds') or [] if language else []
    return {f['name']: f['url'] for f in listed if isinstance(f, dict) and f.get('name') and f.get('url')}


def electric_types(vehicle_types: Optional[dict]) -> set[str]:
    """Vehicle type ids of e-bikes (v2/v3 vehicle_types.json)."""
    types = ((vehicle_types or {}).get('data') or {}).get('vehicle_types') or []
    return {str(t.get('vehicle_type_id')) for t in types if str(t.get('propulsion_type', '')).lower() in ELECTRIC}


def normalize_status(station: dict, version: str, electric: Optional[set[str]]) -> dict:
    """One station_status entry as the rental DTO's numbers. Unknown stays None, never 0
    (e-bikes too, when the feed's vehicle types could not be read)."""
    major = version.split('.')[0]
    bikes = _count(station.get('num_vehicles_available' if major == '3' else 'num_bikes_available'))
    by_type = station.get('vehicle_types_available')
    if isinstance(by_type, list) and electric is not None and major in ('2', '3'):
        ebikes = sum(_count(t.get('count')) or 0 for t in by_type if str(t.get('vehicle_type_id')) in electric)
    else:
        # v1 has no vehicle types; some operators add num_ebikes_available.
        ebikes = _count(station.get('num_ebikes_available'))
    return {
        'bikes': bikes,
        'ebikes': ebikes,
        'docks': _count(station.get('num_docks_available')),
        'renting': _flag(station.get('is_renting')),
        'returning': _flag(station.get('is_returning')),
        'installed': _flag(station.get('is_installed')),
        'lastReported': _epoch(station.get('last_reported')),
    }


def load_network(network: str, url: str) -> dict:
    discovery = get_json(url, timeout=(5, 15))
    version = version_of(discovery)
    urls = feed_urls(discovery)
    if 'station_status' not in urls:
        raise UpstreamError(f'{network}: no station_status feed')
    status = get_json(urls['station_status'], timeout=(5, 15))
    electric: Optional[set[str]] = None
    if 'vehicle_types' in urls:
        try:
            electric = electric_types(get_json(urls['vehicle_types'], timeout=(5, 15)))
        except UpstreamError as e:
            logger.info('GBFS %s vehicle types unavailable: %r', network, e)
    name = None
    if 'system_information' in urls:
        try:
            info = (get_json(urls['system_information'], timeout=(5, 15)).get('data') or {})
            name = info.get('name')
            name = name if isinstance(name, str) else next((n.get('text') for n in name or [] if isinstance(n, dict)), None)
        except UpstreamError:
            pass
    stations = {str(s['station_id']): normalize_status(s, version, electric) for s in (status.get('data') or {}).get('stations') or [] if s.get('station_id') is not None}
    return {'version': version, 'name': name, 'updated': _epoch(status.get('last_updated')) or time.time(), 'stations': stations}


def _load_all() -> dict[str, dict]:
    """{network: {'ok': True, ...network} | {'ok': False, 'error': str}} for every configured feed."""
    def one(item):
        network, url = item
        try:
            return network, {'ok': True, **load_network(network, url)}
        except (UpstreamError, ValueError, KeyError, TypeError) as e:
            logger.warning('GBFS %s failed: %r', network, e)
            return network, {'ok': False, 'error': str(e)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(one, feeds().items()))


networks = Cached(_load_all, ttl=60, max_stale=900, revalidate=120)


def merge(rental: dict, network: str, station_id: str, gbfs: dict[str, dict], now: float) -> dict:
    """Overrides OTP's numbers for one station with its operator's own feed when that loaded."""
    feed = gbfs.get(network) or {}
    status = (feed.get('stations') or {}).get(station_id) if feed.get('ok') else None
    if not status:
        return rental
    out = dict(rental)
    if status['bikes'] is not None:
        out['availableCount'] = status['bikes']
    if status['ebikes'] is not None:
        out['ebikesAvailable'] = status['ebikes']
    if status['docks'] is not None:
        out['docksAvailable'] = status['docks']
    renting = status['renting'] is not False and status['installed'] is not False
    out['canPickup'] = renting and (out.get('availableCount') or 0) > 0
    out['canReturn'] = status['returning'] is not False and status['installed'] is not False and out.get('docksAvailable') != 0
    out['updatedAt'] = _iso(min(feed['updated'], now))
    out['lastReported'] = _iso(status['lastReported']) if status['lastReported'] else None
    out['gbfsVersion'] = feed['version']
    return out


def _iso(epoch: float) -> str:
    return mapping.iso(epoch)

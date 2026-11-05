"""City transport networks (M3): which lines are city lines, of which town and company, with which number.

`data/city_networks.csv` names every city feed (all its lines are city lines) and the few national-feed lines that an
operator lists as city transport (Škofja Loka's 1, Idrija's L1 and L2), since no feed can say it. Payloads keep their
`routeId`, `routeName` and `operatorId` (keys, filters and statistics stay by company); `city()` only adds what a rider
reads: the plain number and "Mestni promet <town> · <company>".
"""
from __future__ import annotations

import csv
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TABLE = Path(__file__).resolve().parent / 'data' / 'city_networks.csv'
_lock = threading.Lock()
_cache: dict = {'stamp': None, 'value': ({}, {})}


def read(path: Path = TABLE) -> tuple[dict[str, dict], dict[str, dict]]:
    """(feed -> network, route gtfsId -> network with its number). Bad rows are logged and skipped."""
    feeds: dict[str, dict] = {}
    routes: dict[str, dict] = {}
    if not path.exists():
        return feeds, routes
    with open(path, newline='', encoding='utf-8') as handle:
        for n, row in enumerate(csv.DictReader(line for line in handle if not line.startswith('#')), start=2):
            town, feed = (row.get('town') or '').strip(), (row.get('feed') or '').strip()
            route, number = (row.get('route_id') or '').strip(), (row.get('number') or '').strip()
            if not town or not feed or (route and (':' not in route or not number)):
                logger.warning('city_networks.csv line %s skipped: %s', n, row)
                continue
            network = {'town': town, 'company': (row.get('company') or '').strip()}
            if route:
                routes[route] = {**network, 'number': number}
            else:
                feeds[feed] = network
    return feeds, routes


def _table() -> tuple[dict[str, dict], dict[str, dict]]:
    try:
        stamp = os.stat(TABLE).st_mtime
    except OSError:
        stamp = None
    with _lock:
        if _cache['stamp'] != stamp or stamp is None:
            _cache.update(stamp=stamp, value=read())
        return _cache['value']


def label(network: dict) -> str:
    """'Mestni promet Škofja Loka · Arriva'; without a company, 'Mestni promet Sevnica'."""
    name = f"Mestni promet {network['town']}"
    return f"{name} · {network['company']}" if network.get('company') else name


def city(route_id: Optional[str], route_name: Optional[str] = None) -> Optional[dict]:
    """The optional `city` field for a line: {'number', 'town', 'company', 'label'}, or None for other lines.

    `route_id` is the route's gtfsId ('IJPP:65376', 'MOKoper:9'); a city feed's own lines keep their feed's number
    (`route_name`, already the plain short name)."""
    if not route_id or ':' not in route_id:
        return None
    feeds, routes = _table()
    found = routes.get(route_id)
    if found is None:
        network = feeds.get(route_id.split(':', 1)[0])
        if network is None or not route_name:
            return None
        found = {**network, 'number': route_name}
    return {**found, 'label': label(found)}


def operator_name(agency_id: Optional[str]) -> Optional[str]:
    """One style for a city feed's operator ('MP_Kranj', 'Mestni potniški promet Koper', 'Mestni avtobus Brežice'
    → 'Mestni promet Kranj · Arriva'); None for any other operator."""
    if not agency_id or ':' not in agency_id:
        return None
    network = _table()[0].get(agency_id.split(':', 1)[0])
    return label(network) if network else None

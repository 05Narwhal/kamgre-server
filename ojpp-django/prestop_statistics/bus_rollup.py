"""Nightly rollups of every line but SŽ's trains (Reliability's Buses, Nov 2026): one RouteDay per line and day, and a
StationDay (`mode` 'bus') per stop and day, from the delays the collector keeps in TripDelay. Run by
`manage.py rollup_stats` after the trains (rollup.py), so the statistics read small rows, never TripDelay per request.

A bus trip is on time when it is less than ON_TIME_LATE late on average over its recorded stops, as the line pages
count a trip (aggregation.ON_TIME_LATE); at a stop, a bus less than ON_TIME_LATE late there. A stop's position on the
trip is mapped to the stop with TripStops, which the collector keeps as it meets each trip (no planner queries at
night); a trip it never met counts for its line but not for its stops.
"""
import logging
from datetime import date, timedelta
from statistics import fmean
from typing import Optional

from django.db import transaction

from prestop_api import abroad
from prestop_statistics.aggregation import ON_TIME_LATE
from prestop_statistics.collector import LJUBLJANA
from prestop_statistics.models import RouteDay, StationDay, TripDelay, TripStops
from prestop_statistics.rollup import SZ_OPERATOR

logger = logging.getLogger(__name__)
LATE = 300   # s: this late or more is "late" (5′+), as the trains (trains.LATE)
CHUNK = 2000  # trips whose stops are read at once


def route_info() -> dict[str, dict]:
    """Route id -> {'mode', 'name', 'origin', 'destination'} from the planner's routes (one cached query)."""
    from prestop_api import mapping, sources
    try:
        routes = sources.routes.get().value
    except Exception as e:  # noqa: BLE001 - names are a nicety; the figures stand without them
        logger.warning('Routes unavailable for the bus rollup: %r', e)
        return {}
    out = {}
    for route_id, r in routes.items():
        origin, destination = mapping.route_ends(r)
        out[route_id] = {'mode': mapping.mode_of(r.get('mode')) or '', 'name': mapping.route_name(r) or '',
                         'origin': origin or '', 'destination': destination or ''}
    return out


def _stops_of(trip_ids: list[str]) -> dict[str, TripStops]:
    out: dict[str, TripStops] = {}
    for i in range(0, len(trip_ids), CHUNK):
        out.update({t.trip_id: t for t in TripStops.objects.filter(trip_id__in=trip_ids[i:i + CHUNK])})
    return out


def _delays(raw: dict) -> dict[int, int]:
    return {int(k): v for k, v in (raw or {}).items() if str(k).lstrip('-').isdigit() and isinstance(v, int)}


def build(day: date, routes: Optional[dict[str, dict]] = None) -> tuple[list[dict], list[dict], dict]:
    """(RouteDay rows, bus StationDay rows, counts) of one service day."""
    routes = route_info() if routes is None else routes
    rows = list(TripDelay.objects.filter(service_date=day).exclude(operator_id=SZ_OPERATOR)
                .only('trip_id', 'route_id', 'operator_id', 'stop_delays', 'canceled', 'first_seen'))
    stops_of = _stops_of(sorted({r.trip_id for r in rows}))
    lines: dict[str, dict] = {}
    stations: dict[str, dict] = {}
    skipped = mapped = 0
    for r in rows:
        known = stops_of.get(r.trip_id)
        info = routes.get(r.route_id) or {}
        mode = info.get('mode') or (known.mode if known else '') or 'bus'
        if mode == 'rail':
            skipped += 1  # a railway of another operator: none today, and not a bus
            continue
        line = lines.setdefault(r.route_id, {
            'service_date': day, 'route_id': r.route_id, 'operator_id': r.operator_id, 'mode': mode,
            'name': (info.get('name') or '')[:60], 'origin': info.get('origin', '')[:200], 'destination': info.get('destination', '')[:200],
            'trips': 0, 'on_time': 0, 'late': 0, 'delay_sum': 0, 'max_delay': None, 'canceled': 0, 'hours': {}})
        if r.canceled:
            line['canceled'] += 1
            continue
        delays = _delays(r.stop_delays)
        if not delays:
            continue
        late = fmean(max(0, d) for d in delays.values())
        line['trips'] += 1
        line['on_time'] += late < ON_TIME_LATE
        line['late'] += late >= LATE
        line['delay_sum'] += round(late)
        line['max_delay'] = max(line['max_delay'] or 0, max(delays.values()))
        stops = {p: (sid, name, at) for p, sid, name, at in (known.stops if known else [])}
        first = min(stops.items())[1][2] if stops else None
        hour = str(first // 3600 % 24) if first is not None else str(r.first_seen.astimezone(LJUBLJANA).hour)
        cell = line['hours'].setdefault(hour, [0, 0, 0])
        cell[0], cell[1], cell[2] = cell[0] + 1, cell[1] + (late < ON_TIME_LATE), cell[2] + round(late)
        if not stops:
            continue
        mapped += 1
        for position, delay in delays.items():
            if position not in stops:
                continue
            stop_id, name, at = stops[position]
            if abroad.is_abroad_stop(name, stop_id):
                continue
            row = stations.setdefault(stop_id, {'name': name, 'delays': [], 'hours': {}})
            row['delays'].append(delay)
            if at is not None:
                h = row['hours'].setdefault(str(at // 3600 % 24), [0, 0, 0])
                h[0], h[1], h[2] = h[0] + 1, h[1] + (delay < ON_TIME_LATE), h[2] + delay
    station_rows = [{'service_date': day, 'stop_id': stop, 'mode': 'bus', 'name': v['name'][:200], 'trains': len(v['delays']),
                     'on_time_share': round(sum(1 for d in v['delays'] if d < ON_TIME_LATE) / len(v['delays']), 4),
                     'avg_delay': round(sum(v['delays']) / len(v['delays'])), 'hours': v['hours']}
                    for stop, v in sorted(stations.items())]
    route_rows = [line for _, line in sorted(lines.items())]
    counts = {'busTrips': len(rows) - skipped, 'busTripsWithStops': mapped, 'lines': len(route_rows), 'busStops': len(station_rows)}
    return route_rows, station_rows, counts


def write(day: date, lines: list[dict], stations: list[dict]) -> None:
    """Replace the day's rows (a re-run of a night gives the same table); the railway's StationDay rows stay."""
    with transaction.atomic():
        RouteDay.objects.filter(service_date=day).delete()
        StationDay.objects.filter(service_date=day, mode='bus').delete()
        RouteDay.objects.bulk_create([RouteDay(**r) for r in lines], batch_size=1000)
        StationDay.objects.bulk_create([StationDay(**s) for s in stations], batch_size=2000)


def days_to_backfill(before: date, days: int) -> list[date]:
    """Days in the `days` before `before` with bus delays but no line rows yet, newest first."""
    start = before - timedelta(days=days)
    have = set(RouteDay.objects.filter(service_date__gte=start, service_date__lt=before).values_list('service_date', flat=True).distinct())
    with_data = set(TripDelay.objects.filter(service_date__gte=start, service_date__lt=before).exclude(operator_id=SZ_OPERATOR)
                    .values_list('service_date', flat=True).distinct())
    return sorted(with_data - have, reverse=True)

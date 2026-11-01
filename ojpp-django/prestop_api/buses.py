"""Buses in Reliability (Nov 2026), as trains.py does for SŽ's trains:

- `now()`: buses on the map now (the live vehicles), how many of them are on time, their mean delay and the latest.
- `trends(days, today)`: every line but SŽ's trains over the last 7, 30 or 90 days from the nightly RouteDay rows
  (bus_rollup.py): per day, per hour of the first departure, per company, the latest lines, and the period before.
- `departure(trip_id, days, today)`: one bus departure (its line, direction and first scheduled time) day by day.
- `station_list(mode, q, days, today)`: the stops of the last days, a stop's two sides of the road as one.

On time: a bus less than ON_TIME_LATE late (on a trip: on average over its recorded stops, as the line pages count).
"""
import threading
import time
from datetime import date, timedelta
from statistics import fmean
from typing import Optional

from . import abroad, mapping, sources

ON_TIME_LATE = 180    # s (prestop_statistics.aggregation.ON_TIME_LATE)
LATE = 300            # s: 5′+ (trains.LATE)
BIGGEST = 8           # buses listed as the latest now
TREND_DAYS = (7, 30, 90)
WORST = 10            # lines listed as usually latest
WORST_TRIPS = 10      # trips a line needs in the period to be listed
OPERATORS = 12        # companies listed
STATION_DAYS = 7      # days behind the stop list
STATIONS = 80         # stops listed (the busiest, or those matching a search)
TTL = 3600            # s the trends are kept (renewed when a new night's rows land)
STATION_TTL = 600     # s the stop list is kept
MAX_START_LOOKUPS = 240  # trips a departure page may ask the planner the start of (the rest are known from TripStops)
_cache: dict[tuple, tuple[float, object, object]] = {}
_lock = threading.Lock()


def _kept(key: tuple, ttl: float, stamp: object, load, margin: float = 0):
    """`load()` kept `ttl` s, or until `stamp` (the latest rollup day) changes; `margin`: renewed that long early."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl - margin and hit[1] == stamp:
        return hit[2]
    value = load()
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (time.time(), stamp, value)
    return value


def _share(on_time: int, n: int) -> Optional[float]:
    return round(on_time / n, 4) if n else None


def now() -> dict:
    """The buses on the map (not SŽ's replacement buses, which are the trains'), as overview() counts the trains."""
    snap = sources.vehicles.peek()
    buses = [v for v in (snap.value if snap else []) if v.get('mode') == 'bus' and not v.get('replacement')]
    known = [v for v in buses if v.get('delaySeconds') is not None]
    on_time = sum(1 for v in known if v['delaySeconds'] < ON_TIME_LATE)
    late = sum(1 for v in known if v['delaySeconds'] >= LATE)
    biggest = sorted((v for v in known if v['delaySeconds'] >= ON_TIME_LATE), key=lambda v: -v['delaySeconds'])[:BIGGEST]
    return {'running': len(buses), 'measured': len(known), 'onTimeShare': _share(on_time, len(known)),
            'avgDelaySeconds': round(fmean(max(0, v['delaySeconds']) for v in known)) if known else None,
            'buckets': {'onTime': on_time, 'slightlyLate': len(known) - on_time - late, 'late': late},
            'biggestDelays': [{'vehicleId': v['id'], 'tripId': v.get('tripId'), 'routeId': v.get('routeId'), 'name': v.get('routeName') or v.get('name') or '',
                               'operatorId': v.get('operatorId'), 'destination': v.get('destination'), 'nextStop': v.get('nextStop'),
                               'delaySeconds': v['delaySeconds']} for v in biggest]}


def _figures(r: dict) -> dict:
    trips, on_time, late = r['trips'] or 0, r['on_time'] or 0, r['late'] or 0
    return {'trips': trips, 'onTimeShare': _share(on_time, trips), 'avgDelaySeconds': round((r['delay'] or 0) / trips) if trips else None,
            'buckets': {'onTime': on_time, 'slightlyLate': trips - on_time - late, 'late': late}, 'canceled': r['canceled'] or 0}


def latest_rollup() -> Optional[date]:
    from prestop_statistics.models import RouteDay
    return RouteDay.objects.order_by('-service_date').values_list('service_date', flat=True).first()


def trends(days: int, today: date) -> dict:
    """Every line but SŽ's trains over the `days` days before today (RouteDay rows up to yesterday)."""
    from django.db.models import Max, Sum
    from prestop_statistics.models import RouteDay
    start = today - timedelta(days=days)
    period = RouteDay.objects.filter(service_date__gte=start, service_date__lt=today)
    sums = dict(trips=Sum('trips'), on_time=Sum('on_time'), late=Sum('late'), delay=Sum('delay_sum'), canceled=Sum('canceled'))
    dates = [{'date': r['service_date'].isoformat(), **_figures(r)} for r in period.values('service_date').annotate(**sums).order_by('service_date')]
    cells = [[0, 0, 0] for _ in range(24)]
    for hours in period.values_list('hours', flat=True).iterator(chunk_size=2000):
        for hour, (n, on_time, delay) in (hours or {}).items():
            if str(hour).isdigit() and 0 <= int(hour) < 24:
                c = cells[int(hour)]
                c[0], c[1], c[2] = c[0] + n, c[1] + on_time, c[2] + delay
    operators = [{'operatorId': r['operator_id'], **{k: v for k, v in _figures(r).items() if k in ('trips', 'onTimeShare', 'avgDelaySeconds')}}
                 for r in period.values('operator_id').annotate(**sums).order_by('-trips', 'operator_id')[:OPERATORS] if r['trips']]
    lines = [r for r in period.values('route_id').annotate(**sums, worst=Max('max_delay')) if (r['trips'] or 0) >= WORST_TRIPS]
    lines = sorted(lines, key=lambda r: (-(r['delay'] or 0) / r['trips'], r['route_id']))[:WORST]
    named = {r['route_id']: r for r in period.filter(route_id__in=[r['route_id'] for r in lines]).order_by('route_id', '-service_date')
             .distinct('route_id').values('route_id', 'name', 'origin', 'destination', 'operator_id', 'mode')}
    worst = [{'routeId': r['route_id'], 'name': named.get(r['route_id'], {}).get('name') or '', 'origin': named.get(r['route_id'], {}).get('origin') or None,
              'destination': named.get(r['route_id'], {}).get('destination') or None, 'operatorId': named.get(r['route_id'], {}).get('operator_id') or None,
              'trips': r['trips'], 'onTimeShare': _share(r['on_time'] or 0, r['trips']), 'avgDelaySeconds': round((r['delay'] or 0) / r['trips']),
              'maxDelaySeconds': r['worst']} for r in lines]
    first = RouteDay.objects.order_by('service_date').values_list('service_date', flat=True).first()
    return {'days': days, 'from': start.isoformat(), 'to': (today - timedelta(days=1)).isoformat(), 'since': first.isoformat() if first else None,
            'headline': _figures(period.aggregate(**sums)),
            'previous': _figures(RouteDay.objects.filter(service_date__gte=start - timedelta(days=days), service_date__lt=start).aggregate(**sums)),
            'dates': dates,
            'hours': [{'trips': n, 'onTimeShare': _share(on_time, n), 'avgDelaySeconds': round(delay / n) if n else None} for n, on_time, delay in cells],
            'operators': operators, 'worstLines': worst}


def trends_cached(days: int, today: date, margin: float = 0) -> dict:
    return _kept(('trends', days, today), TTL, latest_rollup(), lambda: trends(days, today), margin)


def warm_trends(today: date) -> None:
    """Called by warm.py every tick, as trains.warm_trends: each period rebuilt right after the night's rollup lands
    and before it would expire, so no request waits on it."""
    for days in TREND_DAYS:
        trends_cached(days, today, margin=120)


def _starts(trip_ids: set[str]) -> dict[str, int]:
    """Trip id -> scheduled first departure (s after midnight): from TripStops, else the planner (a bounded number)."""
    from prestop_statistics.aggregation import trip_start_seconds
    from prestop_statistics.models import TripStops
    out = {}
    for t in TripStops.objects.filter(trip_id__in=list(trip_ids)).only('trip_id', 'stops'):
        if t.stops and t.stops[0][3] is not None:
            out[t.trip_id] = t.stops[0][3]
    missing = sorted(trip_ids - out.keys())[:MAX_START_LOOKUPS]
    if missing:
        out.update(trip_start_seconds(missing))
    return out


def departure(trip_id: str, days: int, today: date) -> Optional[dict]:
    """The departure `trip_id` runs (its line, direction and first scheduled time) on each of the `days` days before
    today: its mean and worst delay, its delay at its last recorded stop, on time or not; None when nothing is known
    about the trip."""
    from prestop_statistics.models import TripDelay, TripStops
    own = TripDelay.objects.filter(trip_id=trip_id).order_by('-service_date').only('route_id', 'direction').first()
    stops = TripStops.objects.filter(trip_id=trip_id).only('route_id').first()
    route_id = own.route_id if own else stops.route_id if stops else None
    if not route_id:
        return None
    start = _starts({trip_id}).get(trip_id)
    rows = list(TripDelay.objects.filter(route_id=route_id, service_date__gte=today - timedelta(days=days), service_date__lt=today)
                .only('service_date', 'trip_id', 'direction', 'stop_delays', 'canceled'))
    if own:
        rows = [r for r in rows if r.direction == own.direction]
    if start is not None:
        starts = _starts({r.trip_id for r in rows})
        rows = [r for r in rows if starts.get(r.trip_id) == start]
    else:
        rows = [r for r in rows if r.trip_id == trip_id]
    per_day: dict[date, dict] = {}
    for r in rows:
        delays = [v for k, v in sorted(((int(k), v) for k, v in (r.stop_delays or {}).items() if str(k).lstrip('-').isdigit()), key=lambda kv: kv[0])
                  if isinstance(v, int)]
        if r.canceled:
            per_day[r.service_date] = {'date': r.service_date.isoformat(), 'avgDelaySeconds': None, 'maxDelaySeconds': None,
                                       'finalDelaySeconds': None, 'onTime': None, 'canceled': True}
        elif delays and (r.service_date not in per_day or per_day[r.service_date].get('canceled')):
            late = fmean(max(0, d) for d in delays)
            per_day[r.service_date] = {'date': r.service_date.isoformat(), 'avgDelaySeconds': round(late), 'maxDelaySeconds': max(delays),
                                       'finalDelaySeconds': delays[-1], 'onTime': late < ON_TIME_LATE}
    out = [per_day[d] for d in sorted(per_day, reverse=True)]
    ran = [d for d in out if d['avgDelaySeconds'] is not None]
    means = sorted(d['avgDelaySeconds'] for d in ran)
    first = TripDelay.objects.filter(route_id=route_id).order_by('service_date').values_list('service_date', flat=True).first()
    return {'tripId': trip_id, 'routeId': route_id, 'start': f'{start // 3600 % 24:02d}:{start % 3600 // 60:02d}' if start is not None else None,
            'days': out, 'summary': {'runs': len(ran), 'onTimeShare': _share(sum(1 for d in ran if d['onTime']), len(ran)),
                                     'avgDelaySeconds': round(fmean(means)) if means else None},
            'medianDelaySeconds': means[len(means) // 2] if means else None,
            'worstDelaySeconds': max((d['maxDelaySeconds'] for d in ran), default=None),
            'canceled': sum(1 for d in out if d.get('canceled')), 'since': first.isoformat() if first else None}


def _all_stations(mode: str, days: int, today: date) -> list[dict]:
    """Every stop of `mode` with rows in the `days` before today, a stop's sides of the road (sources.stop_group) as one,
    the busiest first: {stopId (its busiest side), name, trains, onTimeShare, avgDelaySeconds}."""
    from django.db.models import F, FloatField, Sum
    from django.db.models.functions import Cast
    from prestop_statistics.models import StationDay
    rows = (StationDay.objects.filter(mode=mode, service_date__gte=today - timedelta(days=days), service_date__lt=today)
            .values('stop_id').annotate(n=Sum('trains'), on=Sum(Cast(F('on_time_share'), FloatField()) * F('trains')),
                                        delay=Sum(Cast(F('avg_delay'), FloatField()) * F('trains'))))
    names = dict(StationDay.objects.filter(mode=mode, service_date__gte=today - timedelta(days=days), service_date__lt=today)
                 .order_by('stop_id', '-service_date').distinct('stop_id').values_list('stop_id', 'name'))
    groups: dict[str, dict] = {}
    for r in rows:
        name = names.get(r['stop_id']) or ''
        if not r['n'] or abroad.is_abroad_stop(name, r['stop_id']):
            continue
        key = min(sources.stop_group(r['stop_id']))
        g = groups.setdefault(key, {'stopId': r['stop_id'], 'name': name, 'trains': 0, 'on': 0.0, 'delay': 0.0, 'top': 0})
        g['trains'] += r['n']
        g['on'] += r['on'] or 0
        g['delay'] += r['delay'] or 0
        if r['n'] > g['top']:
            g['stopId'], g['name'], g['top'] = r['stop_id'], name, r['n']
    return sorted(({'stopId': g['stopId'], 'name': g['name'], 'trains': g['trains'], 'onTimeShare': round(g['on'] / g['trains'], 4),
                    'avgDelaySeconds': round(g['delay'] / g['trains'])} for g in groups.values()), key=lambda s: (-s['trains'], s['name']))


def station_list(mode: str, q: str, today: date, days: int = STATION_DAYS) -> dict:
    """The STATIONS busiest stops of `mode` over the last `days` days, or those whose name holds `q`."""
    every = _kept(('stations', mode, days, today), STATION_TTL, None, lambda: _all_stations(mode, days, today))
    wanted = mapping.fold(q.strip()) if q else ''
    found = [s for s in every if wanted in mapping.fold(s['name'])] if wanted else every
    return {'mode': mode, 'stationDays': days, 'total': len(every), 'stations': found[:STATIONS]}

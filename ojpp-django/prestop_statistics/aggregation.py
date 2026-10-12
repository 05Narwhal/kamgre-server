"""Daily route reliability from collected trip delays.

Every trip weighs the same: a trip's delay is the mean over its recorded stops, and a
day's figures are means over trips. p95 is the nearest-rank 95th percentile of the
per-trip late means. Days without measurements are `no_data` with null metrics, never
zero; days with no scheduled trip are `no_service`.
"""
import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import fmean
from typing import Optional

from prestop_statistics.models import TripDelay


def nearest_rank(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct * len(ordered)) - 1)]


def summarize(trips: list[list[int]]) -> dict:
    """Metrics for one route/direction/day from each trip's per-stop delays."""
    trips = [t for t in trips if t]
    if not trips:
        return {'meanSignedDelaySeconds': None, 'meanLateSeconds': None, 'p95LateSeconds': None, 'tripCount': 0, 'eventCount': 0}
    signed = [fmean(t) for t in trips]
    late = [fmean(max(0, d) for d in t) for t in trips]
    return {
        'meanSignedDelaySeconds': round(fmean(signed), 1), 'meanLateSeconds': round(fmean(late), 1),
        'p95LateSeconds': round(nearest_rank(late, 0.95), 1), 'tripCount': len(trips), 'eventCount': sum(len(t) for t in trips),
    }


def daily_statistics(route_id: str, start: date, end: date, direction: str, quality: str,
                     scheduled: Optional[dict[tuple[date, str], int]]) -> list[dict]:
    """`scheduled` maps (day, direction) to scheduled trip counts, or None if unknown."""
    facts = defaultdict(list)
    if quality == 'observed':
        rows = TripDelay.objects.filter(route_id=route_id, service_date__range=(start, end), canceled=False)
        if direction != 'all':
            rows = rows.filter(direction=direction)
        for row in rows.only('service_date', 'stop_delays'):
            facts[row.service_date].append(list(row.stop_delays.values()))
    out = []
    # The planner only holds the current timetable window; earlier days are unknown, not "no service".
    first_known = min((d for d, _ in scheduled), default=None) if scheduled else None
    day = start
    while day <= end:
        metrics = summarize(facts.get(day, []))
        if first_known is None or day < first_known:
            planned = None
        elif direction == 'all':
            planned = sum(n for (d, _), n in scheduled.items() if d == day)
        else:
            planned = scheduled.get((day, direction), 0)
        if metrics['tripCount']:
            status = 'available'
        else:
            status = 'no_service' if planned == 0 else 'no_data'
        out.append({
            'routeId': route_id, 'date': day.isoformat(), 'direction': direction, 'quality': quality, 'status': status,
            **metrics, 'scheduledTripCount': planned,
            'coverage': round(min(1.0, metrics['tripCount'] / planned), 4) if planned else None,
        })
        day += timedelta(days=1)
    return out


ON_TIME_LATE = 180  # a trip counts as on time when it averages under 3 minutes late (mirrored in src/lib/punctuality.ts)
MIN_SEGMENT_SAMPLES = 3


def route_reliability(route_id: str, today: date, days: int = 30) -> dict:
    """Recent reliability of one route: trip-weighted means, the share of trips under
    3 minutes late, and the signed mean by hour of day (Europe/Ljubljana)."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo('Europe/Ljubljana')
    rows = TripDelay.objects.filter(route_id=route_id, service_date__range=(today - timedelta(days=days - 1), today), canceled=False)
    signed, late = [], []
    hours: dict[int, list[float]] = defaultdict(list)
    for row in rows.only('stop_delays', 'first_seen'):
        values = list(row.stop_delays.values())
        if not values:
            continue
        mean = fmean(values)
        signed.append(mean)
        late.append(fmean(max(0, d) for d in values))
        hours[row.first_seen.astimezone(tz).hour].append(mean)
    return {
        'routeId': route_id, 'days': days, 'tripCount': len(signed),
        'meanSignedDelaySeconds': round(fmean(signed), 1) if signed else None,
        'meanLateSeconds': round(fmean(late), 1) if late else None,
        'onTimeShare': round(sum(1 for v in late if v < ON_TIME_LATE) / len(late), 4) if late else None,
        'byHour': [{'hour': h, 'meanSignedDelaySeconds': round(fmean(v), 1), 'tripCount': len(v)} for h, v in sorted(hours.items())],
    }


def typical_segments(route_id: str, today: date, days: int = 21) -> dict[str, float]:
    """{"fromStop>toStop": seconds}: median observed running time between consecutive stops
    of a route, for segments with at least MIN_SEGMENT_SAMPLES trips."""
    samples: dict[str, list[int]] = defaultdict(list)
    rows = TripDelay.objects.filter(route_id=route_id, service_date__range=(today - timedelta(days=days - 1), today), canceled=False)
    for row in rows.exclude(segments={}).only('segments'):
        for key, seconds in row.segments.items():
            samples[key].append(seconds)
    # The median resists the odd stuck or skipped stop better than the mean.
    return {key: float(sorted(v)[len(v) // 2]) for key, v in samples.items() if len(v) >= MIN_SEGMENT_SAMPLES}


def observed_trip_delays(trips: list[tuple[str, date]]) -> dict[tuple[str, date], dict[str, int]]:
    """{(tripId, serviceDay): {stopSequence: delaySeconds}} observed so far; trips never observed are absent."""
    if not trips:
        return {}
    wanted = set(trips)
    rows = TripDelay.objects.filter(trip_id__in={t for t, _ in trips}, service_date__in={d for _, d in trips}).only('trip_id', 'service_date', 'stop_delays')
    return {(r.trip_id, r.service_date): dict(r.stop_delays) for r in rows if (r.trip_id, r.service_date) in wanted}


def final_observed_delays(route_id: str, day: date) -> dict[str, int]:
    """{tripId: delaySeconds} at the last stop each trip of the route was observed at that day."""
    out = {}
    for row in TripDelay.objects.filter(route_id=route_id, service_date=day, canceled=False).exclude(stop_delays={}).only('trip_id', 'stop_delays'):
        last = max(row.stop_delays, key=int)
        out[row.trip_id] = row.stop_delays[last]
    return out

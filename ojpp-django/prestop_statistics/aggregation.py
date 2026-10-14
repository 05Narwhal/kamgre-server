"""Daily route reliability from collected trip delays.

Every trip weighs the same: a trip's delay is the mean over its recorded stops, and a
day's figures are means over trips. p95 is the nearest-rank 95th percentile of the
per-trip late means. Days without measurements are `no_data` with null metrics, never
zero; days with no scheduled trip are `no_service`.
"""
import math
import threading
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


DEPARTURE_DAYS = 56  # eight weeks: enough Saturdays and Sundays for USUAL_MIN_SAMPLES
USUAL_MIN_SAMPLES = 5  # "usually x late" needs at least this many trips of that departure
_starts: dict[str, Optional[str]] = {}  # tripId -> scheduled start "HH:MM" (None: unknown to the planner)
_starts_lock = threading.Lock()
START_CHUNK = 80


def day_kind(day: date) -> str:
    """'workday', 'saturday' or 'sunday' (Slovenia's work-free holidays count as Sunday)."""
    from prestop_api.sztimetables import holiday
    if day.weekday() == 6 or holiday(day):
        return 'sunday'
    return 'saturday' if day.weekday() == 5 else 'workday'


def trip_starts(trip_ids) -> dict[str, str]:
    """{tripId: "HH:MM"} scheduled departure from the first stop, from the planner (cached for the process)."""
    import json
    from prestop_api.upstream import UpstreamError, otp
    missing = [t for t in dict.fromkeys(trip_ids) if t not in _starts]
    for i in range(0, len(missing), START_CHUNK):
        chunk = missing[i:i + START_CHUNK]
        query = ' '.join(f't{n}: trip(id: {json.dumps(t)}) {{ departureStoptime {{ scheduledDeparture }} }}' for n, t in enumerate(chunk))
        try:
            data = otp().query('{ ' + query + ' }')
        except UpstreamError:
            break  # try again next time
        with _starts_lock:
            for n, t in enumerate(chunk):
                seconds = ((data.get(f't{n}') or {}).get('departureStoptime') or {}).get('scheduledDeparture')
                _starts[t] = f'{seconds // 3600 % 24:02d}:{seconds % 3600 // 60:02d}' if seconds is not None else None
    return {t: _starts[t] for t in trip_ids if _starts.get(t)}


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return round(float(ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2), 1)


def _on_time(late: list[float]) -> Optional[float]:
    return round(sum(1 for v in late if v < ON_TIME_LATE) / len(late), 4) if late else None


def _trip_rows(route_id: str, start: date, end: date):
    """(serviceDate, tripId, first_seen, signed mean, late mean) per observed trip."""
    rows = TripDelay.objects.filter(route_id=route_id, service_date__range=(start, end), canceled=False)
    for row in rows.only('service_date', 'trip_id', 'stop_delays', 'first_seen'):
        values = list(row.stop_delays.values())
        if values:
            yield row.service_date, row.trip_id, row.first_seen, fmean(values), fmean(max(0, d) for d in values)


def departure_delays(route_id: str, today: date, kind: Optional[str] = None) -> dict[str, list[tuple[float, float]]]:
    """{"HH:MM": [(signed, late) per trip]} for the route's departures on days of `kind` (default: today's)
    over the last DEPARTURE_DAYS days."""
    kind = kind or day_kind(today)
    trips = [r for r in _trip_rows(route_id, today - timedelta(days=DEPARTURE_DAYS - 1), today) if day_kind(r[0]) == kind]
    starts = trip_starts({r[1] for r in trips})
    out: dict[str, list] = defaultdict(list)
    for _, trip_id, _, signed, late in trips:
        if trip_id in starts:
            out[starts[trip_id]].append((signed, late))
    return out


def usual_delays(route_id: str, today: date, kind: Optional[str] = None) -> dict[str, float]:
    """{"HH:MM": median delay in seconds}: how late each departure usually is on this kind of day (USUAL_MIN_SAMPLES)."""
    return {start: _median([s for s, _ in v]) for start, v in departure_delays(route_id, today, kind).items() if len(v) >= USUAL_MIN_SAMPLES}


def route_reliability(route_id: str, today: date, days: int = 30) -> dict:
    """Recent reliability of one route: trip-weighted means, the share of trips under 3 minutes late, the signed
    mean and median by hour of day (Europe/Ljubljana), per day (`byDay`, the last `days`) and per departure on
    today's kind of day (`byDeparture`, the last DEPARTURE_DAYS: "usually x late" with USUAL_MIN_SAMPLES)."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo('Europe/Ljubljana')
    first = today - timedelta(days=days - 1)
    rows = list(_trip_rows(route_id, first, today))
    starts = trip_starts({r[1] for r in rows})
    signed = [r[3] for r in rows]
    late = [r[4] for r in rows]
    hours: dict[int, list[float]] = defaultdict(list)
    by_day: dict[date, list[tuple[float, float]]] = defaultdict(list)
    for day, trip_id, seen, s, l in rows:
        hour = int(starts[trip_id][:2]) if trip_id in starts else seen.astimezone(tz).hour
        hours[hour].append(s)
        by_day[day].append((s, l))
    departures = departure_delays(route_id, today)
    return {
        'routeId': route_id, 'days': days, 'tripCount': len(signed),
        'meanSignedDelaySeconds': round(fmean(signed), 1) if signed else None,
        'meanLateSeconds': round(fmean(late), 1) if late else None,
        'onTimeShare': _on_time(late),
        'byHour': [{'hour': h, 'meanSignedDelaySeconds': round(fmean(v), 1), 'tripCount': len(v), 'medianDelaySeconds': _median(v)}
                   for h, v in sorted(hours.items())],
        'byDeparture': [{'start': start, 'samples': len(v), 'medianDelaySeconds': _median([s for s, _ in v]),
                         'p85DelaySeconds': round(float(nearest_rank([s for s, _ in v], 0.85)), 1), 'onTimeShare': _on_time([l for _, l in v])}
                        for start, v in sorted(departures.items())],
        'byDay': [{'date': d.isoformat(), 'samples': len(v), 'medianDelaySeconds': _median([s for s, _ in v]), 'onTimeShare': _on_time([l for _, l in v])}
                  for d in (first + timedelta(days=i) for i in range(days)) for v in [by_day.get(d, [])]],
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

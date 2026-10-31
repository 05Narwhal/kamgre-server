"""Nightly rollups of SŽ trains (spec 2026-10-26 F6): one TrainDay per train and day, one StationDay per station
and day, built from the delays the collector keeps in TripDelay (SŽ trips carry the combined feed's per-station
reports). Run by `manage.py rollup_stats` in the night window (systemd prestop-nightly), so the statistics screen and
the train pages read small rows instead of aggregating TripDelay per request.

One punctuality definition app-wide: a train is on time at a station when it is less than ON_TIME_LATE late (3 min,
as zamudil.si counts and as SŽ reports whole minutes); the same bound as aggregation.ON_TIME_LATE and
src/lib/punctuality.ts.

Spec 2026-10-31 H1: each row also has its scheduled first departure, whether SŽ canceled the run and how much of it
replacement buses ran that day (that date's plan, scheduled.day_plan: the feed's buses and closures.py's), and each
station the delay gained since the previous reported one, so "where time is lost" is a sum. Canceled runs and runs a
bus replaced without any report get a row too (no delays), so trends can count them.
"""
import json
import logging
from datetime import date, timedelta
from typing import Callable, Optional

from django.db import transaction

from prestop_api import sz
from prestop_api.upstream import UpstreamError, otp
from prestop_statistics.aggregation import ON_TIME_LATE
from prestop_statistics.models import StationDay, TrainDay, TripDelay

logger = logging.getLogger(__name__)
SZ_OPERATOR = 'IJPP:1161'
CHUNK = 60  # trips per OTP query
TRIP_Q = 'route { gtfsId shortName mode } stoptimes { stopPosition scheduledDeparture stop { gtfsId name } }'


def otp_trip_stops(trip_ids: list[str]) -> dict[str, Optional[dict]]:
    """trip id -> {'route', 'name', 'mode', 'stops' {stopPosition: (stop id, name)}, 'departure' (scheduled at the
    first stop, s after midnight), 'times' {stopPosition: scheduled departure there}}, or None when OTP no longer has the trip (an older timetable's): its day is left
    out, not guessed."""
    out: dict[str, Optional[dict]] = {}
    for i in range(0, len(trip_ids), CHUNK):
        chunk = trip_ids[i:i + CHUNK]
        query = ' '.join(f't{k}: trip(id: {json.dumps(t)}) {{ {TRIP_Q} }}' for k, t in enumerate(chunk))
        data = otp().query('{ ' + query + ' }', timeout=(5, 60))
        for k, t in enumerate(chunk):
            trip = data.get(f't{k}')
            times = sorted((s['stopPosition'], s.get('scheduledDeparture')) for s in (trip or {}).get('stoptimes') or [])
            out[t] = {'departure': times[0][1] if times else None, 'times': dict(times),
                      'route': trip['route']['gtfsId'], 'name': trip['route'].get('shortName') or '', 'mode': trip['route'].get('mode'),
                      'stops': {s['stopPosition']: (s['stop']['gtfsId'], s['stop'].get('name') or '') for s in trip.get('stoptimes') or []}} if trip else None
    return out


def scraper_tracks(day: date) -> dict[str, dict[str, str]]:
    """{train number: {stop id: track}} as SŽ's boards announced them that day (tracks.py's scraper); {} when unknown."""
    from prestop_api import tracks
    if not tracks.tracks.url:
        return {}
    try:
        rows = tracks.tracks.mirrors.get_json(f'?date={day.isoformat()}', check=lambda d: d['trains'], limit=8 * 1024 * 1024, timeout=(5, 60))
    except UpstreamError as e:
        logger.info('Tracks of %s unavailable: %r', day, e)
        return {}
    found: dict[str, dict[str, str]] = {}
    for r in rows if isinstance(rows, list) else []:
        train, stop, track = str(r.get('train_id') or '').strip(), r.get('ijpp_id'), str(r.get('platform') or '').strip()
        if train and stop and track:
            found.setdefault(train, {})[stop] = track
    return found


def train_row(day: date, delay: Optional[TripDelay], trip: dict, tracks: dict, replaced: Optional[str] = None,
              trip_id: str = '') -> Optional[dict]:
    """The TrainDay fields of one SŽ train's run, or None for a bus (replacement) or a run with nothing to say: no
    report, not canceled, not replaced. `delay` None: a run with no TripDelay row (a bus ran instead of all of it)."""
    category, number = sz.train_parts(trip['name'])
    if not number or (trip.get('mode') and trip['mode'] != 'RAIL'):
        return None
    raw = delay.stop_delays if delay else {}
    reported = {int(k): v for k, v in (raw or {}).items() if str(k).lstrip('-').isdigit() and v is not None}
    stops, before = [], None
    for p in sorted(trip['stops']):
        d = reported.get(p)
        stops.append({'id': trip['stops'][p][0], 'name': trip['stops'][p][1], 'delay': d,
                      'gained': d - before if d is not None and before is not None else None,
                      'track': (tracks.get(number) or {}).get(trip['stops'][p][0]), 'time': (trip.get('times') or {}).get(p)})
        before = d if d is not None else before
    delays = [s['delay'] for s in stops if s['delay'] is not None]
    canceled = bool(delay and delay.canceled)
    if not stops or not (delays or canceled or replaced in ('part', 'whole')):
        return None
    return {'service_date': day, 'number': number, 'category': category or '', 'route_id': delay.route_id if delay else trip['route'],
            'trip_id': delay.trip_id if delay else trip_id, 'origin': stops[0]['name'], 'destination': stops[-1]['name'],
            'max_delay': max(delays) if delays else None, 'avg_delay': round(sum(delays) / len(delays)) if delays else None,
            'final_delay': delays[-1] if delays else None,
            'on_time_share': round(sum(1 for d in delays if d < ON_TIME_LATE) / len(delays), 4) if delays else None, 'stops': stops,
            'departure': trip.get('departure'), 'canceled': canceled, 'replaced': replaced}


def day_plan(day: date) -> Optional[dict]:
    """That service day's replacement plan (scheduled.day_plan), or None when it cannot be read: OTP no longer has the
    day, or the plan has no trains (then nothing is known about replacements and the rows keep `replaced` null)."""
    from prestop_api import scheduled
    try:
        plan = scheduled.day_plan(day, wait=90)
    except Exception as e:  # noqa: BLE001 - a plan we cannot build leaves `replaced` unknown, never the rollup down
        logger.info('Replacement plan of %s unavailable: %r', day, e)
        return None
    return plan if plan and plan.get('trips') else None


def replaced_runs(day: date, plan: Optional[dict]) -> Optional[dict[str, str]]:
    """Train trip id -> 'part' or 'whole' for the runs of `day` a bus ran instead of (any of); None: unknown."""
    if plan is None:
        return None
    from prestop_api import replacement, scheduled
    out: dict[str, str] = {}
    for trip_id in plan.get('sections') or {}:
        for run in (plan.get('trips') or {}).get(trip_id) or []:
            if scheduled._service_date(run) != day:
                continue
            stretches = replacement.crossed(plan, run)
            if not stretches:
                continue
            reach, whole = 0, True
            for a, b, _ in stretches:  # in order: whole when they join up from the first stop to the last
                whole = whole and a <= reach
                reach = max(reach, b)
            out[trip_id] = 'whole' if whole and reach >= len(run['stops']) - 1 else 'part'
    return out


def station_rows(day: date, trains: list[dict]) -> list[dict]:
    """StationDay fields from one day's train rows; `hours` {hour of the scheduled time there: [trains, on time, sum of
    their delays]} (spec 2026-10-31 H3: a station's trains by hour)."""
    seen: dict[str, dict] = {}
    for t in trains:
        if t.get('canceled'):
            continue
        for s in t['stops']:
            if s['delay'] is None:
                continue
            row = seen.setdefault(s['id'], {'name': s['name'], 'delays': [], 'hours': {}})
            row['delays'].append(s['delay'])
            if s.get('time') is not None:
                hour = row['hours'].setdefault(str(s['time'] // 3600 % 24), [0, 0, 0])
                hour[0] += 1
                hour[1] += s['delay'] < ON_TIME_LATE
                hour[2] += s['delay']
    return [{'service_date': day, 'stop_id': stop, 'name': v['name'], 'trains': len(v['delays']),
             'on_time_share': round(sum(1 for d in v['delays'] if d < ON_TIME_LATE) / len(v['delays']), 4),
             'avg_delay': round(sum(v['delays']) / len(v['delays'])), 'hours': v['hours']} for stop, v in sorted(seen.items())]


def _weight(row: dict) -> tuple[int, int]:
    """Which of two runs of one number the day keeps: the one with more reports, else one that ran."""
    return sum(s['delay'] is not None for s in row['stops']), 0 if row['canceled'] else 1


def build(day: date, trip_stops: Optional[Callable[[list[str]], dict]] = None,
          day_tracks: Optional[Callable[[date], dict]] = None, memo: Optional[dict] = None,
          plan: Optional[Callable[[date], Optional[dict]]] = None) -> tuple[list[dict], list[dict], dict]:
    """(train rows, station rows, counts) of one service day; by default OTP's trips, the scraper's tracks and that
    day's replacement plan. `memo`: trips already looked up (a backfill asks OTP about each timetable trip once, not
    once per day)."""
    trip_stops, day_tracks, plan = trip_stops or otp_trip_stops, day_tracks or scraper_tracks, plan or day_plan
    memo = {} if memo is None else memo
    rows = list(TripDelay.objects.filter(service_date=day, operator_id=SZ_OPERATOR))
    replaced = replaced_runs(day, plan(day)) if rows else None
    reported = {r.trip_id for r in rows}
    missing = sorted((reported | set(replaced or {})) - memo.keys())
    if missing:
        memo.update(trip_stops(missing))
    tracks = day_tracks(day) if rows else {}
    by_number: dict[str, dict] = {}
    unknown = 0
    runs = [(r.trip_id, r) for r in rows] + [(t, None) for t in sorted(set(replaced or {}) - reported)]
    for trip_id, r in runs:
        trip = memo.get(trip_id)
        if not trip:
            unknown += r is not None
            continue
        how = None if replaced is None else replaced.get(trip_id, 'none')
        row = train_row(day, r, trip, tracks, how, trip_id)
        if not row:
            continue
        old = by_number.get(row['number'])
        # A number on two routes the same day (LP 4208, 23 Oct 2026) is one train: the run with more reports wins.
        if not old or _weight(row) > _weight(old):
            by_number[row['number']] = row
    trains = sorted(by_number.values(), key=lambda t: t['number'])
    counts = {'trips': len(rows), 'trains': len(trains), 'unknown trips': unknown,
              'canceled': sum(1 for t in trains if t['canceled']),
              'replaced': None if replaced is None else sum(1 for t in trains if t['replaced'] in ('part', 'whole'))}
    return trains, station_rows(day, trains), counts


def write(day: date, trains: list[dict], stations: list[dict]) -> None:
    """Replace the day's rows (a re-run of a night gives the same table)."""
    with transaction.atomic():
        TrainDay.objects.filter(service_date=day).delete()
        StationDay.objects.filter(service_date=day).delete()
        TrainDay.objects.bulk_create([TrainDay(**t) for t in trains])
        StationDay.objects.bulk_create([StationDay(**s) for s in stations])


def days_since(since: date, before: date) -> list[date]:
    """Days from `since` up to (not including) `before` that still have SŽ delays, newest first: a re-roll after the
    rows gained fields (`rollup_stats --since`), whether or not the day has rows."""
    return sorted(set(TripDelay.objects.filter(service_date__gte=since, service_date__lt=before, operator_id=SZ_OPERATOR)
                      .values_list('service_date', flat=True).distinct()), reverse=True)


def days_to_backfill(before: date, days: int) -> list[date]:
    """Days in the `days` before `before` with SŽ delays but no train rows yet, newest first."""
    start = before - timedelta(days=days)
    have = set(TrainDay.objects.filter(service_date__gte=start, service_date__lt=before).values_list('service_date', flat=True).distinct())
    with_data = set(TripDelay.objects.filter(service_date__gte=start, service_date__lt=before, operator_id=SZ_OPERATOR)
                    .values_list('service_date', flat=True).distinct())
    return sorted(with_data - have, reverse=True)

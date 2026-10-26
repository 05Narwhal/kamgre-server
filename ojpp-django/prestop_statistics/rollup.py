"""Nightly rollups of SŽ trains (spec 2026-10-26 F6): one TrainDay per train and day, one StationDay per station
and day, built from the delays the collector keeps in TripDelay (SŽ trips carry the combined feed's per-station
reports). Run by `manage.py rollup_stats` in the night window (systemd prestop-nightly), so the statistics screen and
the train pages read small rows instead of aggregating TripDelay per request.

One punctuality definition app-wide: a train is on time at a station when it is less than ON_TIME_LATE late (3 min,
as zamudil.si counts and as SŽ reports whole minutes); the same bound as aggregation.ON_TIME_LATE and
src/lib/punctuality.ts.
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
TRIP_Q = 'route { gtfsId shortName mode } stoptimes { stopPosition stop { gtfsId name } }'


def otp_trip_stops(trip_ids: list[str]) -> dict[str, Optional[dict]]:
    """trip id -> {'route', 'name', 'mode', 'stops' {stopPosition: (stop id, name)}}, or None when OTP no longer has
    the trip (an older timetable's): its day is left out, not guessed."""
    out: dict[str, Optional[dict]] = {}
    for i in range(0, len(trip_ids), CHUNK):
        chunk = trip_ids[i:i + CHUNK]
        query = ' '.join(f't{k}: trip(id: {json.dumps(t)}) {{ {TRIP_Q} }}' for k, t in enumerate(chunk))
        data = otp().query('{ ' + query + ' }', timeout=(5, 60))
        for k, t in enumerate(chunk):
            trip = data.get(f't{k}')
            out[t] = {'route': trip['route']['gtfsId'], 'name': trip['route'].get('shortName') or '', 'mode': trip['route'].get('mode'),
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


def train_row(day: date, delay: TripDelay, trip: dict, tracks: dict) -> Optional[dict]:
    """The TrainDay fields of one SŽ train's run, or None for a bus (replacement) or a run with nothing reported."""
    category, number = sz.train_parts(trip['name'])
    if not number or (trip.get('mode') and trip['mode'] != 'RAIL'):
        return None
    reported = {int(k): v for k, v in (delay.stop_delays or {}).items() if str(k).lstrip('-').isdigit() and v is not None}
    order = sorted(trip['stops'])
    stops = [{'id': trip['stops'][p][0], 'name': trip['stops'][p][1], 'delay': reported.get(p),
              'track': (tracks.get(number) or {}).get(trip['stops'][p][0])} for p in order]
    delays = [s['delay'] for s in stops if s['delay'] is not None]
    if not delays or not stops:
        return None
    return {'service_date': day, 'number': number, 'category': category or '', 'route_id': delay.route_id, 'trip_id': delay.trip_id,
            'origin': stops[0]['name'], 'destination': stops[-1]['name'], 'max_delay': max(delays),
            'avg_delay': round(sum(delays) / len(delays)), 'final_delay': delays[-1],
            'on_time_share': round(sum(1 for d in delays if d < ON_TIME_LATE) / len(delays), 4), 'stops': stops}


def station_rows(day: date, trains: list[dict]) -> list[dict]:
    """StationDay fields from one day's train rows."""
    seen: dict[str, dict] = {}
    for t in trains:
        for s in t['stops']:
            if s['delay'] is None:
                continue
            row = seen.setdefault(s['id'], {'name': s['name'], 'delays': []})
            row['delays'].append(s['delay'])
    return [{'service_date': day, 'stop_id': stop, 'name': v['name'], 'trains': len(v['delays']),
             'on_time_share': round(sum(1 for d in v['delays'] if d < ON_TIME_LATE) / len(v['delays']), 4),
             'avg_delay': round(sum(v['delays']) / len(v['delays']))} for stop, v in sorted(seen.items())]


def build(day: date, trip_stops: Optional[Callable[[list[str]], dict]] = None,
          day_tracks: Optional[Callable[[date], dict]] = None, memo: Optional[dict] = None) -> tuple[list[dict], list[dict], dict]:
    """(train rows, station rows, counts) of one service day; by default OTP's trips and the scraper's tracks. `memo`:
    trips already looked up (a backfill asks OTP about each timetable trip once, not once per day)."""
    trip_stops, day_tracks = trip_stops or otp_trip_stops, day_tracks or scraper_tracks
    memo = {} if memo is None else memo
    rows = list(TripDelay.objects.filter(service_date=day, operator_id=SZ_OPERATOR, canceled=False))
    missing = sorted({r.trip_id for r in rows} - memo.keys())
    if missing:
        memo.update(trip_stops(missing))
    tracks = day_tracks(day) if rows else {}
    by_number: dict[str, dict] = {}
    unknown = 0
    for r in rows:
        trip = memo.get(r.trip_id)
        if not trip:
            unknown += 1
            continue
        row = train_row(day, r, trip, tracks)
        if not row:
            continue
        old = by_number.get(row['number'])
        # A number on two routes the same day (LP 4208, 23 Oct 2026) is one train: the run with more reports wins.
        if not old or sum(s['delay'] is not None for s in row['stops']) > sum(s['delay'] is not None for s in old['stops']):
            by_number[row['number']] = row
    trains = sorted(by_number.values(), key=lambda t: t['number'])
    return trains, station_rows(day, trains), {'trips': len(rows), 'trains': len(trains), 'unknown trips': unknown}


def write(day: date, trains: list[dict], stations: list[dict]) -> None:
    """Replace the day's rows (a re-run of a night gives the same table)."""
    with transaction.atomic():
        TrainDay.objects.filter(service_date=day).delete()
        StationDay.objects.filter(service_date=day).delete()
        TrainDay.objects.bulk_create([TrainDay(**t) for t in trains])
        StationDay.objects.bulk_create([StationDay(**s) for s in stations])


def days_to_backfill(before: date, days: int) -> list[date]:
    """Days in the `days` before `before` with SŽ delays but no train rows yet, newest first."""
    start = before - timedelta(days=days)
    have = set(TrainDay.objects.filter(service_date__gte=start, service_date__lt=before).values_list('service_date', flat=True).distinct())
    with_data = set(TripDelay.objects.filter(service_date__gte=start, service_date__lt=before, operator_id=SZ_OPERATOR)
                    .values_list('service_date', flat=True).distinct())
    return sorted(with_data - have, reverse=True)

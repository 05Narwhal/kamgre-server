"""SŽ train pages and the statistics overview (spec 2026-10-26 F7).

- `train(number, day)`: a train's run on a service day: the trip (stops with planned and live times, tracks, distance
  along the line; trips.build_trip), the train on the map now (its delay, where from, measured or SŽ's forecast,
  next station; scheduled.vehicles through trainlive), and the notices on its line.
- `history(number, days)`: its last runs from the nightly rollups (prestop_statistics.rollup).
- `overview()`: trains on their way, how many are on time, 3–4 min and 5+ min late now, the biggest
  delays now and the busiest stations.
- `station(stop ids, days)`: a station's days from the rollups.

On time = less than ON_TIME_LATE late, the one definition of rollup.py and the app.
"""
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import leg_alerts, mapping, sources, sz
from .upstream import UpstreamError

ON_TIME_LATE = 180   # s (prestop_statistics.aggregation.ON_TIME_LATE)
LATE = 300           # s: this late or more is "late" (5′+); between the two "slightly late" (the app's delayTone)
BIGGEST = 8          # delays listed on the overview
STATIONS = 40        # stations listed (the statistics overview shows the first few, its Stations tab all)
STATION_DAYS = 7     # days of rollups behind the overview's stations
MAX_DAYS = 90        # history asked for at most
DAY_WAIT = 8         # s a request waits for another day's timetable (today's is kept warm)
LOCAL = ZoneInfo('Europe/Ljubljana')


def number_of(route: dict) -> Optional[str]:
    return sz.train_parts(mapping.route_name(route))[1]


def runs_on(day: date) -> list[dict]:
    """The trains (not replacement buses) running on service day `day`, from the timetable the map uses."""
    from . import scheduled
    if day == scheduled.service_day():
        snap = scheduled.timetable.wait(DAY_WAIT)
    else:
        snap = scheduled.day_timetable(day).wait(DAY_WAIT)
    if not snap:
        raise UpstreamError(f'timetable of {day} not loaded')
    # today's timetable also holds yesterday's late trains: each run by its own service day
    return [t for t in snap.value if t['route'].get('mode') == 'RAIL'
            and datetime.fromtimestamp(t['serviceDay'] + 12 * 3600, LOCAL).date() == day]


def find_run(number: str, day: date) -> Optional[dict]:
    """The run of train `number` that day; a number listed on two routes (LP 4208) is one train, the first found."""
    return next((t for t in runs_on(day) if number_of(t['route']) == number), None)


def vehicle_of(number: str) -> Optional[dict]:
    """The train on the map now, if it is on its way."""
    snap = sources.vehicles.peek()
    return next((v for v in (snap.value if snap else []) if v.get('mode') == 'rail' and v.get('trainNumber') == number), None)


def train(number: str, day: date, lang: str) -> Optional[dict]:
    """{'number', 'name', 'category', 'date', 'trip' (None: it doesn't run that day), 'vehicle', 'alerts'}; None when
    no train has that number that day."""
    from . import scheduled, trips
    run = find_run(number, day)
    if not run:
        return None
    found = trips.load_trips([run['id']], day).get(run['id'])
    trip = trips.build_trip(found, {}, geometry=False) if found else None
    if trip and trip['stops']:
        from . import replacement
        # the stretches a bus runs instead that day, from the plan boards, lines and journeys use
        sections = replacement.trip_sections(trip, scheduled.plan_at(replacement._epoch(trip['stops'][0]['scheduledDeparture']), wait=DAY_WAIT))
        if sections:
            trip['replacedSections'] = sections
    route_id = run['route']['gtfsId']
    start = (run.get('departures') or [run['serviceDay']])[0]
    end = (run.get('arrivals') or [run['serviceDay'] + 86400])[-1]
    try:  # the notices on its route in effect while it runs that day
        alerts = [mapping.public_alert(a) for a in sources.alerts(lang) if route_id in a['routeIds'] and a['_from'] <= end
                  and (a['_to'] is None or a['_to'] >= start) and leg_alerts.on_listed_day(a, start, end)]
    except UpstreamError:
        alerts = []
    category, _ = sz.train_parts(mapping.route_name(run['route']))
    return {'number': number, 'name': mapping.route_name(run['route']) or number, 'category': category, 'date': day.isoformat(),
            'routeId': route_id, 'tripId': run['id'], 'trip': trip, 'vehicle': vehicle_of(number) if day == scheduled.service_day() else None,
            'alerts': alerts}


def history(number: str, days: int, today: date) -> dict:
    """The train's last `days` days from the rollups, newest first, and a summary: mean delay, and the share of runs
    that reached their last reported station on time."""
    from prestop_statistics.models import TrainDay
    rows = list(TrainDay.objects.filter(number=number, service_date__gte=today - timedelta(days=days), service_date__lt=today)
                .order_by('-service_date'))
    out = [{'date': r.service_date.isoformat(), 'avgDelaySeconds': r.avg_delay, 'maxDelaySeconds': r.max_delay,
            'finalDelaySeconds': r.final_delay, 'onTimeShare': r.on_time_share,
            'onTime': r.final_delay < ON_TIME_LATE if r.final_delay is not None else None} for r in rows]
    finals = [r.final_delay for r in rows if r.final_delay is not None]
    means = [r.avg_delay for r in rows if r.avg_delay is not None]
    return {'number': number, 'days': out, 'summary': {
        'runs': len(rows), 'avgDelaySeconds': round(sum(means) / len(means)) if means else None,
        'onTimeShare': round(sum(1 for d in finals if d < ON_TIME_LATE) / len(finals), 4) if finals else None}}


def overview(today: date, now: Optional[float] = None) -> dict:
    """Trains on their way (the map's), the share of them on time now (of those with a known delay), the biggest
    delays now, and the busiest stations of the last STATION_DAYS days with their share on time."""
    from prestop_statistics.models import StationDay
    snap = sources.vehicles.peek()
    trains = {}
    for v in (snap.value if snap else []):
        if v.get('mode') == 'rail' and v.get('trainNumber') and not v.get('replacement'):
            trains.setdefault(v['trainNumber'], v)
    known = [v for v in trains.values() if v.get('delaySeconds') is not None]
    run_of = _runs_by_id()
    biggest = sorted((v for v in known if v['delaySeconds'] >= ON_TIME_LATE), key=lambda v: -v['delaySeconds'])[:BIGGEST]
    late = []
    for v in biggest:
        run = run_of.get(v.get('tripId') or '')
        late.append({'number': v['trainNumber'], 'name': v['routeName'], 'category': v.get('trainCategory'), 'tripId': v.get('tripId'),
                     'vehicleId': v['id'], 'origin': (run['stops'][0].get('name') if run else None) or v.get('comesFrom'),
                     'destination': v.get('destination'), 'nextStop': v.get('nextStop'), 'delaySeconds': v['delaySeconds'],
                     **({'delayKind': v['delayKind']} if v.get('delayKind') else {})})
    since = today - timedelta(days=STATION_DAYS)
    per_stop: dict[str, dict] = {}
    for s in StationDay.objects.filter(service_date__gte=since, service_date__lt=today):
        row = per_stop.setdefault(s.stop_id, {'stopId': s.stop_id, 'name': s.name, 'trains': 0, 'onTime': 0.0, 'delay': 0.0})
        row['trains'] += s.trains
        row['onTime'] += (s.on_time_share or 0) * s.trains
        row['delay'] += (s.avg_delay or 0) * s.trains
    stations = sorted(per_stop.values(), key=lambda r: (-r['trains'], r['name']))[:STATIONS]
    late_now = sum(1 for v in known if v['delaySeconds'] >= LATE)
    on_time_now = sum(1 for v in known if v['delaySeconds'] < ON_TIME_LATE)
    return {'running': len(trains), 'measured': len(known),
            'buckets': {'onTime': on_time_now, 'slightlyLate': len(known) - on_time_now - late_now, 'late': late_now},
            'onTimeShare': round(on_time_now / len(known), 4) if known else None,
            'biggestDelays': late,
            'stations': [{'stopId': r['stopId'], 'name': r['name'], 'trains': r['trains'], 'onTimeShare': round(r['onTime'] / r['trains'], 4),
                          'avgDelaySeconds': round(r['delay'] / r['trains'])} for r in stations if r['trains']],
            'stationDays': STATION_DAYS}


def _runs_by_id() -> dict[str, dict]:
    from . import scheduled
    snap = scheduled.timetable.peek()
    return {t['id']: t for t in (snap.value if snap else [])}


def station(stop_ids: list[str], days: int, today: date) -> Optional[dict]:
    """A station's last `days` days (StationDay rows of any of its stop ids, merged per day), newest first, and a
    summary over them; None when the rollups have no train there."""
    from prestop_statistics.models import StationDay
    rows = list(StationDay.objects.filter(stop_id__in=stop_ids, service_date__gte=today - timedelta(days=days), service_date__lt=today))
    if not rows:
        return None
    per_day: dict[date, dict] = {}
    for r in rows:
        d = per_day.setdefault(r.service_date, {'trains': 0, 'onTime': 0.0, 'delay': 0.0})
        d['trains'] += r.trains
        d['onTime'] += (r.on_time_share or 0) * r.trains
        d['delay'] += (r.avg_delay or 0) * r.trains
    out = [{'date': d.isoformat(), 'trains': v['trains'], 'onTimeShare': round(v['onTime'] / v['trains'], 4) if v['trains'] else None,
            'avgDelaySeconds': round(v['delay'] / v['trains']) if v['trains'] else None} for d, v in sorted(per_day.items(), reverse=True)]
    trains = sum(v['trains'] for v in per_day.values())
    return {'stopId': stop_ids[0], 'name': rows[0].name, 'days': out, 'summary': {
        'trains': trains, 'onTimeShare': round(sum(v['onTime'] for v in per_day.values()) / trains, 4) if trains else None,
        'avgDelaySeconds': round(sum(v['delay'] for v in per_day.values()) / trains) if trains else None}}

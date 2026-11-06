"""SŽ train pages and the statistics overview (spec 2026-10-26 F7).

- `train(number, day)`: a train's run on a service day: the trip (stops with planned and live times, tracks, distance
  along the line; trips.build_trip), the train on the map now (its delay, where from, measured or SŽ's forecast,
  next station; scheduled.vehicles through trainlive), and the notices on its line.
- `history(number, days)`: its last runs from the nightly rollups (prestop_statistics.rollup).
- `overview()`: trains on their way, how many are on time, 3–4 min and 5+ min late now, the biggest
  delays now and the busiest stations.
- `station(stop ids, days)`: a station's days from the rollups.
- `trends(days, today)`: the last 7, 30 or 90 days of all trains (spec 2026-10-31 H2): per day, per hour of the day,
  per category, the worst trains, where time is lost, and the same headline for the period before.

On time = less than ON_TIME_LATE late, the one definition of rollup.py and the app.
"""
import math
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import abroad, leg_alerts, mapping, sources, sz, zamudil
from .upstream import UpstreamError

ON_TIME_LATE = 180   # s (prestop_statistics.aggregation.ON_TIME_LATE)
LATE = 300           # s: this late or more is "late" (5′+); between the two "slightly late" (the app's delayTone)
BIGGEST = 8          # delays listed on the overview
STATIONS = 40        # stations listed (the statistics overview shows the first few, its Stations tab all)
STATION_DAYS = 7     # days of rollups behind the overview's stations
MAX_DAYS = 90        # history asked for at most
DAY_WAIT = 8         # s a request waits for another day's timetable (today's is kept warm)
TREND_DAYS = (7, 30, 90)
WORST = 10           # trains listed as the worst of a period
WORST_RUNS = 3       # runs a train needs in the period to be listed
SEGMENTS = 10        # stretches listed where time is lost
SEGMENT_RUNS = 5     # train runs a stretch needs in the period to be listed
TRENDS_TTL = 3600    # s the trends and histories are kept (warm.py refreshes the trends; a new night's rows renew them)
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
    """The run of train `number` that day: of an international train's legs the one in Slovenia (abroad.main_run); a
    number listed on two routes (LP 4208) is one train, the first found."""
    runs = [t for t in runs_on(day) if number_of(t['route']) == number]
    return (abroad.main_run(runs) if len(runs) > 1 else None) or next(iter(runs), None)


def vehicle_of(number: str, trip: Optional[dict] = None) -> Optional[dict]:
    """The train on the map now, if it is on its way; else the replacement bus running its part of `trip` now (one of
    its `replacedSections`' buses), so the train page opens on what the rider is in (N2)."""
    snap = sources.vehicles.peek()
    vehicles = snap.value if snap else []
    train = next((v for v in vehicles if v.get('mode') == 'rail' and v.get('trainNumber') == number), None)
    buses = {s['busTripId'] for s in (trip or {}).get('replacedSections') or []}
    return train or next((v for v in vehicles if v.get('replacement') and v.get('tripId') in buses), None)


def train(number: str, day: date, lang: str) -> Optional[dict]:
    """{'number', 'name', 'category', 'date', 'trip' (None: it doesn't run that day), 'vehicle', 'alerts'}; None when
    no train has that number that day."""
    from . import scheduled, trips
    run = find_run(number, day)
    if not run:
        return None
    found = trips.load_trips([run['id']], day).get(run['id'])
    trip = trips.build_trip(found, {}, geometry=False) if found else None  # polled: the shape comes once, from /trips
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
            'routeId': route_id, 'tripId': run['id'], 'trip': trip, 'vehicle': vehicle_of(number, trip) if day == scheduled.service_day() else None,
            'alerts': alerts, **({'trainClass': planned} if (planned := zamudil.class_of(number, day)) else {}), **stay_links(number, day, run)}


def stay_links(number: str, day: date, run: dict) -> dict:
    """Staying on the train (spec 2026-10-31 H9, train_stays.links_of): 'comesFrom', 'continuesAs', 'coupledWith'
    when known, with the times as timestamps."""
    import logging
    from prestop_statistics import train_stays
    try:
        found = train_stays.links_of(number, day)
    except Exception as e:  # noqa: BLE001 - optional: the train page stands without it
        logging.getLogger(__name__).warning('Train stays of %s unavailable: %r', number, e)
        return {}
    for key, field in (('comesFrom', 'arrival'), ('continuesAs', 'departure')):
        if key in found:
            found[key] = {**found[key], field: mapping.iso(run['serviceDay'] + found[key][field])}
    if found.get('comesFrom', {}).get('level') == 'sure':
        from . import trainlive
        # how late it leaves because that train is late (H8), as the board and the map say it before its own report
        came = trainlive.carried_for_trip(run['id'], (run.get('scheduledDepartures') or run['departures'])[0])
        if came and came['delay'] > 0:
            found['comesFrom']['delaySeconds'] = came['delay']
    return found


def _quantile(values: list[int], q: float) -> Optional[int]:
    """Nearest-rank quantile (0.5: the median, 0.8: 80 % of the values are at most this); None without values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def _ran(r) -> bool:
    """The run took place as a train (some of it at least): not canceled, not wholly replaced by buses."""
    return not r.canceled and r.replaced != 'whole'


def _real_ends(name: Optional[str], origin: Optional[str], destination: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """A rollup's ends are its stretch in Slovenia; a train abroad reads by where it really runs (RG 211, Reka / Rijeka -
    Vinkovci, not Ilirska Bistrica - Dobova), as its page does."""
    comes, goes = abroad.train_ends(name, origin, destination)
    return comes or origin or None, goes or destination or None


def history(number: str, days: int, today: date) -> dict:
    """The train's last `days` days from the rollups (up to yesterday), newest first, and a summary: mean delay, and
    the share of runs that reached their last reported station on time. Spec 2026-10-31 H2 adds, for the per-train
    statistics page: the usual (median) and 80th-percentile delay at each station of its latest route with the delay
    usually gained since the station before, the weekday pattern, canceled and replaced runs, the usual and worst
    delay, its name and ends, and the first day the rollups hold."""
    from prestop_statistics.models import TrainDay
    rows = list(TrainDay.objects.filter(number=number, service_date__gte=today - timedelta(days=days), service_date__lt=today)
                .order_by('-service_date'))
    ran = [r for r in rows if _ran(r)]
    out = [{'date': r.service_date.isoformat(), 'avgDelaySeconds': r.avg_delay, 'maxDelaySeconds': r.max_delay,
            'finalDelaySeconds': r.final_delay, 'onTimeShare': r.on_time_share,
            'onTime': r.final_delay < ON_TIME_LATE if r.final_delay is not None else None,
            **({'canceled': True} if r.canceled else {}), **({'replaced': r.replaced} if r.replaced in ('part', 'whole') else {})}
           for r in rows]
    finals = [r.final_delay for r in ran if r.final_delay is not None]
    means = [r.avg_delay for r in ran if r.avg_delay is not None]
    stations: dict[str, dict] = {}
    for r in ran:
        for s in r.stops or []:
            if abroad.is_abroad_stop(s.get('name'), s.get('id')):
                continue  # Slovenia only: rows rolled up before the feed's stations abroad were known keep them
            row = stations.setdefault(s['id'], {'name': s.get('name') or '', 'delays': [], 'gained': []})
            if s.get('delay') is not None:
                row['delays'].append(s['delay'])
            if s.get('gained') is not None:
                row['gained'].append(s['gained'])
    route = [s['id'] for s in (rows[0].stops if rows else [])]  # the latest run's stations, in order
    weekdays = [{'runs': 0, 'onTime': 0} for _ in range(7)]
    for r in ran:
        if r.final_delay is not None:
            w = weekdays[r.service_date.weekday()]
            w['runs'] += 1
            w['onTime'] += r.final_delay < ON_TIME_LATE
    latest = rows[0] if rows else None
    name = f'{latest.category} {number}'.strip() if latest else None
    origin, destination = _real_ends(name, latest.origin, latest.destination) if latest else (None, None)
    first = TrainDay.objects.order_by('service_date').values_list('service_date', flat=True).first()
    return {'number': number, 'days': out, 'summary': {
        'runs': len(ran), 'avgDelaySeconds': round(sum(means) / len(means)) if means else None,
        'onTimeShare': round(sum(1 for d in finals if d < ON_TIME_LATE) / len(finals), 4) if finals else None},
        'medianDelaySeconds': _quantile(means, 0.5), 'worstDelaySeconds': max((r.max_delay for r in ran if r.max_delay is not None), default=None),
        'stations': [{'stopId': stop, 'name': stations[stop]['name'], 'runs': len(stations[stop]['delays']),
                      'medianDelaySeconds': _quantile(stations[stop]['delays'], 0.5), 'p80DelaySeconds': _quantile(stations[stop]['delays'], 0.8),
                      'medianGainedSeconds': _quantile(stations[stop]['gained'], 0.5)} for stop in route if stop in stations],
        'weekdays': [{'runs': w['runs'], 'onTimeShare': round(w['onTime'] / w['runs'], 4) if w['runs'] else None} for w in weekdays],
        'canceled': sum(1 for r in rows if r.canceled), 'replaced': sum(1 for r in rows if r.replaced in ('part', 'whole')),
        'name': name, 'category': (latest.category or None) if latest else None,
        'origin': origin, 'destination': destination,
        'since': first.isoformat() if first else None}


def _aggregates() -> dict:
    """The headline figures as database aggregates: trains that ran with a reported delay, of them on time at their
    last reported station and 5+ min late there, their mean delay (over their reported stations), and the canceled
    and replaced runs. A row without a delay (canceled, replaced, not reported) is never on time."""
    from django.db.models import Avg, Count, Q
    measured = Q(canceled=False, final_delay__isnull=False)
    return dict(trains=Count('id', filter=measured), on_time=Count('id', filter=measured & Q(final_delay__lt=ON_TIME_LATE)),
                late=Count('id', filter=measured & Q(final_delay__gte=LATE)), mean=Avg('avg_delay', filter=measured),
                canceled=Count('id', filter=Q(canceled=True)), replaced=Count('id', filter=Q(replaced__in=['part', 'whole'])))


def _figures(found: dict) -> dict:
    trains, on_time, late = found['trains'], found['on_time'], found['late']
    return {'trains': trains, 'onTimeShare': round(on_time / trains, 4) if trains else None,
            'avgDelaySeconds': round(found['mean']) if found['mean'] is not None else None,
            'buckets': {'onTime': on_time, 'slightlyLate': trains - on_time - late, 'late': late},
            'canceled': found['canceled'], 'replaced': found['replaced']}


# Per day and stretch (the station reported before -> this one): runs and the delay they gained there, summed.
_LOST_SQL = """
WITH s AS (
  SELECT t.service_date AS day, t.id AS tid, e.ord, e.elem->>'id' AS stop, e.elem->>'name' AS name, (e.elem->>'gained')::int AS gained
  FROM prestop_statistics_trainday t CROSS JOIN LATERAL jsonb_array_elements(t.stops) WITH ORDINALITY AS e(elem, ord)
  WHERE t.service_date = ANY(%s) AND NOT t.canceled AND e.elem->>'delay' IS NOT NULL
), p AS (
  SELECT day, stop, name, gained, lag(stop) OVER w AS prev, lag(name) OVER w AS prev_name FROM s WINDOW w AS (PARTITION BY tid ORDER BY ord)
)
SELECT day, prev, max(prev_name), stop, max(name), count(*), sum(gained) FROM p
WHERE gained IS NOT NULL AND prev IS NOT NULL GROUP BY day, prev, stop
"""
LOST_KEEP = 24 * 3600  # s a day's stretches are kept while its rows stay as many (a re-roll of the same count: a day later)
_lost_days: dict[date, tuple[int, float, dict]] = {}


def time_lost(start: date, end: date, now: Optional[float] = None) -> list[dict]:
    """The SEGMENTS stretches between two reported stations where trains gained the most delay from `start` up to
    `end` (at least SEGMENT_RUNS runs, gaining on average). Expanding every run's stations is the costly part (about a
    second for 90 days of all trains), and a day's rows change only when the night rolls it up: each day's sums are
    kept until its row count changes or LOST_KEEP passes, so a rebuild after the night reads that night only."""
    import time
    from django.db import connection
    from django.db.models import Count
    from prestop_statistics.models import TrainDay
    now = time.time() if now is None else now
    counts = dict(TrainDay.objects.filter(service_date__gte=start, service_date__lt=end).values_list('service_date')
                  .annotate(n=Count('id')).order_by())
    stale = [d for d, n in counts.items() if d not in _lost_days or _lost_days[d][0] != n or now - _lost_days[d][1] > LOST_KEEP]
    if stale:
        fresh: dict[date, dict] = {d: {} for d in stale}
        with connection.cursor() as cursor:
            cursor.execute(_LOST_SQL, [stale])
            for day, a, an, b, bn, n, gained in cursor.fetchall():
                fresh[day][(a, b)] = (an or '', bn or '', n, gained)
        for d in stale:
            _lost_days[d] = (counts[d], now, fresh[d])
    for d in [d for d in _lost_days if d not in counts and start <= d < end]:
        _lost_days.pop(d)  # a day whose rows are gone
    total: dict[tuple, list] = {}
    for d in counts:
        for key, (an, bn, n, gained) in _lost_days[d][2].items():
            row = total.setdefault(key, [an, bn, 0, 0])
            row[2] += n
            row[3] += gained
    ranked = sorted(((k, v) for k, v in total.items() if v[2] >= SEGMENT_RUNS and v[3] > 0
                     and not abroad.is_abroad_stop(v[0], k[0]) and not abroad.is_abroad_stop(v[1], k[1])),
                    key=lambda kv: (-kv[1][3] / kv[1][2], -kv[1][2], kv[0]))[:SEGMENTS]
    return [{'fromStopId': a, 'fromName': an, 'toStopId': b, 'toName': bn, 'trains': n, 'meanGainedSeconds': round(g / n)}
            for (a, b), (an, bn, n, g) in ranked]


def trends(days: int, today: date) -> dict:
    """All trains over the `days` days before today (TrainDay rows up to yesterday): the headline with the same figures
    for the `days` before (`previous`), each day, each hour of the scheduled first departure, each category, the
    WORST trains (at least WORST_RUNS runs; by mean delay), and the SEGMENTS stretches between two reported stations
    where trains gain the most delay (at least SEGMENT_RUNS runs). `since`: the first day the rollups hold."""
    from django.db.models import Avg, Count, F, Max, Q
    from django.db.models.functions import Mod
    from prestop_statistics.models import TrainDay
    start = today - timedelta(days=days)
    period = TrainDay.objects.filter(service_date__gte=start, service_date__lt=today)
    measured = Q(canceled=False, final_delay__isnull=False)
    figures = _aggregates()
    per_day = [{'date': r['service_date'].isoformat(), **_figures(r)}
               for r in period.values('service_date').annotate(**figures).order_by('service_date')]
    hours = [{'trains': 0, 'onTimeShare': None, 'avgDelaySeconds': None} for _ in range(24)]
    for r in period.filter(departure__isnull=False).annotate(hour=Mod(F('departure') / 3600, 24)).values('hour').annotate(**figures):
        f = _figures(r)
        hours[int(r['hour'])] = {'trains': f['trains'], 'onTimeShare': f['onTimeShare'], 'avgDelaySeconds': f['avgDelaySeconds']}
    categories = sorted(({'category': r['category'] or None, 'trains': f['trains'], 'onTimeShare': f['onTimeShare'], 'avgDelaySeconds': f['avgDelaySeconds']}
                         for r in period.values('category').annotate(**figures) for f in [_figures(r)] if f['trains']),
                        key=lambda c: (-c['trains'], c['category'] or '~'))
    worst_rows = list(period.values('number').annotate(runs=Count('id', filter=measured), mean=Avg('avg_delay', filter=measured),
                                                       on_time=Count('id', filter=measured & Q(final_delay__lt=ON_TIME_LATE)),
                                                       worst=Max('max_delay', filter=measured))
                      .filter(runs__gte=WORST_RUNS, mean__isnull=False).order_by('-mean', 'number')[:WORST])
    latest = {r['number']: r for r in period.filter(number__in=[w['number'] for w in worst_rows])
              .order_by('number', '-service_date').distinct('number').values('number', 'category', 'origin', 'destination')}
    names = {w['number']: f"{latest.get(w['number'], {}).get('category') or ''} {w['number']}".strip() for w in worst_rows}
    ends = {n: _real_ends(name, latest.get(n, {}).get('origin'), latest.get(n, {}).get('destination')) for n, name in names.items()}
    worst = [{'number': w['number'], 'name': names[w['number']],
              'origin': ends[w['number']][0], 'destination': ends[w['number']][1],
              'runs': w['runs'], 'onTimeShare': round(w['on_time'] / w['runs'], 4), 'avgDelaySeconds': round(w['mean']),
              'maxDelaySeconds': w['worst']} for w in worst_rows]
    lost = time_lost(start, today)
    first = TrainDay.objects.order_by('service_date').values_list('service_date', flat=True).first()
    return {'days': days, 'from': start.isoformat(), 'to': (today - timedelta(days=1)).isoformat(),
            'since': first.isoformat() if first else None, 'headline': _figures(period.aggregate(**figures)),
            'previous': _figures(TrainDay.objects.filter(service_date__gte=start - timedelta(days=days), service_date__lt=start).aggregate(**figures)),
            'dates': per_day, 'hours': hours, 'categories': categories, 'worstTrains': worst, 'timeLost': lost}


_trends: dict[int, tuple[float, Optional[date], dict]] = {}


def latest_rollup() -> Optional[date]:
    from prestop_statistics.models import TrainDay
    return TrainDay.objects.order_by('-service_date').values_list('service_date', flat=True).first()


def trends_cached(days: int, today: date, now: Optional[float] = None, margin: float = 0) -> dict:
    """trends() kept TRENDS_TTL s, and renewed as soon as a new night's rows land (the latest rollup day changed) or
    the day turns. `margin`: rebuild this many s before it would expire (the warmer)."""
    import time
    now = time.time() if now is None else now
    latest = latest_rollup()
    hit = _trends.get(days)
    if hit and now - hit[0] < TRENDS_TTL - margin and hit[1] == latest and hit[2]['to'] == (today - timedelta(days=1)).isoformat():
        return hit[2]
    value = trends(days, today)
    _trends[days] = (now, latest, value)
    return value


def warm_trends(today: date, now: Optional[float] = None) -> None:
    """Called by warm.py every tick, busy or not (the database only): each period is rebuilt right after the nightly
    rollup lands, and before it would expire, so no request waits on it."""
    for days in TREND_DAYS:
        trends_cached(days, today, now, margin=120)


def overview(today: date, now: Optional[float] = None) -> dict:
    """Trains on their way (the map's), the share of them on time now (of those with a known delay), the biggest
    delays now, and the busiest stations of the last STATION_DAYS days with their share on time."""
    from prestop_statistics.models import StationDay
    from . import scheduled
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
                     'vehicleId': v['id'], 'origin': (scheduled._end_name(run['stops'][0]) if run else None) or v.get('comesFrom'),
                     'destination': v.get('destination'), 'nextStop': v.get('nextStop'), 'delaySeconds': v['delaySeconds'],
                     **({'delayKind': v['delayKind']} if v.get('delayKind') else {})})
    since = today - timedelta(days=STATION_DAYS)
    per_stop: dict[str, dict] = {}
    for s in StationDay.objects.filter(service_date__gte=since, service_date__lt=today, mode='rail'):
        if abroad.is_abroad_stop(s.name, s.stop_id):
            continue
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


def station(stop_ids: list[str], days: int, today: date, mode: str = 'rail') -> Optional[dict]:
    """A station's last `days` days (StationDay rows of any of its stop ids, merged per day), newest first, and a
    summary over them; None when the rollups have no train there. `mode` 'bus': its buses instead (bus_rollup.py)."""
    from prestop_statistics.models import StationDay
    rows = list(StationDay.objects.filter(stop_id__in=stop_ids, mode=mode, service_date__gte=today - timedelta(days=days), service_date__lt=today))
    if not rows:
        return None
    per_day: dict[date, dict] = {}
    hours = [[0, 0, 0] for _ in range(24)]
    for r in rows:
        d = per_day.setdefault(r.service_date, {'trains': 0, 'onTime': 0.0, 'delay': 0.0})
        d['trains'] += r.trains
        d['onTime'] += (r.on_time_share or 0) * r.trains
        d['delay'] += (r.avg_delay or 0) * r.trains
        for hour, (n, on_time, delay) in (r.hours or {}).items():
            if str(hour).isdigit() and 0 <= int(hour) < 24:
                cell = hours[int(hour)]
                cell[0], cell[1], cell[2] = cell[0] + n, cell[1] + on_time, cell[2] + delay
    out = [{'date': d.isoformat(), 'trains': v['trains'], 'onTimeShare': round(v['onTime'] / v['trains'], 4) if v['trains'] else None,
            'avgDelaySeconds': round(v['delay'] / v['trains']) if v['trains'] else None} for d, v in sorted(per_day.items(), reverse=True)]
    trains = sum(v['trains'] for v in per_day.values())
    return {'stopId': stop_ids[0], 'name': rows[0].name, 'days': out, 'summary': {
        'trains': trains, 'onTimeShare': round(sum(v['onTime'] for v in per_day.values()) / trains, 4) if trains else None,
        'avgDelaySeconds': round(sum(v['delay'] for v in per_day.values()) / trains) if trains else None},
        # by the hour of the scheduled time there (rows rolled up since H3; empty before)
        'hours': [{'trains': n, 'onTimeShare': round(on_time / n, 4) if n else None, 'avgDelaySeconds': round(delay / n) if n else None}
                  for n, on_time, delay in hours]}

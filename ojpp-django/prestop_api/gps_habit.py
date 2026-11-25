"""Which operators and lines normally send live data (spec 2026-11-25 B1, "ghost scheduled buses").

The official timetable lists some buses that do not run: Arriva's A6343 Ljubljana AP → Lesce ŽP is listed every
weekday but ran (with live data) only on 5 and 6 Nov 2026, while Arriva sends live data for nearly every trip of its
other lines. So a trip of an operator that normally sends live data, with none a few minutes after it set off, has
probably not left. Boards keep it, marked `noLiveData` (it may still come), and the map draws no timetable position
for it. Operators and lines that never send live data keep their timetable times and positions as before.

The habit is learned from our own history, the vehicles seen on their trips (VehicleTrip, blocks.py) and the lines'
days with live trips (RouteDay, bus_rollup.py; SŽ's trains are in neither). What counts is how steadily a line's trips
send live data: a start time seen on a line's live days of its kind (weekday, Saturday, Sunday) is seen on nearly all
of them (STEADY) on a line that sends live data for every bus, on only some of them where only some buses have GPS
(Marprom's town lines). So:
- a line live on at least MIN_DAYS of the last DAYS days is expected live when it is steady, never when it is not;
- a line live on fewer days, but at least once in the last LONG days (A6343: 5 and 6 Nov), is expected live when its
  operator is steady over its other lines (Arriva): its quiet days are buses that did not run;
- a line never live in LONG days (LPP's lines copied into the national feed, whose live data comes on LPP's own copy,
  and lines whose buses have no GPS) keeps its timetable times and positions.

`python manage.py gps_habit --measure` reports how many trips the rule would mark on recorded days and how many of
those still showed up later (false marks; they lose the mark as soon as live data arrives).
"""
import logging
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)
DAYS = 14
MIN_DAYS = 5
LONG = 56        # days a line counts as having sent live data before (blocks.KEEP_DAYS)
NEAR = 2 * 3600  # s: a line's day counts against a trip only with another live trip this close to its start
STEADY = 0.85    # share of a line's live days of its kind each of its trips is seen on, on average
GRACE = 5 * 60   # s after a trip's first departure with no live data before it counts as probably not running
TTL = 3600       # s the learned habit is kept in memory
RETRY = 60       # s before trying again after the database could not be read
_memo: dict = {'at': 0.0, 'ttl': 0.0, 'value': None}


def empty() -> dict:
    return {'steady': frozenset(), 'partial': frozenset(), 'rare': frozenset(), 'operators': frozenset()}


def kind(day: date) -> str:
    return {5: 'sa', 6: 'su'}.get(day.weekday(), 'w')


def learn(trips, operator_of: dict, ever, min_days: int = MIN_DAYS) -> dict:
    """The habit from `trips` (route id, service date, scheduled start s) seen live in the last DAYS days,
    `operator_of` {route id: operator id} and the route ids `ever` live in the last LONG days. A trip's start is held
    only against the line's days of its kind with another live trip within NEAR s of it, so hours the collector was
    down (or the line does not run) never count as missing."""
    starts, seen = defaultdict(list), defaultdict(set)
    for route, day, start in trips:
        starts[(route, day)].append(start)
        seen[(route, kind(day), start)].add(day)
    days_of = defaultdict(list)  # (route, kind) -> [(day, sorted starts)]
    for (route, day), s in starts.items():
        days_of[(route, kind(day))].append(sorted(s))
    hit, possible = defaultdict(int), defaultdict(int)
    for (route, k, start), days in seen.items():
        hit[route] += len(days)
        possible[route] += sum(1 for s in days_of[(route, k)]
                               if bisect_right(s, start + NEAR) > bisect_left(s, start - NEAR))
    own = {r for r, n in Counter(route for route, _ in starts).items() if n >= min_days}
    steady = {r for r in own if hit[r] / possible[r] >= STEADY}
    op_hit, op_possible = defaultdict(int), defaultdict(int)
    for route in own:
        if operator_of.get(route):
            op_hit[operator_of[route]] += hit[route]
            op_possible[operator_of[route]] += possible[route]
    operators = {o for o, p in op_possible.items() if op_hit[o] / p >= STEADY}
    return {'steady': frozenset(steady), 'partial': frozenset(own - steady),
            'rare': frozenset((set(ever) | {r for r, _ in starts}) - own), 'operators': frozenset(operators)}


def learn_from_db(today: date, days: int = DAYS) -> dict:
    from prestop_statistics.models import RouteDay, VehicleTrip
    trips = (VehicleTrip.objects.filter(service_date__gte=today - timedelta(days=days), service_date__lt=today)
             .values_list('route_id', 'service_date', 'start').iterator(chunk_size=20000))
    history = (RouteDay.objects.filter(service_date__gte=today - timedelta(days=LONG), service_date__lt=today, trips__gt=0)
               .values_list('route_id', 'operator_id').distinct())
    operator_of = {r: o for r, o in history if o}
    return learn(trips, operator_of, {r for r, _ in history})


def habit(now: Optional[float] = None) -> dict:
    """The learned habit, kept TTL s; empty (everyone keeps timetable positions) while the database cannot be read."""
    now = time.time() if now is None else now
    if _memo['value'] is not None and now - _memo['at'] < _memo['ttl']:
        return _memo['value']
    try:
        value, ttl = learn_from_db(date.fromtimestamp(now)), TTL
    except Exception as error:  # no database (tests, a restore): never let the boards fail over it
        logger.warning('gps_habit: could not learn (%s)', error)
        value, ttl = empty(), RETRY
    _memo.update(at=now, ttl=ttl, value=value)
    return value


def reset() -> None:
    _memo.update(at=0.0, ttl=0.0, value=None)


def expects_live(operator_id: Optional[str], route_id: Optional[str], known: Optional[dict] = None) -> bool:
    known = habit() if known is None else known
    if route_id in known['steady']:
        return True
    return route_id in known['rare'] and operator_id in known['operators']


def no_live_data(operator_id: Optional[str], route_id: Optional[str], first_departure: Optional[float],
                 has_live: bool, now: Optional[float] = None, known: Optional[dict] = None) -> bool:
    """A trip that should have sent live data by now and did not: GRACE s past its first departure, of an operator or
    line that normally sends it. Unknown first departure: never."""
    if has_live or first_departure is None:
        return False
    now = time.time() if now is None else now
    return now >= first_departure + GRACE and expects_live(operator_id, route_id, known)


def measure(today: date, days: int = 7, scheduled=None, grace: int = GRACE) -> dict:
    """What the rule would have done on each of the `days` days before `today`, each with the habit learned from the
    DAYS days before it: `marked` trips listed but never live on lines expected live (scheduled by the timetable minus
    those with live data; `scheduled(route_id)` gives {(date, direction): trips}, views.scheduled_trip_counts),
    `live` trips with GPS on those lines, of them `late` first seen more than `grace` s after their start (marked a
    while, then shown when their data came: the false marks), and the lines most often marked."""
    from zoneinfo import ZoneInfo
    from datetime import datetime, time as clock
    from prestop_statistics.models import RouteDay, VehicleTrip
    tz = ZoneInfo('Europe/Ljubljana')
    trips = list(VehicleTrip.objects.filter(service_date__gte=today - timedelta(days=days + DAYS), service_date__lt=today)
                 .values_list('route_id', 'service_date', 'start', 'first_seen'))
    history = list(RouteDay.objects.filter(service_date__gte=today - timedelta(days=days + LONG), service_date__lt=today,
                                           trips__gt=0).values_list('route_id', 'operator_id', 'service_date'))
    operator_of = {r: o for r, o, _ in history if o}
    out, worst = [], defaultdict(int)
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        known = learn([(r, d, s) for r, d, s, _ in trips if day - timedelta(days=DAYS) <= d < day], operator_of, {r for r, _, d in history if day - timedelta(days=LONG) <= d < day})
        lines = {r for r in known['steady'] | known['rare'] if expects_live(operator_of.get(r), r, known)}
        observed = defaultdict(int)
        for r, d, _, _ in trips:
            observed[r] += d == day
        marked = 0
        for route in sorted(lines) if scheduled else ():
            try:
                listed = sum(n for (d, _), n in scheduled(route).items() if d == day)
            except Exception:  # the timetable service did not answer: that line is left out
                continue
            missing = max(0, listed - observed[route])
            marked += missing
            worst[route] += missing
        midnight = datetime.combine(day, clock(), tz).timestamp()
        live = late = 0
        for r, d, start, seen in trips:
            if d == day and r in lines:
                live += 1
                late += seen.timestamp() > midnight + start + grace
        out.append({'day': day.isoformat(), 'lines': len(lines), 'steady': len(known['steady']),
                    'partial': len(known['partial']), 'operators': len(known['operators']),
                    'marked': marked, 'live': live, 'late': late})
    top = sorted(worst.items(), key=lambda kv: -kv[1])[:10]
    return {'days': out, 'mostMarked': [{'routeId': r, 'trips': n} for r, n in top if n]}


# ---------------------------------------------------------------- listed trips that rarely run (B1 part 5)
# A check after departure comes too late at a trip's first stop (it has left that board), so each listed trip gets a
# run rate learned before it leaves. A slot is operator + line name + direction + day kind + first-stop start (± SLOP),
# never a route or trip id, so a feed renumbering (A6343: IJPP:67295 → IJPP:67714 on 1 Dec) keeps its history. A
# listed day counts only when it is observable: the operator sent live data for other trips within NEAR of the start
# (collector up, operator reporting). Only operators steady over their lines (learn()['operators']) are judged, and
# only slots with MIN_OBSERVABLE observable listed days; LPP's copies in the national feed and lines never live in
# LONG days never are. `GHOST_TRIPS` (settings): hide (the default, measured 11-24 Nov) | mark | off; off changes nothing.
# Hard safety rules (prod sweep 25 Nov: 26 of 31 naive "ghost lines" were real buses without GPS), each never judged:
# (a) a slot not itself seen live in the LONG days (a trip always run by a bus without GPS, e.g. a subcontractor's,
#     however steady its operator); (b) SŽ's replacement buses (operator IJPP:1161, lines "BUS <train no>") and every
#     feed that is not the national one or a live city feed (the hand-kept Ptuj, Postojna, Sevnica, Brežice town feeds
#     are filed under Arriva's and Nomago's ids but never send GPS); (c) LPP's copies in the national feed.
GHOST_DAYS = 28
MIN_OBSERVABLE = 6
GHOST_RATE = 0.05      # run rate at or below: ghost (listed, almost never runs). Prod backtest 25 Nov (11–24 Nov):
#                        0.05 hid 7 slot-days, 0 ran; 0.10 / 0.15 / 0.20 hid 26 / 51 / 82 and 7.7 / 11.8 / 11.0 % ran
#                        (N0138, A6140, N6293, A8530 run on ~1 listed day in 7–10: a rate threshold r hides about r
#                        of runs). A6343 (0.14–0.17) is caught only with its SŽ closure days left out (`closed`).
IRREGULAR_RATE = 0.6   # run rate below: irregular (runs on some listed days)
SLOP = 120             # s: the same slot across days and feed versions
DAY_SHARE = 0.8        # a day counts only if this share of the operator's other listed trips was matched live then
#                        (prod, before 10 Nov: Marprom's live buses were matched to ~10 % of its weekday trips, so
#                        every Marprom slot looked like a ghost; backtest 16 Nov: 489 of 499 hidden ran)
NEVER_JUDGED = ('IJPP:LPP-',)                     # (c)
JUDGED_FEEDS = ('IJPP:', 'LPP:', 'MARPROM:')       # (b) feeds whose buses send live data; any other feed never judged
REPLACEMENT_OPERATORS = frozenset({'IJPP:1161'})   # (b) SŽ: its buses run instead of trains (mapping.REPLACEMENT_AGENCIES)
ROUTE_TRIPS_Q = ('query($id: String!) { route(id: $id) { gtfsId shortName agency { gtfsId } patterns { directionId '
                 'stops { name } trips { activeDates departureStoptime { scheduledDeparture } } } } }')
MAX_CLOSURE = 31  # days: a longer closure ("do 12. decembra", a year of works Divača – Koper) is how the line runs,
#                  not days a ghost may run; leaving it in would excuse every day on its corridor
STOP_SUFFIXES = ('avtobusnapostaja', 'zelezniskapostaja', 'postaja', 'ap', 'zp')


def ghost_mode() -> str:
    from django.conf import settings
    mode = str(getattr(settings, 'GHOST_TRIPS', 'hide')).lower()
    return mode if mode in ('hide', 'mark') else 'off'


def direction_of(value) -> Optional[int]:
    """A slot's direction: 0 or 1, else None. OTP gives a pattern's directionId as an int (-1 when the feed has none:
    the whole IJPP feed) and a trip's as a string (null when the feed has none), so the nightly learn (patterns) and
    the boards and planner (trips) must both go through this, or no verdict is ever found (prod, 25 Nov: A6343)."""
    return {0: 0, 1: 1, '0': 0, '1': 1}.get(value) if isinstance(value, (int, str)) and not isinstance(value, bool) else None


def listing(route: dict) -> list[dict]:
    """The listed trips of an OTP `route` (ROUTE_TRIPS_Q): operator, line name, direction, start s, service dates, and
    `ends` (first and last stop names of the pattern; empty when OTP gave no stops)."""
    from datetime import datetime
    out = []
    for p in route.get('patterns') or []:
        stops = [s.get('name') or '' for s in p.get('stops') or []]
        ends = (stops[0], stops[-1]) if stops else ()
        for t in p.get('trips') or []:
            start = (t.get('departureStoptime') or {}).get('scheduledDeparture')
            if isinstance(start, int):
                out.append({'route': route.get('gtfsId') or '', 'operator': (route.get('agency') or {}).get('gtfsId'),
                            'name': route.get('shortName') or '', 'direction': direction_of(p.get('directionId')), 'start': start,
                            'dates': {datetime.strptime(d, '%Y%m%d').date() for d in t.get('activeDates') or []},
                            'ends': ends})
    return out


def stop_key(name: str) -> str:
    """A bus stop's name as an SŽ station key (`sz.station_key`) without the bus/rail station words:
    'Lesce ŽP' → 'lesce', 'Ljubljana AP' → 'ljubljana', 'Kranj AP' → 'kranj'."""
    from prestop_api import sz
    key = sz.station_key(name)
    for suffix in STOP_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[:-len(suffix)]
    return key


def on_corridor(name: str, keys) -> bool:
    """True when a bus stop is at a station of a closed section (`closures.corridor` keys): the stop's key begins the
    station's ('lesce' ~ 'lescebled', 'ljubljana' ~ 'ljubljana'). Matching too much only shows a ghost as irregular on
    that line's closure days, the safe side."""
    key = stop_key(name)
    return len(key) >= 3 and any(k.startswith(key) for k in keys)


def closure_sections(alerts, trains) -> list[tuple[set, set]]:
    """(station keys of the closed section, its days) per SŽ closure notice (`closures.is_closure`: buses instead of
    trains) of at most MAX_CLOSURE days, the section widened to every station a train passes between its sides
    (`closures.corridor`, so 'Ljubljana - Jesenice' covers Lesce Bled and Kranj)."""
    from datetime import datetime
    from prestop_api import closures
    out = []
    for a in alerts:
        if not closures.is_closure(a):
            continue
        keys = closures.corridor(closures.sides(a), trains)
        days = {datetime.strptime(d, '%Y%m%d').date() for d in closures._days(a)}
        if keys and days and len(days) <= MAX_CLOSURE:
            out.append((keys, days))
    return out


def closed_lines(listed, sections) -> dict:
    """{(operator, line name): days} for learn_slots/verdict's `closed`: the days of every closure whose section holds
    both ends of one of the line's patterns (A6343 Ljubljana AP – Lesce ŽP on SŽ's Ljubljana – Jesenice closure)."""
    out: dict = {}
    for t in listed:
        ends = t.get('ends') or ()
        if len(ends) != 2:
            continue
        for keys, days in sections:
            if on_corridor(ends[0], keys) and on_corridor(ends[1], keys):
                out.setdefault((t['operator'], t['name']), set()).update(days)
    return out


def judgeable(route: str, operator: Optional[str], name: Optional[str]) -> bool:
    """Safety rules (b) and (c): False for a line that must never be judged, whatever its history."""
    return (route.startswith(JUDGED_FEEDS) and not route.startswith(NEVER_JUDGED)
            and operator not in REPLACEMENT_OPERATORS and not (name or '').upper().startswith('BUS '))


def ran_ever(listed, seen: dict, first: date, last: date) -> dict:
    """Safety rule (a): the listed starts seen live on any day first..last (the LONG days), whether or not the
    operator sent anything else then. -> {(operator, name, direction, kind): [start]}"""
    out = defaultdict(list)
    for t in listed:
        for day in t['dates']:
            if first <= day <= last and _near(seen.get((t['route'], day), []), t['start'], SLOP) > 0:
                out[(t['operator'], t['name'], t['direction'], kind(day))].append(t['start'])
    return dict(out)


def _near(starts: list, start: int, span: int) -> int:
    return bisect_right(starts, start + span) - bisect_left(starts, start - span)


def matched(listed, seen: dict, first: date, last: date) -> dict:
    """How much of each operator's listing was matched live per day first..last, over judgeable lines:
    {(operator, day): [seen, listed], (operator, line name, day): [seen, listed]}."""
    out = defaultdict(lambda: [0, 0])
    for t in listed:
        if not judgeable(t['route'], t['operator'], t['name']):
            continue
        for day in t['dates']:
            if first <= day <= last:
                hit = _near(seen.get((t['route'], day), []), t['start'], SLOP) > 0
                for key in ((t['operator'], day), (t['operator'], t['name'], day)):
                    out[key][0] += hit
                    out[key][1] += 1
    return dict(out)


def observed(counts: dict, operator, name, day: date) -> bool:
    """The operator's other lines were matched live on `day` well enough (DAY_SHARE) to hold a missing trip against."""
    op, own = counts.get((operator, day), (0, 0)), counts.get((operator, name, day), (0, 0))
    listed = op[1] - own[1]
    return listed > 0 and (op[0] - own[0]) / listed >= DAY_SHARE


def learn_slots(listed, seen: dict, operator_live: dict, operators, ever, first: date, last: date, counts=None,
                closed: Optional[dict] = None) -> dict:
    """Run counts per slot over the days first..last (inclusive). `listed`: listing() rows; `seen` {(route, day):
    sorted starts live}; `operator_live` {(operator, day): sorted starts live}; `operators`: the steady operators;
    `ever` {(operator, line name)} live in the last LONG days; `counts`: matched() over those days (else worked out);
    `closed` {(operator, line name): days}: days with an SŽ closure on the rail the line follows, left out of its rate
    (A6343 ran on 5–6 Nov only, SŽ's full closure Ljubljana – Jesenice; on other days it never runs).
    -> {(operator, name, direction, kind): [[start, runs, observable days]]}"""
    counts = matched(listed, seen, first, last) if counts is None else counts
    slots = defaultdict(list)
    for t in listed:
        op, route = t['operator'], t['route']
        if op not in operators or not judgeable(route, op, t['name']) or (op, t['name']) not in ever:
            continue
        for day in t['dates']:
            if not first <= day <= last or day in (closed or {}).get((op, t['name']), ()):
                continue
            own = seen.get((route, day), [])
            if _near(operator_live.get((op, day), []), t['start'], NEAR) - _near(own, t['start'], NEAR) <= 0:
                continue  # nothing else of the operator live then: the collector or the operator was down
            if not observed(counts, op, t['name'], day):
                continue  # most of the operator's trips were not matched that day: its data, not its buses
            rows = slots[(op, t['name'], t['direction'], kind(day))]
            row = next((r for r in rows if abs(r[0] - t['start']) <= SLOP), None)
            if row is None:
                row = [t['start'], 0, 0]
                rows.append(row)
            row[1] += _near(own, t['start'], SLOP) > 0
            row[2] += 1
    return dict(slots)


def judge(slots: dict, ran: dict, ghost_rate: float = GHOST_RATE) -> dict:
    """The slots that rarely run: {(operator, name, direction, kind): [(start, 'ghost' | 'irregular', rate, days)]}.
    `ran`: ran_ever() over the LONG days. Safety rule (a): a slot never seen live itself is judged only when its line
    (same key) has slots seen live and every one of them is a ghost (A6343: 4 of its 6 trips ran on 5–6 Nov only, the
    other 2 never; the line does not run). On a line that runs, an unseen slot is a bus without GPS: never judged."""
    out = {}
    for key, rows in slots.items():
        seen, unseen = [], []
        for row in rows:
            (seen if any(abs(s - row[0]) <= SLOP for s in ran.get(key, ())) else unseen).append(row)
        verdicts = []
        for start, runs, days in seen:
            rate = runs / days if days else 1.0
            ok = days >= MIN_OBSERVABLE and rate < IRREGULAR_RATE
            verdicts.append((start, 'ghost' if rate <= ghost_rate else 'irregular', rate, days) if ok else None)
        dead = bool(verdicts) and all(v and v[1] == 'ghost' for v in verdicts)
        for start, runs, days in unseen if dead else ():
            if days >= MIN_OBSERVABLE and runs / days <= ghost_rate:
                verdicts.append((start, 'ghost', runs / days, days))
        if any(verdicts):
            out[key] = [v for v in verdicts if v]
    return out


def verdict(judged: dict, operator: Optional[str], name: Optional[str], direction, start: Optional[int], day: date,
            closed: Optional[dict] = None) -> Optional[str]:
    """'ghost', 'irregular' or None for a listed trip, from its slot on `day`'s kind. On a closure day of its line
    (`closed`, as in learn_slots) a ghost may run, so it is only 'irregular'."""
    if start is None:
        return None
    for s, v, _, _ in judged.get((operator, name or '', direction_of(direction), kind(day)), ()):
        if abs(s - start) <= SLOP:
            return 'irregular' if v == 'ghost' and day in (closed or {}).get((operator, name or ''), ()) else v
    return None


def history(first: date, last: date) -> tuple:
    """From VehicleTrip and RouteDay: (seen, operator_live, operator_of) for the days first..last; operator_of holds
    the routes live in the LONG days to `last`."""
    from prestop_statistics.models import RouteDay, VehicleTrip
    days = RouteDay.objects.filter(service_date__gte=last - timedelta(days=LONG), service_date__lte=last, trips__gt=0)
    operator_of = {r: o for r, o in days.values_list('route_id', 'operator_id').distinct() if o}
    seen, operator_live = defaultdict(list), defaultdict(list)
    for route, day, start in (VehicleTrip.objects.filter(service_date__gte=first, service_date__lte=last)
                              .values_list('route_id', 'service_date', 'start').iterator(chunk_size=20000)):
        seen[(route, day)].append(start)
        if operator_of.get(route):
            operator_live[(operator_of[route], day)].append(start)
    for v in (*seen.values(), *operator_live.values()):
        v.sort()
    return seen, operator_live, operator_of


def backtest(today: date, days: int, listed: list, past=None, ghost_rate: float = GHOST_RATE,
             closed: Optional[dict] = None) -> dict:
    """For each of the `days` days D before `today`, judge from the GHOST_DAYS days before D (no look-ahead) and count
    on D the hidden slot-days (ghosts listed and observable on D) and how many of them ran anyway (false hides).
    `listed`: listing() rows of the lines to judge; `past`: history() (read from the database when None);
    `closed`: as in learn_slots (a closure day of a line is judged with the closure known, as live use would)."""
    seen, operator_live, operator_of = past or history(today - timedelta(days=days + LONG), today - timedelta(days=1))
    ever = {(operator_of[t['route']], t['name']) for t in listed if t['route'] in operator_of}
    counts = matched(listed, seen, today - timedelta(days=days + GHOST_DAYS), today - timedelta(days=1))
    out, ran_on = [], Counter()
    lines = defaultdict(lambda: {'hidden': 0, 'ran': 0, 'rates': [], 'days': set()})
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        first = day - timedelta(days=GHOST_DAYS)
        trips = [(r, d, s) for (r, d), starts in seen.items() if first <= d < day for s in starts]
        ops = learn(trips, operator_of, set(operator_of))['operators']
        ran = ran_ever(listed, seen, day - timedelta(days=LONG), day - timedelta(days=1))
        judged = judge(learn_slots(listed, seen, operator_live, ops, ever, first, day - timedelta(days=1), counts, closed),
                       ran, ghost_rate)
        hidden = ran = irregular = 0
        for key, rows in learn_slots(listed, seen, operator_live, ops, ever, day, day, counts).items():
            for start, runs, _ in rows:
                v = verdict(judged, *key[:3], start, day, closed)
                irregular += v == 'irregular'
                if v == 'ghost':
                    hidden += 1
                    ran += runs > 0
                    line = lines[f'{key[0]} {key[1]}']
                    line['hidden'] += 1
                    line['ran'] += runs > 0
                    line['days'].add(day.isoformat())
                    line['rates'] += [r for s, _, r, _ in judged[key] if abs(s - start) <= SLOP][:1]
                    ran_on[(key, start)] += runs > 0
        out.append({'day': day.isoformat(), 'operators': len(ops), 'hidden': hidden, 'ranAnyway': ran, 'irregular': irregular})
    hidden, ran = sum(d['hidden'] for d in out), sum(d['ranAnyway'] for d in out)
    return {'days': out, 'hidden': hidden, 'ranAnyway': ran, 'falseShare': ran / hidden if hidden else 0.0,
            'hiddenOn2DaysItRan': sum(1 for n in ran_on.values() if n >= 2),
            'lines': sorted(({'line': k, 'hidden': v['hidden'], 'ran': v['ran'], 'days': sorted(v['days']),
                              'rate': sum(v['rates']) / len(v['rates'])} for k, v in lines.items()), key=lambda x: -x['hidden'])}


# Closure days kept (part 6b-3b): SŽ drops a notice from its list once it ends and the server keeps no closure
# history, so `manage gps_habit --learn` (nightly) adds the closures in effect to PRESTOP_GHOST_FILE, kept LONG days.
# SEED_FILE holds the closures of 2–11 and 19–22 Nov read from local copies of SŽ's list and zamudil's daily notices
# (`--seed`), so the first backtests can leave A6343's 5–6 Nov runs out of its rate.
SEED_FILE = 'data/ghost_closures_seed.json'


def _sections_from(body) -> list[tuple[set, set]]:
    out = []
    for s in (body or {}).get('sections') or []:
        try:
            out.append((set(s['keys']), {date.fromisoformat(d) for d in s['days']}))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def merge_sections(*lists, since: Optional[date] = None) -> list[tuple[set, set]]:
    """One (keys, days) per closed section, the days of every list joined; days before `since` dropped."""
    merged: dict = {}
    for sections in lists:
        for keys, days in sections:
            merged.setdefault(frozenset(keys), set()).update(d for d in days if since is None or d >= since)
    return [(set(k), d) for k, d in merged.items() if d]


def load_closures(path: Optional[str] = None) -> list[tuple[set, set]]:
    """The stored closure sections (PRESTOP_GHOST_FILE) and the seed's; [] for any that cannot be read (fail safe:
    no closure days only means a ghost is not excused on them)."""
    import json
    from pathlib import Path
    from django.conf import settings
    out = []
    for p in (Path(__file__).parent / SEED_FILE, path if path is not None else getattr(settings, 'PRESTOP_GHOST_FILE', '')):
        try:
            out.append(_sections_from(json.loads(Path(p).read_text(encoding='utf-8'))) if p else [])
        except (OSError, ValueError):
            out.append([])
    return merge_sections(*out)


def save_closures(sections, path: str, today: date) -> int:
    """Adds `sections` to the file at `path` (days older than LONG dropped), written to a temporary file and then
    moved over the old one. -> the number of sections stored."""
    import json
    import os
    from pathlib import Path
    target = Path(path)
    try:
        old = _sections_from(json.loads(target.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        old = []
    merged = merge_sections(old, sections, since=today - timedelta(days=LONG))
    body = {'savedAt': today.isoformat(), 'sections': sorted(
        ({'keys': sorted(k), 'days': sorted(d.isoformat() for d in days)} for k, days in merged), key=lambda s: s['keys'])}
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.tmp')
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, target)
    return len(merged)


def rail_trains(trips) -> list[dict]:
    """SŽ's trains among a day's timetable trips (as closures.synthesize takes them), for `closures.corridor`."""
    from prestop_api import mapping
    return [t for t in trips if not mapping.is_replacement(t['route'])
            and (t['route'].get('agency') or {}).get('gtfsId') in mapping.REPLACEMENT_AGENCIES]


def notices_from_files(paths) -> list[dict]:
    """Closure alerts from saved copies: SŽ's list (`data/szsite/notices.json`: {'data': [{id, from, to, title, text}]})
    and zamudil's daily notices (`notices-<day>.json`: in effect on its serviceDate, or the days its title gives)."""
    import json
    from pathlib import Path
    from prestop_api import sz_list, zamudil
    out = []
    for p in paths:
        body = json.loads(Path(p).read_text(encoding='utf-8'))
        data = body.get('data')
        if isinstance(data, list):
            out += [sz_list._alert(n, sz_list.spans(n)) for n in data if isinstance(n, dict) and n.get('title')]
            continue
        day = date.fromisoformat((data or {}).get('serviceDate') or '')
        for n in (data or {}).get('notices') or []:
            title = n.get('summary') or ''
            if not title or title.startswith('Povezava'):
                continue
            spans = zamudil.title_spans(title, day) or [(day, day)]
            if not any(a <= day <= b for a, b in spans):
                spans = [(day, day)]
            out.append(sz_list._alert({'id': f'z-{day}-{len(out)}', 'title': title, 'text': ''}, spans))
    return out


# Stored verdicts (part 6c): the nightly `manage gps_habit --learn` judges every slot of the steady operators' lines
# (asking OTP once per line) and writes VERDICT_FILE beside PRESTOP_GHOST_FILE. Requests read only that file, through
# trip_verdict(), the one check every trip list goes through. A verdict the current listing can no longer judge (A6343's
# route id 67295 becomes 67714 on 1 Dec: its old run days leave OTP) is kept up to LONG days, unless the slot now runs.
VERDICT_FILE = 'ghost-trips.json'
STALE = 3   # days: older verdicts hide nothing (fail safe: the nightly learn stopped)
CHECK = 60  # s between looks at the verdict file
_stored = {'at': 0.0, 'mtime': None, 'path': None, 'value': None, 'body': None}


def verdict_path(path: Optional[str] = None) -> str:
    from pathlib import Path
    from django.conf import settings
    base = path if path is not None else getattr(settings, 'PRESTOP_GHOST_FILE', '')
    return str(Path(base).with_name(VERDICT_FILE)) if base else ''


def learn_verdicts(today: date, listed: list, past: tuple, closed: Optional[dict] = None, old: Optional[dict] = None) -> dict:
    """The verdicts for `today`, learned from the GHOST_DAYS days before it as backtest() does, as the stored body:
    {'learnedAt', 'slots': [{operator, name, direction, kind, start, verdict, rate, days, judgedAt}],
    'closed': [{operator, name, days}]} (closure days from yesterday on). `old`: the previous body."""
    seen, operator_live, operator_of = past
    first, last = today - timedelta(days=GHOST_DAYS), today - timedelta(days=1)
    ever = {(operator_of[t['route']], t['name']) for t in listed if t['route'] in operator_of}
    trips = [(r, d, s) for (r, d), starts in seen.items() if first <= d <= last for s in starts]
    ops = learn(trips, operator_of, set(operator_of))['operators']
    slots = learn_slots(listed, seen, operator_live, ops, ever, first, last, None, closed)
    judged = judge(slots, ran_ever(listed, seen, today - timedelta(days=LONG), last))
    rows = {(*key, start): {'verdict': v, 'rate': round(rate, 3), 'days': days, 'judgedAt': today.isoformat()}
            for key, items in judged.items() for start, v, rate, days in items}
    for r in (old or {}).get('slots') or []:
        try:
            key = (r['operator'], r['name'], direction_of(r.get('direction')), r['kind'], int(r['start']))
            at = date.fromisoformat(r['judgedAt'])
        except (KeyError, TypeError, ValueError):
            continue
        if at < today - timedelta(days=LONG) or any(k[:4] == key[:4] and abs(k[4] - key[4]) <= SLOP for k in rows):
            continue
        now = next((x for x in slots.get(key[:4], ()) if abs(x[0] - key[4]) <= SLOP), None)
        if now and now[2] >= MIN_OBSERVABLE and now[1] / now[2] >= IRREGULAR_RATE:
            continue  # judged normal now
        if any((t['operator'], t['name'], t['direction']) == key[:3] and abs(t['start'] - key[4]) <= SLOP
               and any(at < d <= last and kind(d) == key[3] and _near(seen.get((t['route'], d), []), t['start'], SLOP)
                       for d in t['dates']) for t in listed):
            continue  # seen running since it was judged
        rows[key] = {k: r[k] for k in ('verdict', 'rate', 'days', 'judgedAt') if k in r}
    return {'learnedAt': today.isoformat(),
            'slots': [{'operator': k[0], 'name': k[1], 'direction': k[2], 'kind': k[3], 'start': k[4], **v}
                      for k, v in sorted(rows.items(), key=lambda x: tuple(str(p) for p in x[0]))],
            'closed': [{'operator': o, 'name': n, 'days': sorted(d.isoformat() for d in days if d >= last)}
                       for (o, n), days in sorted((closed or {}).items(), key=lambda x: (str(x[0][0]), x[0][1]))
                       if any(d >= last for d in days)]}


def write_json(path: str, body: dict) -> None:
    import json
    import os
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.tmp')
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, target)


def read_verdicts(body: dict, today: date) -> dict:
    """The stored body as {'judged': judge() form, 'closed': closed form, 'learnedAt': date}; nothing judged when it
    is older than STALE days."""
    learned = date.fromisoformat(body['learnedAt'])
    if learned < today - timedelta(days=STALE):
        return {'judged': {}, 'closed': {}, 'learnedAt': learned}
    judged, closed = defaultdict(list), {}
    for r in body.get('slots') or []:
        if r.get('verdict') in ('ghost', 'irregular'):
            judged[(r['operator'], r['name'], direction_of(r.get('direction')), r['kind'])].append(
                (int(r['start']), r['verdict'], r.get('rate'), r.get('days')))
    for r in body.get('closed') or []:
        closed[(r['operator'], r['name'])] = {date.fromisoformat(d) for d in r['days']}
    return {'judged': dict(judged), 'closed': closed, 'learnedAt': learned}


def stored(now: Optional[float] = None, path: Optional[str] = None) -> dict:
    """The stored verdicts, looked at every CHECK s and read again when the file changed; nothing judged when the
    file is missing, unreadable or stale (fail safe: today's behaviour)."""
    import json
    import os
    from pathlib import Path
    now = time.time() if now is None else now
    path = verdict_path() if path is None else path
    if _stored['value'] is not None and _stored['path'] == path and now - _stored['at'] < CHECK:
        return _stored['value']
    try:
        mtime = os.stat(path).st_mtime
        if mtime != _stored['mtime'] or _stored['path'] != path or _stored.get('body') is None:
            _stored['body'] = json.loads(Path(path).read_text(encoding='utf-8'))
        value = read_verdicts(_stored['body'], date.fromtimestamp(now))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        mtime, value = None, {'judged': {}, 'closed': {}, 'learnedAt': None}
        _stored['body'] = None
    _stored.update(at=now, mtime=mtime, path=path, value=value)
    return value


def reset_stored() -> None:
    _stored.update(at=0.0, mtime=None, path=None, value=None, body=None)


def trip_verdict(operator: Optional[str], name: Optional[str], direction, start: Optional[int], day: date,
                 live: bool = False, now: Optional[float] = None) -> Optional[str]:
    """The one check every trip list goes through (B1): 'ghost' (remove it everywhere), 'irregular' (show it, labelled
    "often does not run", ranked last) or None. Live data for the trip (a GTFS-RT update or a vehicle on it) -> None
    at once. GHOST_TRIPS 'mark' shows a ghost as irregular; 'off', or verdicts stale or unreadable -> None.
    `start`: the trip's scheduled departure from its first stop, s after its service day began (OTP's)."""
    mode = ghost_mode()
    if live or mode == 'off' or not isinstance(start, int):
        return None
    known = stored(now)
    v = verdict(known['judged'], operator, name, direction, start, day, known['closed'])
    return 'irregular' if v == 'ghost' and mode == 'mark' else v


def summary(now: Optional[float] = None) -> dict:
    """/health `ghostTrips`: the switch, when the verdicts were learned and how many slots each holds."""
    known = stored(now)
    rows = [v for items in known['judged'].values() for _, v, _, _ in items]
    return {'mode': ghost_mode(), 'learnedAt': known['learnedAt'].isoformat() if known['learnedAt'] else None,
            'ghosts': rows.count('ghost'), 'irregular': rows.count('irregular')}

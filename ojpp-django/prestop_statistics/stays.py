"""Staying on the same vehicle (contract 3) and where each departure's vehicle comes from (contract 2), learned from
the recorder (blocks.record: VehicleTrip version 2, VehicleGap, RecorderDay).

Observations. On every complete day of a feed (the collector polled at least FULL_DAY of it and the feed had vehicles),
each trip a vehicle ran is one observation of its departure: route + scheduled start + stop pattern, so a timetable
change makes a new departure whose history starts afresh. Its origin that day:
- continues: the same vehicle ran another departure that ended at most blocks.MAX_GAP before, and the gap between
  the two shows no fresh start;
- depot: no such trip, or a fresh start: after leaving the terminus the vehicle stood at a learned depot, or it was
  switched off (missing from the feed OFF_POLLS polls, in feeds that otherwise show vehicles between trips);
- unknown: no gap was recorded (the collector restarted in between), so it counts neither way.
Depots are clusters of long idle spots (DEPOT_IDLE) of at least DEPOT_VEHICLES vehicles of one feed.

Levels, per departure and kind of day, from the observations before the day (only the departure's current pattern):
- sure: at least `min_days` observed days, at least SURE_SHARE the same previous departure, and the last `min_days`
  observations agree, so one contradiction ends `sure` until it is earned again. `min_days` starts at SURE_DAYS and
  is raised per feed every night until the backtest over the recorded window has no `sure` miss (SURE_PRECISION,
  up to MAX_SURE_DAYS; a feed that misses even then gets no `sure`);
- likely: at least LIKELY_DAYS days and LIKELY_SHARE;
- otherwise none: a normal change.

Gate: nothing is learned for a feed before it has GATE_DAYS consecutive complete days, so nothing is shown either (no
stays and no delay carried over from the previous trip). Live check: every night yesterday's stays are compared with
what the vehicles did (StayCheck); a feed whose `sure` missed is capped at `likely` for DEMOTE_DAYS. The collector
runs all of it once a night (nightly), after the service day has ended. Rail has no vehicle feed, so no trains.
"""
import logging
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from prestop_statistics import blocks
from prestop_statistics.aggregation import day_kind
from prestop_statistics.models import RecorderDay, StayCheck, StayDeparture, VehicleGap, VehicleTrip

logger = logging.getLogger(__name__)
FULL_DAY = 0.95 * 86400   # s the collector polled for a day to count
FEED_SECONDS = 3600       # s a feed had vehicles in it for its day to count
GATE_DAYS = 7             # consecutive complete days before anything is learned
SURE_DAYS = 4             # floor of `min_days`
MAX_SURE_DAYS = 10
SURE_SHARE = 0.95
SURE_PRECISION = 1.0      # the backtest precision `min_days` must reach for a feed to get `sure`
LIKELY_DAYS = 2
LIKELY_SHARE = 0.7
OFF_POLLS = 5             # polls missing from the feed between two trips: switched off
SEEN_BETWEEN = 0.5        # a feed shows vehicles between trips when this share of its gaps has them
DEPOT_IDLE = 2 * 3600     # s: idle spots this long are where vehicles are parked
DEPOT_METERS = 300
DEPOT_VEHICLES = 2
DEMOTE_DAYS = 7
MIN_DELAYS = 3            # delay samples behind `absorb` and `depot_delay`
NIGHTLY_HOUR = 4.5        # local time the nightly job runs after (service days end at 04:00)
CONTINUES, DEPOT = 'continues', 'depot'
_nightly: dict = {'day': None}


@dataclass
class Obs:
    day: date
    feed: str
    key: tuple                   # (route_id, start, pattern)
    origin: Optional[str]        # CONTINUES, DEPOT or None (unknown)
    prev: Optional[tuple] = None  # the previous departure's key when it continues
    prev_end: Optional[int] = None
    prev_delay: Optional[int] = None
    start_delay: Optional[int] = None

    @property
    def outcome(self):
        return self.prev if self.origin == CONTINUES else self.origin


def _feed(trip_id: str) -> str:
    return trip_id.split(':', 1)[0]


# ---------------------------------------------------------------- the gate

def complete_days(since: date, until: date) -> dict[str, set[date]]:
    """feed -> the days in [since, until] that count: the collector ran at least FULL_DAY and the feed had vehicles."""
    rows = list(RecorderDay.objects.filter(day__range=(since, until), version__gte=blocks.RECORDER_VERSION).values_list('day', 'feed', 'seconds'))
    collector = {d for d, f, s in rows if f == '*' and s >= FULL_DAY}
    out: dict[str, set[date]] = defaultdict(set)
    for d, f, s in rows:
        if f != '*' and d in collector and s >= FEED_SECONDS:
            out[f].add(d)
    return out


def gate_opens(days: set[date]) -> Optional[date]:
    """The day after the first GATE_DAYS consecutive complete days, or None."""
    run, prev = 0, None
    for d in sorted(days):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        prev = d
        if run >= GATE_DAYS:
            return d + timedelta(days=1)
    return None


# ---------------------------------------------------------------- observations

def learn_depots(since: date, until: date) -> dict[str, list[tuple]]:
    """feed -> depot spots (lat, lon): long idle spots where at least DEPOT_VEHICLES of its vehicles were parked."""
    clusters: dict[str, list[dict]] = defaultdict(list)
    for vehicle, idle in VehicleGap.objects.filter(service_date__range=(since, until)).exclude(idle=[]).values_list('vehicle_id', 'idle'):
        for lat, lon, seconds in idle or ():
            if seconds < DEPOT_IDLE:
                continue
            found = next((c for c in clusters[_feed(vehicle)] if blocks._metres((lat, lon), c['at']) <= DEPOT_METERS), None)
            if found:
                found['vehicles'].add(vehicle)
            else:
                clusters[_feed(vehicle)].append({'at': (lat, lon), 'vehicles': {vehicle}})
    return {feed: [c['at'] for c in cs if len(c['vehicles']) >= DEPOT_VEHICLES] for feed, cs in clusters.items()}


def feeds_seen_between(since: date, until: date) -> set[str]:
    """Feeds that show their vehicles between trips (so missing from the feed means switched off)."""
    seen, total = Counter(), Counter()
    for vehicle, polls in VehicleGap.objects.filter(service_date__range=(since, until)).exclude(after_trip_id='').exclude(before_trip_id='') \
            .values_list('vehicle_id', 'seen_polls'):
        total[_feed(vehicle)] += 1
        seen[_feed(vehicle)] += polls > 0
    return {f for f, n in total.items() if seen[f] >= SEEN_BETWEEN * n}


def fresh_start(gap: tuple, depots: list[tuple], shows_between: bool) -> bool:
    """A gap (max_distance, unseen_polls, idle) through a depot, or with the vehicle switched off."""
    far, unseen, idle = gap
    if shows_between and unseen >= OFF_POLLS:
        return True
    return far > blocks.TERMINUS_METERS and any(blocks._metres((lat, lon), d) <= DEPOT_METERS for lat, lon, _ in idle or () for d in depots)


def observations(days: dict[str, set[date]], depots: dict[str, list], between: set[str]) -> list[Obs]:
    """Every recorded departure on the given days of each feed, with its origin that day."""
    out = []
    for day in sorted(set().union(*days.values()) if days else ()):
        runs: dict[str, list[tuple]] = defaultdict(list)
        for row in VehicleTrip.objects.filter(service_date=day, version__gte=blocks.RECORDER_VERSION) \
                .values_list('trip_id', 'vehicle_id', 'route_id', 'start', 'end', 'end_delay', 'start_delay', 'pattern'):
            if day in days.get(_feed(row[0]), ()):
                runs[row[1]].append(row)
        if not runs:
            continue
        gaps = {(v, a, b): (far, unseen, idle) for v, a, b, far, unseen, idle in VehicleGap.objects.filter(service_date=day)
                .values_list('vehicle_id', 'after_trip_id', 'before_trip_id', 'max_distance', 'unseen_polls', 'idle')}
        for vehicle, rows in runs.items():
            for r in rows:
                trip_id, _, route_id, start, _, _, start_delay, pattern = r
                feed = _feed(trip_id)
                before = [o for o in rows if o[0] != trip_id and o[4] <= start and start - o[4] <= blocks.MAX_GAP]
                prev = max(before, key=lambda o: o[4], default=None)
                obs = Obs(day, feed, (route_id, start, pattern), DEPOT, start_delay=start_delay)
                if prev:
                    gap = gaps.get((vehicle, prev[0], trip_id))
                    if gap is None:
                        obs.origin = None
                    elif not fresh_start(gap, depots.get(feed, []), feed in between):
                        obs.origin, obs.prev, obs.prev_end, obs.prev_delay = CONTINUES, (prev[2], prev[3], prev[7]), prev[4], prev[5]
                out.append(obs)
    return out


def histories(obs: list[Obs]) -> dict[tuple, list[Obs]]:
    """(kind, route_id, start) -> its observations, oldest first."""
    out: dict[tuple, list[Obs]] = defaultdict(list)
    for o in sorted(obs, key=lambda o: o.day):
        out[(day_kind(o.day), o.key[0], o.key[1])].append(o)
    return out


# ---------------------------------------------------------------- levels

@dataclass
class Stats:
    pattern: str
    days: int
    top: object = None   # the most common outcome: a previous departure's key, or DEPOT
    share: float = 0.0
    streak: int = 0      # the latest observations agreeing with `top`


def stats(history: list[Obs]) -> Optional[Stats]:
    """The departure's record under its current pattern (the latest observation's)."""
    if not history:
        return None
    pattern = history[-1].key[2]
    known = [o.outcome for o in history if o.key[2] == pattern and o.origin]
    s = Stats(pattern, len(known))
    if known:
        s.top, n = Counter(known).most_common(1)[0]
        s.share = n / len(known)
        for outcome in reversed(known):
            if outcome != s.top:
                break
            s.streak += 1
    return s


def level(s: Optional[Stats], min_days: Optional[int]) -> str:
    """'sure', 'likely' or '' for staying on; `min_days` None: the feed gets no `sure`."""
    if not s or s.top in (None, DEPOT):
        return ''
    if min_days is not None and s.days >= min_days and s.share >= SURE_SHARE and s.streak >= min_days:
        return 'sure'
    return 'likely' if s.days >= LIKELY_DAYS and s.share >= LIKELY_SHARE else ''


def _median(values: list) -> Optional[int]:
    return round(statistics.median(values)) if len(values) >= MIN_DELAYS else None


def model(history: list[Obs], min_days: Optional[int]) -> dict:
    """What StayDeparture stores for one departure."""
    s = stats(history)
    lvl = level(s, min_days)
    current = [o for o in history if o.key[2] == s.pattern]
    origin = CONTINUES if lvl else DEPOT if s.top == DEPOT and s.days >= LIKELY_DAYS and s.share >= LIKELY_SHARE else 'unknown'
    out = {'pattern': s.pattern, 'origin': origin, 'level': lvl, 'days': s.days, 'share': round(s.share, 3),
           'prev_route_id': '', 'prev_start': None, 'prev_pattern': '', 'prev_end': None, 'absorb': None,
           'depot_delay': _median([o.start_delay for o in current if o.origin == DEPOT and o.start_delay is not None])}
    if lvl:
        same = [o for o in current if o.outcome == s.top]
        out.update(prev_route_id=s.top[0], prev_start=s.top[1], prev_pattern=s.top[2], prev_end=round(statistics.median(o.prev_end for o in same)))
        # How much of a late arrival the layover takes up: the previous trip's end delay minus this one's start delay.
        absorbed = _median([o.prev_delay - o.start_delay for o in same if o.prev_delay is not None and o.prev_delay >= 60 and o.start_delay is not None])
        out['absorb'] = max(0, absorbed) if absorbed is not None else None
    return out


# ---------------------------------------------------------------- backtest

def points(groups: dict[tuple, list[Obs]]):
    """For every observation with a known origin: (obs, the record before its day). Each day is predicted only from
    the days before it."""
    for hist in groups.values():
        for i, o in enumerate(hist):
            if o.origin is None:
                continue
            prior = [p for p in hist[:i] if p.day < o.day]
            if prior:
                yield o, stats(prior)


def tune(groups: dict[tuple, list[Obs]]) -> dict[str, Optional[int]]:
    """feed -> the smallest `min_days` whose `sure` reached SURE_PRECISION (never missed) on the recorded window, None
    when none does."""
    by_feed: dict[str, list] = defaultdict(list)
    for o, s in points(groups):
        if s.top not in (None, DEPOT) and s.pattern == o.key[2] and s.share >= SURE_SHARE:
            by_feed[o.feed].append((s, o.outcome == s.top))
    out = {}
    for feed, cases in by_feed.items():
        out[feed] = next((k for k in range(SURE_DAYS, MAX_SURE_DAYS + 1) if _precision([hit for s, hit in cases if level(s, k) == 'sure']) >= SURE_PRECISION), None)
    return out


def _precision(hits: list[bool]) -> float:
    return sum(hits) / len(hits) if hits else 1.0


def backtest(groups: dict[tuple, list[Obs]], opens: dict[str, Optional[date]], min_days: dict[str, Optional[int]]) -> dict:
    """(level, feed, kind) -> {'predicted', 'hits', 'continued'}: precision = hits / predicted, recall = hits /
    continued (observations that did continue). Days before the feed's gate opens get no prediction."""
    out: dict[tuple, dict] = defaultdict(lambda: {'predicted': 0, 'hits': 0, 'continued': 0})
    for o, s in points(groups):
        opened = opens.get(o.feed)
        if not opened or o.day < opened:
            continue
        lvl = level(s, min_days.get(o.feed, SURE_DAYS)) if s.pattern == o.key[2] else ''
        for name in ('sure', 'likely'):
            cell = out[(name, o.feed, day_kind(o.day))]
            cell['continued'] += o.origin == CONTINUES
            if lvl == name:
                cell['predicted'] += 1
                cell['hits'] += o.outcome == s.top
    return dict(out)


# ---------------------------------------------------------------- nightly

def demoted(day: date) -> set[str]:
    """Feeds whose `sure` missed in the live check of the last DEMOTE_DAYS."""
    return set(StayCheck.objects.filter(day__gte=day - timedelta(days=DEMOTE_DAYS), day__lt=day, level='sure', misses__gt=0)
               .values_list('feed', flat=True))


def window(day: date) -> tuple[date, date]:
    return day - timedelta(days=blocks.KEEP_DAYS), day - timedelta(days=1)


def gather(day: date) -> tuple[dict, dict, dict]:
    """(complete days per feed, gate opening per feed, histories) from the window before `day`."""
    since, until = window(day)
    days = complete_days(since, until)
    opens = {feed: gate_opens(d) for feed, d in days.items()}
    obs = observations(days, learn_depots(since, until), feeds_seen_between(since, until))
    return days, opens, histories(obs)


def learn(day: date) -> dict:
    """Relearn every departure of the feeds whose gate is open on `day` into StayDeparture."""
    _, opens, groups = gather(day)
    open_feeds = {f for f, d in opens.items() if d and d <= day}
    min_days = tune(groups)
    capped = demoted(day)
    for feed in capped & open_feeds:
        logger.warning('stays: %s had a wrong "sure" in the last %s days, so it is at most "likely"', feed, DEMOTE_DAYS)
    rows = []
    for (kind, route_id, start), hist in groups.items():
        feed = hist[-1].feed
        if feed not in open_feeds:
            continue
        m = model(hist, None if feed in capped else min_days.get(feed, SURE_DAYS))
        if m['origin'] == 'unknown' and m['depot_delay'] is None:
            continue
        rows.append(StayDeparture(kind=kind, feed=feed, route_id=route_id, start=start, learned_on=day, **m))
    with transaction.atomic():
        StayDeparture.objects.all().delete()
        StayDeparture.objects.bulk_create(rows, batch_size=2000)
    levels = Counter(r.level or r.origin for r in rows)
    return {'feeds': sorted(open_feeds), 'departures': len(rows), **levels, 'minDays': min_days,
            'gate': {f: d.isoformat() if d else None for f, d in opens.items()}}


def check(day: date) -> dict:
    """The live check: the stored stays (learned before `day`) against what the vehicles did on `day` (StayCheck)."""
    stored = {(r.route_id, r.start): r for r in StayDeparture.objects.filter(kind=day_kind(day), learned_on__lte=day).exclude(level='')}
    if not stored:
        return {}
    since, until = window(day + timedelta(days=1))
    feeds = set(RecorderDay.objects.filter(day=day).exclude(feed='*').values_list('feed', flat=True))
    tally: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for o in observations({f: {day} for f in feeds}, learn_depots(since, until), feeds_seen_between(since, until)):
        r = stored.get(o.key[:2])
        if not r or r.pattern != o.key[2] or o.origin is None:
            continue
        hit = o.outcome == (r.prev_route_id, r.prev_start, r.prev_pattern)
        tally[(o.feed, r.level)][0 if hit else 1] += 1
        if not hit and r.level == 'sure':
            logger.warning('stays: "sure" missed on %s: %s %s after %s %s, the vehicle did %s', day, r.route_id, r.start, r.prev_route_id, r.prev_start, o.outcome)
    for (feed, lvl), (hits, misses) in tally.items():
        StayCheck.objects.update_or_create(day=day, feed=feed, level=lvl, defaults={'hits': hits, 'misses': misses})
    return {f'{feed} {lvl}': f'{h}/{h + m}' for (feed, lvl), (h, m) in tally.items()}


def nightly(now: Optional[float] = None) -> Optional[dict]:
    """Once a day, after NIGHTLY_HOUR: check yesterday, then relearn for today. Called on every collector poll."""
    local = datetime.fromtimestamp(now or time.time(), blocks._tz())
    if local.hour + local.minute / 60 < NIGHTLY_HOUR or _nightly['day'] == local.date():
        return None
    today = _nightly['day'] = local.date()
    if StayDeparture.objects.filter(learned_on=today).exists():
        return None  # the collector restarted after tonight's run
    checked = check(today - timedelta(days=1))
    return {'checked': checked, **learn(today)}


# ---------------------------------------------------------------- reading (the web process)

def learned_on() -> Optional[date]:
    return StayDeparture.objects.aggregate(day=Max('learned_on'))['day']


def departures(route_id: str, kind: str) -> dict[int, dict]:
    """start -> the learned departure (StayDeparture's fields) of a route on a kind of day."""
    return {r['start']: r for r in StayDeparture.objects.filter(route_id=route_id, kind=kind).values(
        'start', 'pattern', 'origin', 'level', 'prev_route_id', 'prev_start', 'prev_pattern', 'prev_end', 'absorb', 'depot_delay')}


def run_today(route_id: str, start: int, day: date) -> Optional[dict]:
    """Today's run of a departure: {'tripId', 'vehicleId', 'routeId', 'delaySeconds' (live, or None)}."""
    row = VehicleTrip.objects.filter(route_id=route_id, start=start, service_date=day).order_by('-last_seen').first()
    if not row:
        return None
    fresh = (timezone.now() - row.last_seen).total_seconds() <= blocks.LIVE_AGE
    return {'tripId': row.trip_id, 'vehicleId': row.vehicle_id, 'routeId': row.route_id, 'delaySeconds': row.end_delay if fresh else None}


def trip_pattern(trip_id: str) -> Optional[str]:
    """The stop pattern of a trip in today's timetable (OTP), as the recorder hashes it."""
    import json
    from prestop_api.upstream import otp
    data = otp().query('{ trip(id: %s) { stoptimes { stop { gtfsId } } } }' % json.dumps(trip_id))
    stoptimes = (data.get('trip') or {}).get('stoptimes') or []
    return blocks.hash_stops([(s.get('stop') or {}).get('gtfsId') or '' for s in stoptimes]) if stoptimes else None

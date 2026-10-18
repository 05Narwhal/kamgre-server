"""Learned running and dwell times (spec 2026-10-18 A5): what the map's vehicles and the arrival forecast move by.

Each night (`manage.py learn_times`, started by the collector after NIGHTLY_HOUR under `nice`) the last DAYS days
are read one day at a time: running times between consecutive stops from TripDelay.segments (arrival to arrival,
collector.py), dwells from VehicleTrip.dwell (dwell.py). They are grouped by route, kind of day (workday,
Saturday, Sunday/holiday) and hour band (BANDS, by when the trip runs). A running time keeps its median and
quartiles where it has enough samples (MIN_FINE_SAMPLES for a kind of day or band, MIN_SAMPLES over everything). A
dwell keeps its mean over all trips, those that drove through (0 s) included, and the share that stood: reports come
~30 s apart, so a stand is caught with a chance of about its length / 30 s and then measured as about 30 s
(dwell.py); the mean over all trips is right on average, where a median of the caught ones says 30 s everywhere.
The same is kept per route and kind over all bands, and per route over everything, so a lookup backs off to coarser
data, then to the old 21-day route median (aggregation.typical_segments), then to the timetable. The result
replaces the LearnedTime table.

Medians, not a fitted model: `learn_times --evaluate` compares them on held-out days with the plain route median. A
gradient-boosted model would need a new dependency; with the banded medians not yet beating the plain median on a
week of data (spec 2026-10-18 A5 report), there was nothing for it to win back.
"""
import logging
import statistics
import time
from array import array
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from django.db import transaction

from prestop_statistics.aggregation import day_kind
from prestop_statistics.models import LearnedTime, TripDelay, VehicleTrip

logger = logging.getLogger(__name__)
DAYS = 28
MIN_SAMPLES = 5
# A kind of day or an hour band keeps its own median only with this many samples: on 7 days of data (2026-10-09..15,
# 145k held-out segments) finer medians with fewer samples were worse than the route's (MAE 32.3 vs 32.0 s).
MIN_FINE_SAMPLES = 20
# Hour bands (local start hour, name): the night, the morning peak, the day, the afternoon peak, the evening.
BANDS = ((0, 'night'), (6, 'am'), (9, 'day'), (14, 'pm'), (18, 'eve'))
NIGHTLY_HOUR = 4.75  # local time after which the nightly run starts (after stays.py's)
TIMEOUT = 10 * 60    # s: a nightly run taking longer is stopped
MAX_SEGMENT = 3600
ALL = '*'
_nightly: dict = {'day': None, 'process': None, 'started': 0.0}
_memo: dict = {}
MEMO_TTL = 3600


def band(hour: int) -> str:
    name = BANDS[0][1]
    for start, label in BANDS:
        if hour % 24 >= start:
            name = label
    return name


def _tz():
    from prestop_statistics.collector import LJUBLJANA
    return LJUBLJANA


def _quartiles(values) -> tuple[float, float, float]:
    ordered = sorted(values)
    if len(ordered) < 4:
        mid = statistics.median(ordered)
        return mid, ordered[0], ordered[-1]
    q = statistics.quantiles(ordered, n=4, method='inclusive')
    return q[1], q[0], q[2]


def segment_rows(day: date) -> Iterable[tuple[str, str, dict]]:
    """(route, band, {"from>to": seconds}) for each trip observed on `day` (one day in memory at a time)."""
    tz = _tz()
    rows = TripDelay.objects.filter(service_date=day, canceled=False).exclude(segments={}).only('route_id', 'segments', 'first_seen')
    for row in rows.iterator(chunk_size=2000):
        yield row.route_id, band(row.first_seen.astimezone(tz).hour), row.segments


def dwell_rows(day: date) -> Iterable[tuple[str, str, dict]]:
    """(route, band, {stopId: seconds}) for each trip whose dwells were recorded on `day`."""
    rows = VehicleTrip.objects.filter(service_date=day).exclude(dwell={}).only('route_id', 'start', 'dwell')
    for row in rows.iterator(chunk_size=2000):
        yield row.route_id, band(row.start // 3600), row.dwell


def gather(days: Iterable[date]):
    """Samples per (route, kind, band, key), segments and dwells separately, streamed day by day."""
    segments: dict[tuple, array] = defaultdict(lambda: array('H'))
    dwells: dict[tuple, array] = defaultdict(lambda: array('H'))
    for day in days:
        kind = day_kind(day)
        for route, b, values in segment_rows(day):
            for key, seconds in values.items():
                if 0 < seconds <= MAX_SEGMENT:
                    segments[(route, kind, b, key)].append(int(seconds))
        for route, b, values in dwell_rows(day):
            for stop, seconds in values.items():
                if 0 <= seconds <= MAX_SEGMENT:
                    dwells[(route, kind, b, stop)].append(int(seconds))
    return segments, dwells


def summarize(segments: dict, dwells: dict, learned_on: date) -> list[LearnedTime]:
    """LearnedTime rows: each (route, kind, band) and the coarser (route, kind, *) and (route, *, *) levels."""
    def levels(samples: dict) -> dict[tuple, dict[str, list]]:
        out: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for (route, kind, b, key), values in samples.items():
            for level in ((route, kind, b), (route, kind, ALL), (route, ALL, ALL)):
                out[level][key].append(values)
        return out
    rows: dict[tuple, LearnedTime] = {}
    for level, keys in levels(segments).items():
        learned = {}
        need = MIN_SAMPLES if level[1] == ALL else MIN_FINE_SAMPLES
        for key, parts in keys.items():
            values = [v for part in parts for v in part]
            if len(values) >= need:
                median, q25, q75 = _quartiles(values)
                learned[key] = [round(median, 1), round(q25, 1), round(q75, 1), len(values)]
        if learned:
            rows[level] = LearnedTime(route_id=level[0], kind=level[1], band=level[2], segments=learned, dwells={}, learned_on=learned_on)
    for level, keys in levels(dwells).items():
        learned = {}
        for key, parts in keys.items():
            values = [v for part in parts for v in part]
            if len(values) >= MIN_SAMPLES:
                stood = sum(1 for v in values if v > 0)
                learned[key] = [round(statistics.fmean(values), 1), round(stood / len(values), 3), len(values)]
        if learned:
            row = rows.setdefault(level, LearnedTime(route_id=level[0], kind=level[1], band=level[2], segments={}, dwells={}, learned_on=learned_on))
            row.dwells = learned
    return list(rows.values())


def learn(today: date, days: int = DAYS, exclude: Iterable[date] = ()) -> dict:
    """Relearns the table from the `days` days before `today`; returns counts."""
    started = time.monotonic()
    skip = set(exclude)
    span = [today - timedelta(days=n) for n in range(1, days + 1) if today - timedelta(days=n) not in skip]
    segments, dwells = gather(span)
    rows = summarize(segments, dwells, today)
    with transaction.atomic():
        LearnedTime.objects.all().delete()
        LearnedTime.objects.bulk_create(rows, batch_size=500)
    return {'rows': len(rows), 'segmentKeys': len(segments), 'dwellKeys': len(dwells), 'seconds': round(time.monotonic() - started, 1)}


# ---------------------------------------------------------------- nightly, from the collector

def nightly(now: Optional[float] = None) -> Optional[dict]:
    """Once a day after NIGHTLY_HOUR, starts `manage.py learn_times` as a low-priority process (it must not slow the
    API or the collector's polls) and stops it after TIMEOUT. Called on every collector poll."""
    import subprocess
    import sys
    from pathlib import Path
    now = now or time.time()
    process = _nightly['process']
    if process is not None:
        code = process.poll()
        if code is None and now - _nightly['started'] > TIMEOUT:
            process.kill()
            _nightly['process'] = None
            return {'learnTimes': 'stopped after %d s' % TIMEOUT}
        if code is not None:
            _nightly['process'] = None
            return {'learnTimes': 'done' if code == 0 else f'failed ({code})'}
        return None
    local = datetime.fromtimestamp(now, _tz())
    if local.hour + local.minute / 60 < NIGHTLY_HOUR or _nightly['day'] == local.date():
        return None
    _nightly['day'] = local.date()
    if LearnedTime.objects.filter(learned_on=local.date()).exists():
        return None  # the collector restarted after tonight's run
    _nightly['process'] = subprocess.Popen(['nice', '-n', '10', sys.executable, 'manage.py', 'learn_times'], cwd=str(Path(__file__).resolve().parents[1]))  # where manage.py is
    _nightly['started'] = now
    return {'learnTimes': 'started'}


# ---------------------------------------------------------------- reading (the web process)

def lookup(route_id: str, kind: str, hour: int) -> tuple[dict[str, float], dict[str, list]]:
    """({"from>to": median seconds}, {stopId: [median dwell, share, samples]}) for a route at that kind of day and
    hour, the most specific level first (each level only fills what a finer one lacks). Cached for an hour."""
    key = (route_id, kind, band(hour))
    hit = _memo.get(key)
    if hit and time.monotonic() - hit[0] < MEMO_TTL:
        return hit[1]
    rows = {(r.kind, r.band): r for r in LearnedTime.objects.filter(route_id=route_id).only('kind', 'band', 'segments', 'dwells')}
    segments: dict[str, float] = {}
    dwells: dict[str, list] = {}
    for level in ((ALL, ALL), (kind, ALL), (kind, key[2])):
        row = rows.get(level)
        if row:
            segments.update({k: v[0] for k, v in row.segments.items()})
            dwells.update(row.dwells)
    if len(_memo) > 20_000:
        _memo.clear()
    _memo[key] = (time.monotonic(), (segments, dwells))
    return segments, dwells


DRIVE_THROUGH = 4  # s: a stop whose mean dwell is shorter is usually driven through


def dwell_seconds(learned: Optional[list]) -> Optional[float]:
    """The dwell to draw at a stop: its mean over all trips, or 0 where they usually drive through; None when not
    learned."""
    if not learned:
        return None
    mean = float(learned[0])
    return 0.0 if mean < DRIVE_THROUGH else mean


# ---------------------------------------------------------------- evaluation

def evaluate(today: date, days: int = DAYS, holdout: int = 7) -> dict:
    """Mean absolute error (s) of segment running times on each of the last `holdout` days, learned from the other
    days of the window: the timetable is not stored here, so the comparison is the plain route median over all days
    (what trips carried before) against the banded medians with back-off."""
    window = [today - timedelta(days=n) for n in range(1, days + 1)]
    errors = {'routeMedian': [], 'learned': []}
    for test in window[:holdout]:
        segments, _ = gather(d for d in window if d != test)
        flat: dict[tuple, list] = defaultdict(list)
        for (route, kind, b, key), values in segments.items():
            flat[(route, key)].extend(values)
        rows = summarize(segments, {}, today)
        table = {(r.route_id, r.kind, r.band): r.segments for r in rows}
        kind = day_kind(test)
        for route, b, values in segment_rows(test):
            for key, seconds in values.items():
                if not 0 < seconds <= MAX_SEGMENT:
                    continue
                plain = flat.get((route, key))
                if not plain or len(plain) < MIN_SAMPLES:
                    continue
                guess = None
                for level in ((kind, b), (kind, ALL), (ALL, ALL)):
                    hit = (table.get((route, *level)) or {}).get(key)
                    if hit:
                        guess = hit[0]
                        break
                errors['routeMedian'].append(abs(statistics.median(plain) - seconds))
                errors['learned'].append(abs((guess if guess is not None else statistics.median(plain)) - seconds))
    return {k: {'mae': round(statistics.fmean(v), 1) if v else None, 'n': len(v)} for k, v in errors.items()}

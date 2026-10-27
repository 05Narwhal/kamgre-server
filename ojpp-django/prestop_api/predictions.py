"""Predicted delays of journey legs (contract 2) and staying on the same vehicle (contract 3).

Each transit leg gets `predictedDelaySeconds` and `predictionBasis`, best first:

- `live`: the feed's own estimate for this trip (OTP's realtime times);
- `previous-trip`: the trip hasn't started, but the vehicle that runs it (learned in prestop_statistics.stays) is
  on its previous trip now, late: that delay minus what the layover usually takes up; when the vehicle is still a
  few trips earlier, the delay is carried along its `sure` stays (each layover taking up its share, previous_trip);
- `history`: for a departure whose vehicle comes from the depot, how late it usually starts then; else how late this
  departure usually is on this kind of day (the median of at least 5 trips, aggregation.usual_delays);
- otherwise both are null.

History is read from the database in the background (one worker), so a route seen for the first time doesn't slow the
planner down: its first answer has no history prediction, later ones do. The learned departures are not: the whole
StayDeparture table is held in memory per process (loaded at start and whenever a new learning day appears), and the
stop patterns of the trips come with the plan itself, so the first answer already has its stays.
"""
import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
TTL = 6 * 3600
SERVICE_DAY_ENDS_HOUR = 4
PREVIOUS_AHEAD = 3 * 3600  # s: a previous trip's live delay says something about departures this soon
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='predictions')
_lock = threading.Lock()
_memo: dict = {}      # key -> (monotonic time, value)
_pending: set = set()


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def _background(key: tuple, load: Callable, ttl: float = TTL):
    """The cached value, or None while it is loaded in the background."""
    with _lock:
        hit = _memo.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        if key not in _pending:
            _pending.add(key)
            _pool.submit(_load, key, load)
    return hit[1] if hit else None


def _load(key: tuple, load: Callable):
    try:
        value = load()
    except Exception as e:  # noqa: BLE001 - a prediction is optional
        logger.warning('Prediction data for %s unavailable: %r', key, e)
        value = None
    finally:
        connection.close()
    with _lock:
        _memo[key] = (time.monotonic(), value)
        _pending.discard(key)


def usual(route_id: str, day) -> Optional[dict]:
    from prestop_statistics.aggregation import usual_delays
    return _background(('usual', route_id, day), lambda: usual_delays(route_id, day))


LEARNED_CHECK = 600  # s between looks at whether the server learned a new day
_learned_lock = threading.Lock()
_learned: dict = {'on': None, 'checked': 0.0, 'rows': {}}  # rows: (route_id, kind) -> {start: departure}


def learned_table() -> dict:
    """Every learned departure, (route_id, kind) -> {start: StayDeparture fields}: held per process and reloaded when
    `stays.learned_version()` moves (one aggregate, looked at most every LEARNED_CHECK s). The first caller loads it and
    the others wait for that, so no answer is built without it. A failed read keeps the old table."""
    from prestop_statistics import stays
    if _learned['on'] is not None and time.monotonic() - _learned['checked'] < LEARNED_CHECK:
        return _learned['rows']
    with _learned_lock:
        if _learned['on'] is not None and time.monotonic() - _learned['checked'] < LEARNED_CHECK:
            return _learned['rows']
        try:
            version = stays.learned_version()
            if version != _learned['on']:
                _learned['rows'] = stays.all_departures()
                logger.info('Stays: %s learned departures, learned on %s', sum(len(v) for v in _learned['rows'].values()), version[0])
            _learned['on'], _learned['checked'] = version, time.monotonic()
        except Exception as e:  # noqa: BLE001 - a prediction is optional
            logger.warning('Learned stays unavailable: %r', e)
            _learned['checked'] = time.monotonic() - LEARNED_CHECK + 60  # try again in a minute
    return _learned['rows']


def departure(route_id: str, start: int, day) -> Optional[dict]:
    """What stays.py learned about a departure on `day`'s kind of day (StayDeparture), None while unknown.
    Empty until the feed's 7-full-days gate is open. Relearned every night, so the table follows the learning day."""
    from prestop_statistics.aggregation import day_kind
    return learned_table().get((route_id, day_kind(day)), {}).get(start)


CHAIN_HOPS = 6  # trips back along a vehicle's sure stays to find the one it is running now


def previous_trip(route_id: str, start: int, day, hops: int = CHAIN_HOPS, sure_only: bool = False) -> Optional[dict]:
    """Today's run of the departure this one continues on the same vehicle: {'tripId', 'vehicleId', 'routeId',
    'delaySeconds' (live, or None), 'slack' (s of its delay the layover takes up)}; None for a depot start or unknown.

    When that trip has not started yet, the vehicle is followed further back, but only along `sure` stays (a depot
    start or a `likely` one ends it): the trip it runs now passes its delay on, each layover taking up its usual
    share, and `delaySeconds` is what reaches the end of the trip just before this one."""
    from prestop_statistics import stays
    d = departure(route_id, start, day)
    if not d or d['origin'] != 'continues' or (sure_only and d['level'] != 'sure'):
        return None
    try:
        run = stays.run_today(d['prev_route_id'], d['prev_start'], day)
    except Exception as e:  # noqa: BLE001
        logger.warning('Previous trip of %s unavailable: %r', route_id, e)
        return None
    slack = d['absorb'] if d['absorb'] is not None else start - (d['prev_end'] or start)
    if run:
        return {**run, 'slack': slack}
    if d['level'] != 'sure' or hops <= 1:
        return None
    before = previous_trip(d['prev_route_id'], d['prev_start'], day, hops - 1, sure_only=True)
    if not before or before['delaySeconds'] is None:
        return None
    return {**before, 'delaySeconds': max(0, before['delaySeconds'] - max(0, before['slack'] or 0)), 'slack': slack}


def _hhmm(seconds: int) -> str:
    return f'{seconds // 3600 % 24:02d}:{seconds % 3600 // 60:02d}'


def predict_leg(leg: dict, raw: dict, now: Optional[float] = None) -> tuple[Optional[int], Optional[str]]:
    """(predictedDelaySeconds, predictionBasis) of one transit leg; `raw` is OTP's leg."""
    end_est = (raw['end'].get('estimated') or {}).get('time')
    if end_est:
        return round(_ts(end_est) - _ts(raw['end']['scheduledTime'])), 'live'
    if leg.get('delaySeconds') is not None:
        return leg['delaySeconds'], 'live'
    if not settings.PRESTOP_PREDICTIONS or not leg.get('routeId') or leg.get('canceled'):
        return None, None
    start = ((raw.get('trip') or {}).get('departureStoptime') or {}).get('scheduledDeparture')
    departs = _ts(leg['scheduledDeparture'])
    day = (datetime.fromtimestamp(departs, LOCAL) - timedelta(hours=SERVICE_DAY_ENDS_HOUR)).date()  # after midnight: yesterday's service
    now = now or time.time()
    if start is not None and 0 <= departs - now <= PREVIOUS_AHEAD:
        prev = previous_trip(leg['routeId'], start, day)
        if prev and prev['delaySeconds'] is not None:
            return max(0, prev['delaySeconds'] - max(0, prev['slack'] or 0)), 'previous-trip'
    if start is not None:
        d = departure(leg['routeId'], start, day)
        if d and d['origin'] == 'depot' and d['depot_delay'] is not None:  # a depot start inherits no delay
            return d['depot_delay'], 'history'
        median = (usual(leg['routeId'], day) or {}).get(_hhmm(start))
        if median is not None:
            return round(median), 'history'
    return None, None


def annotate(legs: list[dict], raws: list[Optional[dict]], now: Optional[float] = None) -> None:
    """Contract 2 on every transit leg. `raws[i]`: OTP's leg behind legs[i], None for legs made here (replacement walks
    and buses)."""
    for leg, raw in zip(legs, raws):
        if leg['mode'] == 'walk':
            continue
        delay, basis = predict_leg(leg, raw, now) if raw else ((leg['delaySeconds'], 'live') if leg.get('delaySeconds') is not None else (None, None))
        leg['predictedDelaySeconds'], leg['predictionBasis'] = delay, basis


def transfer_shift(previous: dict, leg: dict) -> int:
    """Seconds a transfer gains (+) or loses (-) from predicted delays beyond the live times already in the effective ones:
    the arriving leg's predicted delay always counts against it; the leaving leg's only when its vehicle is running late
    now (previous-trip): "usually late" is not something to bet a connection on."""
    shift = 0
    if previous.get('predictionBasis') in ('previous-trip', 'history'):
        shift -= max(0, previous.get('predictedDelaySeconds') or 0)
    if leg.get('predictionBasis') == 'previous-trip':
        shift += max(0, leg.get('predictedDelaySeconds') or 0)
    return shift


# ---------------------------------------------------------------- staying on the vehicle (contract 3)

STAY_WALK = 60  # s: more walking than this between two legs is a change of vehicle


def _service_day(ts: float):
    return (datetime.fromtimestamp(ts, LOCAL) - timedelta(hours=SERVICE_DAY_ENDS_HOUR)).date()


PATTERN_TTL = 6 * 3600
PATTERN_WAIT = 1.0  # s all the missing patterns of one answer may take
_patterns: dict = {}   # trip id -> (monotonic time, pattern)
_fetching: dict = {}   # trip id -> Future
_fetch_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='patterns')
rejections: Counter = Counter()  # why a learned stay was not shown, since the process started


def note_pattern(trip_id: str, stop_ids: list[str]) -> None:
    """The stops of a trip as the plan query returned them, so no OTP query per trip is needed to compare them."""
    from prestop_statistics import blocks
    if trip_id and stop_ids:
        _patterns[trip_id] = (time.monotonic(), blocks.hash_stops(stop_ids))


def _fetch_pattern(trip_id: str) -> Optional[str]:
    from prestop_statistics import stays
    try:
        pattern = stays.trip_pattern(trip_id)
    except Exception as e:  # noqa: BLE001
        logger.warning('Stops of %s unavailable: %r', trip_id, e)
        pattern = None
    with _lock:
        _fetching.pop(trip_id, None)
    if pattern:
        _patterns[trip_id] = (time.monotonic(), pattern)
    return pattern


def trip_patterns(trip_ids: list[str]) -> dict[str, Optional[str]]:
    """The stop pattern of each trip: from the plan (note_pattern), else asked of OTP in parallel for at most
    PATTERN_WAIT s in all (only a learned pair gets here). One not known in time stays None, and is kept once it arrives."""
    now = time.monotonic()
    out = {t: _patterns[t][1] if t in _patterns and now - _patterns[t][0] < PATTERN_TTL else None for t in trip_ids}
    missing = [t for t, p in out.items() if p is None]
    if missing:
        with _lock:
            futures = {t: _fetching.get(t) or _fetching.setdefault(t, _fetch_pool.submit(_fetch_pattern, t)) for t in missing}
        deadline = time.monotonic() + PATTERN_WAIT
        for t, f in futures.items():
            try:
                out[t] = f.result(timeout=max(0.0, deadline - time.monotonic()))
            except FutureTimeout:
                pass
    return out


def trip_pattern(trip_id: str) -> Optional[str]:
    return trip_patterns([trip_id])[trip_id]


def _refuse(why: str, leg: dict) -> None:
    rejections[why] += 1
    logger.debug('Stay refused (%s): %s %s', why, leg.get('routeId'), leg.get('tripId'))


def stay_level(previous: dict, previous_meta: dict, leg: dict, meta: dict, walking: float) -> Optional[str]:
    """'sure' or 'likely' when the vehicle of `previous` goes on as `leg`, else None (a normal change).

    Only what the vehicles were seen to do counts (stays.py: per departure and kind of day, after the feed's 7-full-days
    gate); OTP's interline and the feed's block_id never do on their own. Both trips must still have the stops they
    were learned with, and today the vehicles already seen on them must not disagree. Trains: no vehicle data, none."""
    if 'rail' in (previous['mode'], leg['mode']) or walking > STAY_WALK or meta.get('held') or leg.get('replacement') or previous.get('replacement'):
        return None
    if not settings.PRESTOP_PREDICTIONS or meta.get('tripStart') is None or previous_meta.get('tripStart') is None or not leg.get('routeId'):
        return None
    day = _service_day(_ts(leg['scheduledDeparture']))
    d = departure(leg['routeId'], meta['tripStart'], day)
    if not d or not d['level']:
        return None
    if d['prev_route_id'] != previous.get('routeId') or d['prev_start'] != previous_meta['tripStart']:
        _refuse('other-previous-trip', leg)
        return None
    from .sources import stop_group
    end, begin = previous['destination'].get('stopId'), leg['origin'].get('stopId')
    if not end or (end != begin and begin not in stop_group(end)):
        _refuse('stop-group', leg)
        return None
    if not leg.get('tripId') or not previous.get('tripId'):
        _refuse('no-trip', leg)
        return None
    patterns = trip_patterns([leg['tripId'], previous['tripId']])
    if None in patterns.values():
        _refuse('pattern-missing', leg)
        return None
    if patterns[leg['tripId']] != d['pattern'] or patterns[previous['tripId']] != d['prev_pattern']:
        _refuse('pattern-changed', leg)
        return None  # another timetable: not what was learned
    if day == _service_day(time.time()):
        from prestop_statistics import blocks
        try:
            before, after = blocks.vehicle_on(previous['tripId'], day), blocks.vehicle_on(leg['tripId'], day)
        except Exception as e:  # noqa: BLE001
            logger.warning('Vehicles of %s unavailable: %r', leg['tripId'], e)
            before = after = None
        if before and after and before != after:
            _refuse('vehicle-today', leg)
            return None  # today another vehicle runs it
    return d['level']


# The ticket when staying on the same vehicle, by operator:
# - SŽ (IJPP:1161), train to train: a ticket is for a relation, not for one train, so a through train that
#   changes its number needs none (SŽ's conditions of carriage: "vozovnica velja za relacijo"). Trains get no stay
#   level today (no vehicle data), so this waits for that.
# - LPP: a fare paid with Urbana covers every ride within 90 minutes of the first validation, but each boarding is
#   validated (lpp.si, Urbana; visitljubljana.com/en/visitors/travel-information/getting-around/city-buses/: "transfers
#   free of charge within 90 minutes"; n1info.si 2023: the Urbana app counts the 90 minutes down). So nothing to do
#   inside the window, and validate again once it has run out.
# - IJPP intercity buses (Arriva, Nomago, Kranj, ...): single tickets are bought for one trip's relation from the
#   driver or online (gov.si 2026-09-18: enkratne vozovnice IJPP po novem tudi prek spleta); nothing says they carry
#   over to the next trip, even under the same line number (a new trip is a new journey), so a new ticket.
# - Anyone else: unknown, so a new ticket.
NO_NEW_TICKET = {'IJPP:1161'}
LPP_WINDOW = 90 * 60


def is_lpp(leg: dict) -> bool:
    return (leg.get('operatorId') or '').startswith('LPP:')


def ticket_note(previous: dict, leg: dict, lpp_since: Optional[float]) -> str:
    """'none', 'new' or 'revalidate' when staying on; `lpp_since`: when the rider first boarded LPP in this journey."""
    if previous['mode'] == leg['mode'] == 'rail' and previous.get('operatorId') == leg.get('operatorId') in NO_NEW_TICKET:
        return 'none'
    if is_lpp(previous) and is_lpp(leg):
        inside = lpp_since is not None and _ts(leg['effectiveDeparture']) - lpp_since <= LPP_WINDOW
        return 'none' if inside else 'revalidate'
    return 'new'

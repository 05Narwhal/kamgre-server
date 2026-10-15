"""Predicted delays of journey legs (contract 2) and staying on the same vehicle (contract 3).

Each transit leg gets `predictedDelaySeconds` and `predictionBasis`, best first:

- `live`: the feed's own estimate for this trip (OTP's realtime times);
- `previous-trip`: the trip hasn't started, but the vehicle that runs it (learned in prestop_statistics.stays) is
  on its previous trip now, late: that delay minus what the layover usually takes up;
- `history`: for a departure whose vehicle comes from the depot, how late it usually starts then; else how late this
  departure usually is on this kind of day (the median of at least 5 trips, aggregation.usual_delays);
- otherwise both are null.

History and the learned departures are read from the database in the background (one worker), so a route seen for
the first time doesn't slow the planner down: its first answer has no prediction, later ones do.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def departure(route_id: str, start: int, day) -> Optional[dict]:
    """What stays.py learned about a departure on `day`'s kind of day (StayDeparture), None while unknown or loading.
    Empty until the feed's 7-full-days gate is open. Relearned every night, so the cache follows the learning day."""
    from prestop_statistics import stays
    from prestop_statistics.aggregation import day_kind
    learned = _background(('stays-learned',), stays.learned_on, ttl=600)
    if not learned:
        return None
    kind = day_kind(day)
    return (_background(('stays', route_id, kind, learned), lambda: stays.departures(route_id, kind)) or {}).get(start)


def previous_trip(route_id: str, start: int, day) -> Optional[dict]:
    """Today's run of the departure this one continues on the same vehicle: {'tripId', 'vehicleId', 'routeId',
    'delaySeconds' (live, or None), 'slack' (s of its delay the layover takes up)}; None for a depot start or unknown."""
    from prestop_statistics import stays
    d = departure(route_id, start, day)
    if not d or d['origin'] != 'continues':
        return None
    try:
        run = stays.run_today(d['prev_route_id'], d['prev_start'], day)
    except Exception as e:  # noqa: BLE001
        logger.warning('Previous trip of %s unavailable: %r', route_id, e)
        return None
    slack = d['absorb'] if d['absorb'] is not None else start - (d['prev_end'] or start)
    return {**run, 'slack': slack} if run else None


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


def trip_pattern(trip_id: str) -> Optional[str]:
    from prestop_statistics import stays
    return _background(('pattern', trip_id), lambda: stays.trip_pattern(trip_id))


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
    if not d or not d['level'] or d['prev_route_id'] != previous.get('routeId') or d['prev_start'] != previous_meta['tripStart']:
        return None
    from .sources import stop_group
    end, begin = previous['destination'].get('stopId'), leg['origin'].get('stopId')
    if not end or (end != begin and begin not in stop_group(end)):
        return None
    if not leg.get('tripId') or not previous.get('tripId') or trip_pattern(leg['tripId']) != d['pattern'] or trip_pattern(previous['tripId']) != d['prev_pattern']:
        return None  # another timetable (or its stops still loading): not what was learned
    if day == _service_day(time.time()):
        from prestop_statistics import blocks
        try:
            before, after = blocks.vehicle_on(previous['tripId'], day), blocks.vehicle_on(leg['tripId'], day)
        except Exception as e:  # noqa: BLE001
            logger.warning('Vehicles of %s unavailable: %r', leg['tripId'], e)
            before = after = None
        if before and after and before != after:
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

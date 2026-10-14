"""Predicted delays of journey legs (contract 2) and staying on the same vehicle (contract 3).

Each transit leg gets `predictedDelaySeconds` and `predictionBasis`, best first:

- `live`: the feed's own estimate for this trip (OTP's realtime times);
- `previous-trip`: the trip hasn't started, but the vehicle that usually runs it (prestop_statistics.blocks) is
  on its previous trip now, late: that delay minus the layover;
- `history`: how late this departure usually is on this kind of day (the median of at least 5 trips,
  aggregation.usual_delays);
- otherwise both are null.

History and the learned blocks are read from the database in the background (one worker), so a route seen for
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


def _background(key: tuple, load: Callable):
    """The cached value, or None while it is loaded in the background."""
    with _lock:
        hit = _memo.get(key)
        if hit and time.monotonic() - hit[0] < TTL:
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


def blocks_ready() -> bool:
    from prestop_statistics import blocks
    return bool(_background(('blocks-ready',), lambda: blocks.recorded_days() >= blocks.MIN_DAYS))


def previous_trip(route_id: str, start: int, day) -> Optional[dict]:
    """Today's run of the trip before this one on the same vehicle (blocks.previous_run); its learned model loads in the background."""
    from prestop_statistics import blocks
    if not blocks_ready() or _background(('blocks', route_id, day), lambda: blocks.learn(route_id, day)) is None:
        return None
    try:
        return blocks.previous_run(route_id, start, day)
    except Exception as e:  # noqa: BLE001
        logger.warning('Previous trip of %s unavailable: %r', route_id, e)
        return None


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

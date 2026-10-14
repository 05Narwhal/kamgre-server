"""Warnings for a watched journey beyond its first departure (watcher.tick): a ride expected late, a change at
risk, a disruption on the way.

The app watches a journey by its trips (in order) and the stop of its first ride, so the rides are rebuilt here:
each change is where the next trip comes closest to the one before (the same stop, or stops within CHANGE_METERS)
after the earlier one arrives. A ride's expected delay is the live one, else how late its departure usually is
(prestop_statistics.aggregation.usual_delays). What was true at the first look is only recorded: the rider saw it in
the app. After that a message goes out when a ride becomes at least LATE late (or its delay changes by MIN_CHANGE),
when a change drops under RISKY spare time, or when a new alert concerns a ride's route or stops; watcher.py sends at
most one per journey per JOURNEY_GAP.
"""
import logging
import math
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
CHANGE_METERS = 400
LATE = 180
MIN_CHANGE = 120
RISKY = 120
USUAL_TTL = 3600
_usual: dict = {}
TEXT = {
    'sl': {'late': '{route} predvidoma zamuja {minutes} min ({stop} {at})', 'risk': 'Prestop na {stop} je negotov: le {spare} za prestop na {route}',
           'missed': 'Prestop na {stop} verjetno ne bo uspel: {route} odpelje prej, kot prispete', 'alert': 'Motnja na poti: {title}',
           'minutes': '{} min', 'none': 'nič časa'},
    'en': {'late': '{route} is expected {minutes} min late ({stop} {at})', 'risk': 'Your change at {stop} is at risk: only {spare} to catch {route}',
           'missed': "You'll probably miss your change at {stop}: {route} leaves before you arrive", 'alert': 'Disruption on your way: {title}',
           'minutes': '{} min', 'none': 'no time'},
}


def _ts(value: Optional[str]) -> Optional[float]:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() if value else None


def _meters(a: dict, b: dict) -> float:
    kx = 111_320 * math.cos(math.radians(a.get('latitude') or 0))
    return math.hypot(((a.get('longitude') or 0) - (b.get('longitude') or 0)) * kx, ((a.get('latitude') or 0) - (b.get('latitude') or 0)) * 110_574)


def rides(trip_ids: list[str], first_stop: str, trips: dict) -> list[dict]:
    """[{'trip', 'board', 'alight'}] (stop indexes; alight None for the last ride) for the watched trips we know."""
    known = [trips[t] for t in trip_ids if t in trips and trips[t].get('stops')]
    out = []
    for n, trip in enumerate(known):
        stops = trip['stops']
        if n == 0:
            board = next((i for i, s in enumerate(stops) if s['stopId'] == first_stop), 0)
        else:
            prev = out[-1]
            best = None
            for i, a in enumerate(known[n - 1]['stops'][prev['board'] + 1:], start=prev['board'] + 1):
                arrives = _ts(a.get('scheduledArrival'))
                for j, b in enumerate(stops):
                    leaves = _ts(b.get('scheduledDeparture'))
                    if arrives is None or leaves is None or leaves < arrives - 60:
                        continue
                    if a['stopId'] != b['stopId'] and _meters(a, b) > CHANGE_METERS:
                        continue
                    gap = (leaves - arrives, _meters(a, b))
                    if best is None or gap < best[0]:
                        best = (gap, i, j)
            if not best:
                break  # can't tell where the change is: stop here
            prev['alight'], board = best[1], best[2]
        out.append({'trip': trip, 'board': board, 'alight': None})
    return out


def _usual_delay(trip: dict) -> Optional[int]:
    """How late this departure usually is (median on this kind of day), from the statistics."""
    from prestop_statistics.aggregation import usual_delays
    first = _ts(trip['stops'][0].get('scheduledDeparture'))
    if not first or not trip.get('routeId'):
        return None
    local = datetime.fromtimestamp(first, LOCAL)
    key = (trip['routeId'], local.date())
    hit = _usual.get(key)
    if not hit or time.monotonic() - hit[0] > USUAL_TTL:
        try:
            hit = (time.monotonic(), usual_delays(trip['routeId'], local.date()))
        except Exception as e:  # noqa: BLE001 - a prediction is optional
            logger.warning('Usual delays of %s unavailable: %r', trip['routeId'], e)
            hit = (time.monotonic(), {})
        _usual[key] = hit
    median = hit[1].get(local.strftime('%H:%M'))
    return round(median) if median is not None else None


def delay_at(trip: dict, stop: dict, arrival: bool) -> tuple[Optional[int], bool]:
    """(expected delay in s at the stop, live)."""
    planned = _ts(stop.get('scheduledArrival' if arrival else 'scheduledDeparture'))
    actual = _ts(stop.get('effectiveArrival' if arrival else 'effectiveDeparture'))
    if planned is not None and actual is not None:
        return round(actual - planned), True
    return _usual_delay(trip), False


def state(watch, trips: dict, alerts: list[dict], now: float) -> dict:
    """{'late': {tripId: delay}, 'changes': {index: spare s}, 'alerts': [ids], 'where': {...names for the texts}}."""
    built = rides(watch.trip_ids, watch.stop_id, trips)
    late, changes, where = {}, {}, {}
    for n, ride in enumerate(built):
        trip, stops = ride['trip'], ride['trip']['stops']
        board = stops[ride['board']]
        delay, _ = delay_at(trip, board, arrival=False)
        # The first ride's departure has its own updates (watcher._change); later rides until they leave.
        if n and delay is not None and (_ts(board.get('scheduledDeparture')) or 0) + max(0, delay) > now:
            late[trip['id']] = delay
            where[trip['id']] = {'route': trip.get('routeName') or '?', 'stop': board.get('name') or '',
                                 'at': datetime.fromtimestamp(_ts(board['scheduledDeparture']), LOCAL).strftime('%H:%M')}
        if n + 1 < len(built) and ride['alight'] is not None:
            nxt = built[n + 1]
            alight, boards = stops[ride['alight']], nxt['trip']['stops'][nxt['board']]
            arrive, _ = delay_at(trip, alight, arrival=True)
            leave, live = delay_at(nxt['trip'], boards, arrival=False)
            # Only a delay the next vehicle has now helps: "usually late" is no bet for the one to catch.
            spare = (_ts(boards['scheduledDeparture']) + (leave if live and leave else 0)) - (_ts(alight['scheduledArrival']) + max(0, arrive or 0))
            if _ts(alight['scheduledArrival']) + max(0, arrive or 0) > now - 60:
                changes[str(n)] = round(spare)
                where[str(n)] = {'route': nxt['trip'].get('routeName') or '?', 'stop': boards.get('name') or alight.get('name') or ''}
    routes = {r['trip'].get('routeId') for r in built}
    stop_ids = {s['stopId'] for r in built for s in r['trip']['stops'][r['board']:(r['alight'] + 1 if r['alight'] is not None else None)]}
    first = min((_ts(r['trip']['stops'][r['board']].get('scheduledDeparture')) or now for r in built), default=now)
    last = max((_ts(r['trip']['stops'][-1].get('scheduledArrival')) or now for r in built), default=now)
    hits = [a for a in alerts if (set(a.get('routeIds') or []) & routes or set(a.get('stopIds') or []) & stop_ids)
            and a['_from'] <= last and (a.get('_to') is None or a['_to'] >= first)]
    where.update({a['id']: {'title': a['title']} for a in hits})
    return {'late': late, 'changes': changes, 'alerts': sorted(a['id'] for a in hits), 'where': where}


def news(before: dict, now_state: dict, language: str) -> Optional[tuple[str, bool, tuple]]:
    """(message, alert again, what it tells) for the worst news since the rider was last told; None for nothing new."""
    text = TEXT.get(language, TEXT['sl'])
    where = now_state['where']
    for key, spare in now_state['changes'].items():
        told = before.get('changes', {}).get(key)
        if spare < RISKY and (told is None or told >= RISKY or abs(spare - told) >= MIN_CHANGE):
            w = where[key]
            if spare < 0:
                return text['missed'].format(**w), True, ('changes', key, spare)
            gap = text['minutes'].format(round(spare / 60)) if spare >= 60 else text['none']
            return text['risk'].format(spare=gap, **w), True, ('changes', key, spare)
    new_alerts = [a for a in now_state['alerts'] if a not in before.get('alerts', [])]
    if new_alerts:
        return text['alert'].format(**where[new_alerts[0]]), True, ('alerts', new_alerts[0], None)
    for trip_id, delay in now_state['late'].items():
        told = before.get('late', {}).get(trip_id)
        if delay >= LATE and (told is None or abs(delay - told) >= MIN_CHANGE):
            return text['late'].format(minutes=round(delay / 60), **where[trip_id]), False, ('late', trip_id, delay)
    return None


def baseline(now_state: dict) -> dict:
    """The first look: everything as it stands counts as known."""
    return {'seen': True, 'late': now_state['late'], 'changes': now_state['changes'], 'alerts': now_state['alerts']}


def told(before: dict, what: tuple) -> dict:
    field, key, value = what
    out = {**before, 'late': dict(before.get('late', {})), 'changes': dict(before.get('changes', {})), 'alerts': list(before.get('alerts', []))}
    if field == 'alerts':
        out['alerts'].append(key)
    else:
        out[field][key] = value
    return out

"""Journeys ride the replacement bus, not the closed railway.

OTP (the public derp-si server) plans with the feed's trains. Where a bus replaces a train on a
stretch that day (a real "BUS 18969" the feed keeps the whole train beside, or a synthetic bus
from an SŽ notice, see closures.py), a planned train leg over that stretch is split: the train up
to the stretch, the bus along it (between its replacement stops, on the roads, with its own line
and trip), the train after it. A synthetic bus keeps the train's times, so the journey still holds;
a real bus has its own, and a leg whose bus would not connect is left as planned (its notice says
why). The walks between a station and its replacement stop are added afterwards
(journeys.replacement_walks). Which stretches count is decided per service day
(scheduled.day_plan), so a closure that ends on the 11th leaves the 12th's journeys alone.
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import closures, geometry, leg_alerts, mapping, sz
from . import replacement as replaced_by

PlanFor = Callable[[float], Optional[dict]]


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _stamp(epoch: float, like: str) -> str:
    """`epoch` written in the offset of `like` (OTP's local times, e.g. +02:00)."""
    offset = datetime.fromisoformat(like).utcoffset() or timedelta(0)
    return datetime.fromtimestamp(round(epoch), timezone(offset)).isoformat()


def _index(stops: list[dict], place: dict, after: int = -1) -> Optional[int]:
    """Where a leg's end is in a train's stops: by stop id, else by station name."""
    for i, s in enumerate(stops):
        if i > after and place.get('stopId') and s.get('gtfsId') == place['stopId']:
            return i
    key = sz.station_key(place.get('name') or '')
    for i, s in enumerate(stops):
        if i > after and key and sz.station_key(s.get('name') or '') == key:
            return i
    return None


def _place(stop: dict) -> dict:
    """A station as a leg end."""
    place = {'name': stop.get('name') or 'Station', 'latitude': stop['lat'], 'longitude': stop['lon'], 'kind': 'station'}
    if stop.get('gtfsId'):
        place['stopId'] = place['id'] = stop['gtfsId']
    return place


def _cut(coords: list, stops: list[dict]) -> list:
    """The part of a leg's line between two stops (projected onto it)."""
    if len(coords) < 2:
        return [[s['lon'], s['lat']] for s in stops]
    cum = geometry.cumulative(coords)
    a, b = geometry.stop_distances(coords, stops)
    part = geometry.slice_between(coords, cum, a, b) if b > a else []
    return part if len(part) >= 2 else [[s['lon'], s['lat']] for s in stops]


def _train_piece(leg: dict, train: dict, a: int, b: int, suffix: str) -> dict:
    stops = train['stops']
    dep, arr = train['departures'][a], train['arrivals'][b]
    sched_dep = (train.get('scheduledDepartures') or train['departures'])[a]
    sched_arr = (train.get('scheduledArrivals') or train['arrivals'])[b]
    like = leg['scheduledDeparture']
    return {
        **leg, 'id': f'{leg["id"]}-{suffix}',
        'origin': leg['origin'] if a == _index(stops, leg['origin']) else _place(stops[a]),
        'destination': leg['destination'] if b == _index(stops, leg['destination'], a) else _place(stops[b]),
        'scheduledDeparture': _stamp(sched_dep, like), 'scheduledArrival': _stamp(sched_arr, like),
        'effectiveDeparture': _stamp(dep, like), 'effectiveArrival': _stamp(arr, like),
        'geometry': _cut(leg['geometry'], [stops[a], stops[b]]), 'stopCount': b - a,
        'delaySeconds': round(dep - sched_dep) if train['delays'][a] is not None else leg.get('delaySeconds'),
    }


def _bus_piece(leg: dict, bus: dict, train: dict, a: int, b: int, road: Callable[[list[dict]], Optional[dict]], suffix: str) -> Optional[dict]:
    """The bus between the train's stops `a` and `b`, or None when the bus does not call at both."""
    keys = [sz.station_key(s.get('name') or '') for s in bus['stops']]
    first, last = (sz.station_key(train['stops'][i].get('name') or '') for i in (a, b))
    ka = keys.index(first) if first in keys else None
    kb = keys.index(last, ka or 0) if ka is not None and last in keys[ka:] else None
    if ka is None or kb is None or kb <= ka:
        return None
    # Where the bus really stops (beside the station, a bus station bay): real buses are listed at the station.
    stops = bus['stops'] if bus.get('synthetic') else closures.relocate(bus['stops'])
    part = stops[ka:kb + 1]
    shape = road(part)
    line = shape['coords'] if shape else [[s['lon'], s['lat']] for s in part]
    sched_dep = (bus.get('scheduledDepartures') or bus['departures'])[ka]
    sched_arr = (bus.get('scheduledArrivals') or bus['arrivals'])[kb]
    like = leg['scheduledDeparture']
    return {
        **leg, 'id': f'{leg["id"]}-{suffix}', 'mode': 'bus', 'routeId': bus['route']['gtfsId'], 'tripId': bus['id'],
        'routeName': mapping.route_name(bus['route']) or leg['routeName'], 'headsign': stops[kb].get('name') or bus.get('headsign'),
        'origin': _place(train['stops'][a]), 'destination': _place(train['stops'][b]),
        'scheduledDeparture': _stamp(sched_dep, like), 'scheduledArrival': _stamp(sched_arr, like),
        'effectiveDeparture': _stamp(bus['departures'][ka], like), 'effectiveArrival': _stamp(bus['arrivals'][kb], like),
        'geometry': line, 'stopCount': kb - ka, 'delaySeconds': None, 'delayProvenance': None,
        'replacement': True, 'replacesTrain': leg['routeName'],
        # Read by journeys.replacement_walks, then dropped: where the bus stops beside each station.
        '_boardAt': part[0], '_alightAt': part[-1],
    }


def rewrite(legs: list[dict], meta: list[dict], plan_for: PlanFor, road: Callable[[list[dict]], Optional[dict]]) -> tuple[list[dict], list[dict]]:
    """Train legs over a replaced stretch, split into train, bus and train (see the module notes)."""
    out, out_meta = [], []
    for n, (leg, m) in enumerate(zip(legs, meta)):
        pieces = _split(leg, m, plan_for, road) if leg['mode'] == 'rail' and leg.get('tripId') else None
        if not pieces or not _connects(pieces, legs[n - 1] if n else None, legs[n + 1] if n + 1 < len(legs) else None):
            out.append(leg)
            out_meta.append(m)
            continue
        for k, piece in enumerate(pieces):
            out.append(piece)
            # A held change: SŽ holds the bus for the train and the train for the bus (rated, not counted; build_journeys).
            out_meta.append({**m, 'held': k > 0,
                             'duration': _ts(piece['effectiveArrival']) - _ts(piece['effectiveDeparture']),
                             'platform': m['platform'] if k == 0 else None})
    return out, out_meta


def _connects(pieces: list[dict], before: Optional[dict], after: Optional[dict]) -> bool:
    """The pieces run in order and still meet the legs around them (a real bus has its own times)."""
    ends = [(_ts(p['effectiveDeparture']), _ts(p['effectiveArrival'])) for p in pieces]
    in_order = all(d <= a for d, a in ends) and all(ends[i][1] <= ends[i + 1][0] + 60 for i in range(len(ends) - 1))
    first_ok = before is None or before['mode'] == 'walk' or _ts(before['effectiveArrival']) <= ends[0][0]
    last_ok = after is None or after['mode'] == 'walk' or ends[-1][1] <= _ts(after['effectiveDeparture'])
    return in_order and first_ok and last_ok


def _split(leg: dict, m: dict, plan_for: PlanFor, road) -> Optional[list[dict]]:
    when = _ts(leg['scheduledDeparture'])
    plan = plan_for(when)
    trip_sections = (plan or {}).get('sections', {}).get(leg['tripId'])
    if not trip_sections:
        return None
    train = replaced_by.run_near(plan, leg['tripId'], when)
    if not train:
        return None
    start = _index(train['stops'], leg['origin'])
    end = _index(train['stops'], leg['destination'], start if start is not None else -1)
    if start is None or end is None:
        return None
    # The day's stretches this ride crosses, in order.
    crossed = sorted((s for s in trip_sections if s['fromIndex'] is not None and s['toIndex'] is not None
                      and s['fromIndex'] < end and s['toIndex'] > start
                      and abs(s['start'] - train['departures'][max(s['fromIndex'], start)]) <= replaced_by.MATCH_WINDOW),
                     key=lambda s: s['fromIndex'])
    if not crossed:
        return None
    pieces, at = [], start
    for s in crossed:
        a, b = max(s['fromIndex'], at), min(s['toIndex'], end)
        if a >= b:
            continue
        bus = plan['by_id'].get(s['busTripId']) or replaced_by.run_near(plan, s['busTripId'], s['start'])
        piece = _bus_piece(leg, bus, train, a, b, road, f'bus{len(pieces)}') if bus else None
        if not piece:
            return None
        if a > at:
            pieces.append(_train_piece(leg, train, at, a, f't{len(pieces)}'))
        pieces.append(piece)
        at = b
    if not pieces:
        return None
    if at < end:
        pieces.append(_train_piece(leg, train, at, end, f't{len(pieces)}'))
    return pieces


def unreplaced_notices(legs: list[dict], plan_for: PlanFor, alerts: dict[str, dict]) -> None:
    """A train leg that the day's plan does not replace runs as a train, so an SŽ "buses replace trains"
    notice for its section concerns other trains: drop it from the leg when that day has replacement buses
    on the section (ICS 20 runs Ljubljana – Celje while buses replace ICS 14, 17, 31 and 36 there). It stays
    when no bus is known on the section (which trains it means is unknown) and on a train that is replaced
    but whose bus could not be joined to the journey (the notice says why). `alerts`: by id."""
    for leg in legs:
        if leg['mode'] != 'rail' or leg.get('replacement') or not leg.get('tripId'):
            continue
        notices = [i for i in leg['alertIds'] if (alerts.get(i) or {}).get('kind') == 'replacement']
        if not notices:
            continue
        plan = plan_for(_ts(leg['scheduledDeparture']))
        if not plan or (plan.get('sections') or {}).get(leg['tripId']):
            continue
        buses = _bus_stations(plan)
        leg['alertIds'] = [i for i in leg['alertIds'] if i not in notices or not _has_buses(alerts[i], buses)]


def _on_plan(plan: dict, key: str, build: Callable[[], object]):
    """A value derived from a day's plan, kept on it until the plan is rebuilt (its trips change)."""
    kept = plan.get(key)
    if not kept or kept[0] is not plan.get('trips'):
        kept = plan[key] = (plan.get('trips'), build())
    return kept[1]


def _bus_stations(plan: dict) -> list[set[str]]:
    """The (folded) station names of every replacement bus in a day's plan, real and synthetic."""
    def build():
        buses = [t for runs in (plan.get('trips') or {}).values() for t in runs if mapping.is_replacement(t['route'])]
        return [{mapping.fold(s.get('name') or '') for s in bus['stops']} for bus in buses + list(plan.get('synthetic') or [])]
    return _on_plan(plan, '_busStations', build)


def name_replaced_trains(legs: list[dict], plan_for: PlanFor) -> None:
    """A feed's own replacement bus ridden as OTP planned it (BUS 14006 Ljubljana – Celje) says which train it
    runs instead of ("Instead of train ICS 14"), as the buses journey_legs puts in do."""
    for leg in legs:
        if not leg.get('replacement') or leg.get('replacesTrain') or not leg.get('tripId'):
            continue
        plan = plan_for(_ts(leg['scheduledDeparture']))
        name = _trains_by_bus(plan).get(leg['tripId']) if plan else None
        if name:
            leg['replacesTrain'] = name


def _trains_by_bus(plan: dict) -> dict[str, str]:
    def build():
        out: dict[str, str] = {}
        for train_id, found in (plan.get('sections') or {}).items():
            runs = (plan.get('trips') or {}).get(train_id) or []
            for s in found if runs else []:
                out.setdefault(s['busTripId'], mapping.route_name(runs[0]['route']) or '')
        return out
    return _on_plan(plan, '_trainsByBus', build)


def _has_buses(alert: dict, buses: list[set[str]]) -> bool:
    sides = leg_alerts.title_sections(alert['title'])
    return len(sides) >= 2 and any(sum(1 for side in sides if side & names) >= 2 for names in buses)

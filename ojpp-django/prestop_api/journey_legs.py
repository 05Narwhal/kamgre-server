"""Journeys ride the replacement bus, not the closed railway.

OTP (the public derp-si server) plans with the feed's trains. Where a bus replaces a train on a
stretch that day (a real "BUS 18969" the feed keeps the whole train beside, or a synthetic bus
from an SŽ notice, see closures.py), a planned train leg over that stretch is split: the train up
to the stretch, the bus along it (between its replacement stops, on the roads, with its own line
and trip), the train after it. A synthetic bus keeps the train's times, so the journey still holds;
a real bus has its own, and a journey whose bus would not connect is dropped: it is never offered by the train
(replaced). The walks between a station and its replacement stop are added afterwards
(journeys.replacement_walks). Which stretches count is decided per service day
(scheduled.day_plan) and read where the line view reads them (replacement.stretches), so a closure that ends on
the 11th leaves the 12th's journeys alone, and a train the line view shows as its bus is never ridden.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import closures, geometry, leg_alerts, mapping, stopfix, sz, trainlive
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
    place = {'name': stopfix.renamed(stop.get('gtfsId'), stop.get('name') or 'Station'), 'latitude': stop['lat'], 'longitude': stop['lon'], 'kind': 'station'}
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


def _own_bay(piece: dict, stop: dict) -> dict:
    """A replacement bus has no railway track. The piece is cut from the train's leg, so it inherited that leg's
    platform (a track predicted from the train number, tracks.py): drop it, and keep only the bay of a bus station the
    bus leaves from, when the stop has one (platforms.place)."""
    piece.pop('platform', None)
    piece.pop('platformUsual', None)
    if stop.get('bay'):
        piece['platform'] = stop['bay']
        if stop.get('bayUsual'):
            piece['platformUsual'] = True
    return piece


def _bus_piece(leg: dict, bus: dict, train: dict, a: int, b: int, road: Callable[[list[dict]], Optional[dict]], suffix: str,
               plan: Optional[dict] = None) -> Optional[dict]:
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
    piece = {
        **leg, 'id': f'{leg["id"]}-{suffix}', 'mode': 'bus', 'routeId': bus['route']['gtfsId'], 'tripId': bus['id'],
        'routeName': mapping.route_name(bus['route']) or leg['routeName'], 'headsign': stops[kb].get('name') or bus.get('headsign'),
        'origin': _place(train['stops'][a]), 'destination': _place(train['stops'][b]),
        'scheduledDeparture': _stamp(sched_dep, like), 'scheduledArrival': _stamp(sched_arr, like),
        'effectiveDeparture': _stamp(bus['departures'][ka], like), 'effectiveArrival': _stamp(bus['arrivals'][kb], like),
        'geometry': line, 'stopCount': kb - ka, 'delaySeconds': None, 'delayProvenance': None,
        'replacement': True, 'replacesTrain': leg['routeName'],
        # Read by journeys.replacement_walks, then dropped: where the bus stops beside each station.
        '_boardAt': part[0], '_alightAt': part[-1],
        **_live(plan, bus, ka, kb, like),
    }
    return _own_bay(piece, part[0])


def _live(plan: Optional[dict], bus: dict, p: int, q: int, like: str) -> dict:
    """A bus piece's live times (trainlive.py), as {'_live': {...}} for rewrite to put on once the journey is decided
    on the timetable (a late bus must not make a change SŽ holds look missed), or {}."""
    live = trainlive.live_bus(plan, bus) if plan else None
    delay = next((d for d in (live['delays'][p], live['delays'][q]) if d is not None), None) if live else None
    if delay is None:
        return {}
    return {'_live': {'effectiveDeparture': _stamp(live['departures'][p], like), 'effectiveArrival': _stamp(live['arrivals'][q], like),
                      'delaySeconds': delay, 'delayProvenance': 'predicted'}}


def rewrite(legs: list[dict], meta: list[dict], plan_for: PlanFor,
            road: Callable[[list[dict]], Optional[dict]]) -> Optional[tuple[list[dict], list[dict]]]:
    """Train legs over a replaced stretch, split into train, bus and train (see the module notes). Where SŽ's
    replacement timetable runs buses with their own times (`timetable_ride`), the walks at the journey's start
    or end move with them. None when a leg's train (or feed bus) does not run that day and no bus of the day
    makes the journey: OTP planned it on the timetable it knows, the rider would wait for a train that is a bus."""
    out, out_meta = [], []
    shift_after = 0.0  # s the walks after a ride with its own times move by
    for n, (leg, m) in enumerate(zip(legs, meta)):
        if leg['mode'] == 'walk' and shift_after:
            out.append(_shift(leg, shift_after))
            out_meta.append(m)
            continue
        shift_after = 0.0
        timed = timetable_ride(legs, n, plan_for, road, m)
        if timed is not None:
            pieces = timed
        else:
            pieces = _split(leg, m, plan_for, road) if leg['mode'] == 'rail' and leg.get('tripId') else None
            if pieces and not _connects(pieces, legs[n - 1] if n else None, legs[n + 1] if n + 1 < len(legs) else None):
                pieces = None
        if not pieces:
            if replaced(leg, m, plan_for):
                return None
            out.append(leg)
            out_meta.append(m)
            continue
        if timed and _ready(legs, n) is None:  # only walks before it: they end where the first bus leaves
            early = _ts(pieces[0]['effectiveDeparture']) - _ts(leg['effectiveDeparture'])
            for k in range(len(out)):
                out[k] = _shift(out[k], early)
        if timed and _deadline(legs, n) is None:
            shift_after = _ts(pieces[-1]['effectiveArrival']) - _ts(leg['effectiveArrival'])
        for k, piece in enumerate(pieces):
            out.append(piece)
            # A held change: SŽ holds the bus for the train and the train for the bus (rated, not counted; build_journeys).
            # Two of a train's buses meeting is a change like any other.
            held = k > 0 and not (piece['mode'] == 'bus' and pieces[k - 1]['mode'] == 'bus')
            out_meta.append({**m, 'held': held,
                             'duration': _ts(piece['effectiveArrival']) - _ts(piece['effectiveDeparture']),
                             'platform': m['platform'] if k == 0 else None})
    # The buses' live delays, once the journey is decided (see _live).
    return [_with_live(l) for l in out], out_meta


def _with_live(leg: dict) -> dict:
    live = leg.pop('_live', None)
    return {**leg, **live} if live else leg


def _shift(leg: dict, seconds: float) -> dict:
    if not seconds:
        return leg
    like = leg['scheduledDeparture']
    return {**leg, **{k: _stamp(_ts(leg[k]) + seconds, like)
                      for k in ('scheduledDeparture', 'scheduledArrival', 'effectiveDeparture', 'effectiveArrival')}}


def _ready(legs: list[dict], n: int) -> Optional[float]:
    """When the rider can board leg `n`: the ride before it arrives, plus the walks between; None when only walks
    come before (they can start earlier)."""
    walked = 0.0
    for prev in reversed(legs[:n]):
        if prev['mode'] != 'walk':
            return _ts(prev['effectiveArrival']) + walked
        walked += _ts(prev['effectiveArrival']) - _ts(prev['effectiveDeparture'])
    return None


def _deadline(legs: list[dict], n: int) -> Optional[float]:
    """When leg `n` must have arrived to make the next ride; None when only walks follow."""
    walked = 0.0
    for nxt in legs[n + 1:]:
        if nxt['mode'] != 'walk':
            return _ts(nxt['effectiveDeparture']) - walked
        walked += _ts(nxt['effectiveArrival']) - _ts(nxt['effectiveDeparture'])
    return None


def timetable_ride(legs: list[dict], n: int, plan_for: PlanFor, road, m: Optional[dict] = None) -> Optional[list[dict]]:
    """Leg `n` on the buses of SŽ's replacement timetable that day, or None when none concerns it. A train leg over
    a stretch they replace rides, from where it boards to where it alights, the bus or chain of the train's buses
    (and train stretches that still run) arriving first: Ljubljana - Jesenice on 318 is bus 318/1, Ljubljana -
    Lesce Bled 318/2; two buses change where they meet. A leg on a feed bus the timetable runs instead of rides
    the timetable's bus. [] when no such ride makes the journey (rewrite drops it)."""
    leg = legs[n]
    if not leg.get('tripId'):
        return None
    plan = _plan_of(leg, m, plan_for)
    if not plan:
        return None
    ready, deadline = _ready(legs, n), _deadline(legs, n)
    instead = (plan.get('suppressed') or {}).get(leg['tripId'])
    if leg.get('replacement') and instead:
        bus = plan['by_id'].get(instead)
        keys = [sz.station_key(s.get('name') or '') for s in (bus or {}).get('stations') or []]
        frm, to = sz.station_key(leg['origin'].get('name') or ''), sz.station_key(leg['destination'].get('name') or '')
        p = keys.index(frm) if frm in keys else None
        q = keys.index(to, p + 1) if p is not None and to in keys[p + 1:] else None
        if q is None or (ready is not None and bus['departures'][p] < ready) or (deadline is not None and bus['arrivals'][q] > deadline):
            return []
        return [_bus_ride(leg, bus, p, q, road, 'bus0', plan)]
    if leg['mode'] != 'rail':
        return None
    train, crossed = replaced_by.stretches(plan, leg['tripId'], _ts(leg['scheduledDeparture']))
    if not train:
        return None
    start = _index(train['stops'], leg['origin'])
    end = _index(train['stops'], leg['destination'], start if start is not None else -1)
    if start is None or end is None:
        return None
    buses = {s['busTripId']: plan['by_id'].get(s['busTripId']) or replaced_by.run_near(plan, s['busTripId'], s['start']) for _, _, s in crossed}
    if not any(a < end and b > start for a, b, s in crossed if (buses.get(s['busTripId']) or {}).get('source') == 'timetable'):
        return None
    path = _fastest(train, start, end, [b for b in buses.values() if b], {i for a, b, _ in crossed for i in range(a, b)},
                    ready, deadline)
    if not path:
        return []
    pieces = []
    for kind, *where in path:
        suffix = f'{"t" if kind == "train" else "bus"}{len(pieces)}'
        pieces.append(_train_piece(leg, train, *where, suffix) if kind == 'train' else _bus_ride(leg, *where, road, suffix, plan))
    return pieces


MAX_PIECES = 4


def _fastest(train: dict, start: int, end: int, buses: list[dict], replaced: set[int], ready: Optional[float],
             deadline: Optional[float]) -> Optional[list[tuple]]:
    """The ride from the train's stop `start` to `end` arriving first (then leaving last, then with the fewest
    pieces), on the train where it runs (hop i → i+1 not in `replaced`) and on `buses`: [('train', i, j) |
    ('bus', bus, p, q)], or None."""
    train_keys = [sz.station_key(s.get('name') or '') for s in train['stops']]
    target = train_keys[end]
    stretch = set(train_keys[start:end + 1])
    bus_keys = [[sz.station_key(s.get('name') or '') for s in b.get('stations') or b['stops']] for b in buses]
    best: list = [None, None]  # score, path

    def offer(path: list[tuple], arrive: float, leave: float):
        score = (arrive, -leave, len(path))
        if (deadline is None or arrive <= deadline) and (best[0] is None or score < best[0]):
            best[0], best[1] = score, list(path)

    def search(key: str, at: Optional[float], path: list[tuple], seen: set[str], leave: Optional[float]):
        if len(path) >= MAX_PIECES:
            return
        for i in (i for i in range(start, end) if train_keys[i] == key):
            if at is not None and train['departures'][i] < at:
                continue
            for j in range(i + 1, end + 1):
                if j - 1 in replaced:
                    break
                ride = ('train', i, j)
                go(train_keys[j], train['arrivals'][j], path + [ride], seen, train['departures'][i] if leave is None else leave)
        for bus, keys in zip(buses, bus_keys):
            for p in (p for p in range(len(keys) - 1) if keys[p] == key):
                if at is not None and bus['departures'][p] < at:
                    continue
                for q in range(p + 1, len(keys)):
                    if keys[q] in stretch:
                        go(keys[q], bus['arrivals'][q], path + [('bus', bus, p, q)], seen, bus['departures'][p] if leave is None else leave)

    def go(key: str, at: float, path: list[tuple], seen: set[str], leave: float):
        if key == target:
            offer(path, at, leave)
        elif key not in seen:
            search(key, at, path, seen | {key}, leave)
    search(train_keys[start], ready, [], {train_keys[start]}, None)
    return best[1]


def _bus_ride(leg: dict, bus: dict, p: int, q: int, road: Callable[[list[dict]], Optional[dict]], suffix: str,
              plan: Optional[dict] = None) -> dict:
    """A timetable bus from its call `p` to `q` (between the stations; journeys.replacement_walks adds the walks to
    where it stops beside them)."""
    stations = bus.get('stations') or bus['stops']
    part = bus['stops'][p:q + 1]
    shape = road(part)
    like = leg['scheduledDeparture']
    name = bus.get('trainName')
    piece = {
        **leg, 'id': f'{leg["id"]}-{suffix}', 'mode': 'bus', 'routeId': bus['route']['gtfsId'], 'tripId': bus['id'],
        'routeName': mapping.route_name(bus['route']) or leg['routeName'], 'headsign': bus.get('headsign') or part[-1].get('name'),
        'origin': _place(stations[p]), 'destination': _place(stations[q]),
        'scheduledDeparture': _stamp(bus['scheduledDepartures'][p], like), 'scheduledArrival': _stamp(bus['scheduledArrivals'][q], like),
        'effectiveDeparture': _stamp(bus['departures'][p], like), 'effectiveArrival': _stamp(bus['arrivals'][q], like),
        'geometry': shape['coords'] if shape else [[s['lon'], s['lat']] for s in part], 'stopCount': q - p,
        'delaySeconds': None, 'delayProvenance': None, 'replacement': True,
        '_boardAt': part[0], '_alightAt': part[-1], **_live(plan, bus, p, q, like),
    }
    piece.pop('replacesTrain', None)
    if name:
        piece['replacesTrain'] = name
    return _own_bay(piece, part[0])


def _connects(pieces: list[dict], before: Optional[dict], after: Optional[dict]) -> bool:
    """The pieces run in order and still meet the legs around them (a real bus has its own times)."""
    ends = [(_ts(p['effectiveDeparture']), _ts(p['effectiveArrival'])) for p in pieces]
    in_order = all(d <= a for d, a in ends) and all(ends[i][1] <= ends[i + 1][0] + 60 for i in range(len(ends) - 1))
    first_ok = before is None or before['mode'] == 'walk' or _ts(before['effectiveArrival']) <= ends[0][0]
    last_ok = after is None or after['mode'] == 'walk' or ends[-1][1] <= _ts(after['effectiveDeparture'])
    return in_order and first_ok and last_ok


def _split(leg: dict, m: dict, plan_for: PlanFor, road) -> Optional[list[dict]]:
    plan = _plan_of(leg, m, plan_for)
    train, stretches = replaced_by.stretches(plan, leg['tripId'], _ts(leg['scheduledDeparture']))
    if not train:
        return None
    start = _index(train['stops'], leg['origin'])
    end = _index(train['stops'], leg['destination'], start if start is not None else -1)
    if start is None or end is None:
        return None
    # The day's stretches this ride crosses, in order.
    crossed = [(a, b, s) for a, b, s in stretches if a < end and b > start]
    if not crossed:
        return None
    pieces, at = [], start
    for lo, hi, s in crossed:
        a, b = max(lo, at), min(hi, end)
        if a >= b:
            continue
        bus = plan['by_id'].get(s['busTripId']) or replaced_by.run_near(plan, s['busTripId'], s['start'])
        piece = _bus_piece(leg, bus, train, a, b, road, f'bus{len(pieces)}', plan) if bus else None
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


def _plan_of(leg: dict, m: Optional[dict], plan_for: PlanFor) -> Optional[dict]:
    """The plan of the service day the leg's trip runs on, as the line view reads it (from the trip's first
    departure, views._with_replaced): a train still running after midnight is the day before's, not the calendar
    day's. `m['tripStart']`: the trip's first departure, s after its service day's midnight."""
    when = _ts(leg['scheduledDeparture'])
    start = (m or {}).get('tripStart')
    # A moment on the service day: its midnight plus however long the trip has run, plus a margin for DST days.
    return plan_for(when - start + 6 * 3600 if isinstance(start, (int, float)) and start <= when else when)


def replaced(leg: dict, m: Optional[dict], plan_for: PlanFor) -> bool:
    """Whether a bus runs instead of this leg on its service day: a train leg crossing a stretch the day's plan
    replaces (replacement.stretches, which the line view shows), or a feed bus a replacement timetable runs instead
    of (the day's `suppressed`)."""
    if not leg.get('tripId') or leg['mode'] not in ('rail', 'bus'):
        return False
    plan = _plan_of(leg, m, plan_for)
    if leg.get('replacement'):
        return leg['tripId'] in ((plan or {}).get('suppressed') or {})
    if leg['mode'] != 'rail':
        return False
    train, stretches = replaced_by.stretches(plan, leg['tripId'], _ts(leg['scheduledDeparture']))
    start = _index(train['stops'], leg['origin']) if train else None
    end = _index(train['stops'], leg['destination'], start) if start is not None else None
    return end is not None and any(a < end and b > start for a, b, _ in stretches)


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
        when = _ts(leg['scheduledDeparture'])
        plan = plan_for(when)
        if not plan or (plan.get('sections') or {}).get(leg['tripId']):
            continue
        buses = _bus_stations(plan)
        # A notice whose replacement timetable decides this train that day and runs no bus for it: it runs.
        train = replaced_by.run_near(plan, leg['tripId'], when)
        day = closures.service_date(train) if train else None
        number = sz.train_parts(leg.get('routeName') or '')[1]
        decided = plan.get('decided') or {}
        leg['alertIds'] = [i for i in leg['alertIds'] if i not in notices or not (
            _has_buses(alerts[i], buses) or closures.decides(decided.get((i, day)), number))]


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


# ---------------------------------------------------------------- the search window around a timetable's buses

GAIN_NEAR = 5000      # m: a station this close to where the journey starts (or ends) may be its first (or last) ride's
GAIN_MAX = 3600       # s: at most this much wider
GAIN_HOURS = 4 * 3600  # s: only buses this close to the asked time count


def search_gain(plan: Optional[dict], req: dict) -> float:
    """How far to move OTP's search time so it finds the trains a replacement timetable's bus makes work: OTP plans
    with the train's times, and the bus has its own. EC 38 on 19 Oct reaches Jesenice at 06:43 as a train, but its
    bus 38/1 at 06:32, so "arrive by 06:40" never saw it. Departing: how much later than its train a bus leaves a
    station near the origin; arriving: how much earlier it reaches one near the destination. A bus that takes the
    rider nowhere nearer the destination from there (arriving: comes from nowhere nearer the origin) is not ridden, so a
    city trip past Ljubljana station is not moved. The journeys this widened search finds outside the asked time are
    dropped again (journeys.within_time)."""
    if not plan:
        return 0
    arriving = req['timeMode'] == 'arriveBy'
    place = req['destination'] if arriving else req['origin']
    other = req['origin'] if arriving else req['destination']
    here, when = [place['longitude'], place['latitude']], req['dateTime'].timestamp()
    there = [other['longitude'], other['latitude']]
    away = lambda s: geometry.distance([s['lon'], s['lat']], there) if s.get('lat') is not None else math.inf
    best = 0.0
    for bus in plan.get('synthetic') or []:
        if bus.get('source') != 'timetable' or not bus.get('trainTripId'):
            continue
        if min(abs(bus['departures'][0] - when), abs(bus['arrivals'][-1] - when)) > GAIN_HOURS:
            continue
        train = replaced_by.run_near(plan, bus['trainTripId'], bus['departures'][0])
        if not train:
            continue
        index = {sz.station_key(s.get('name') or ''): i for i, s in enumerate(train['stops'])}
        stations = bus.get('stations') or bus['stops']
        for p, s in enumerate(stations):
            i = index.get(sz.station_key(s.get('name') or ''))
            if p == (0 if arriving else len(stations) - 1):
                continue  # nobody rides a bus to where it starts, or from where it ends
            if i is None or s.get('lat') is None or geometry.distance([s['lon'], s['lat']], here) > GAIN_NEAR:
                continue
            if min(map(away, stations[:p] if arriving else stations[p + 1:]), default=math.inf) >= away(s):
                continue
            gain = train['arrivals'][i] - bus['arrivals'][p] if arriving else bus['departures'][p] - train['departures'][i]
            best = max(best, gain)
    return min(best, GAIN_MAX)

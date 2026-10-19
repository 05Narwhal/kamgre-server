"""Live delays of SŽ trains, for whichever vehicle runs each part of a train that day: the train itself, or the
replacement bus on a stretch it runs instead (replacement.py, closures.py).

SŽ reports a train by its number and keeps doing so while its bus is on the road (BUS 18969 carries train 1896).
Both sources measure that delay against the *train's* timetable: the combined GTFS-RT feed (SŽ trip updates on the
train's trip, per station; OTP applies them too) and the SŽ live feed (sz.py: the delay and the next station).
Seen on 19 Oct 2026: LPV 2428, all of it run by BUS 2428, was reported +41 min at Slovenski Javornik at 22:20, the
station its bus was then reaching (train 21:39 + 41 = 22:20; the bus's own timetable says 22:12, so it was 8 min
late, not 41). So a station's live time is the train's timetable there plus the delay, and the delay of the vehicle
there is that time minus the vehicle's own timetable.

Each vehicle takes the delay reported at its own stations and carries it on to its later stops. One with nothing
reported yet takes it from the vehicle before it at the change station: a late train makes its bus leave late,
and nothing leaves a change station early. A bus is never early either (a delay of 0 is the least SŽ reports, and a
bus's timetable is slower than the train's). Several buses at once on one stretch (318/1 and 318/2): the report
cannot tell them apart, so they keep their timetable. With nothing reported at all a vehicle runs by its timetable.

One function for the map (scheduled.vehicles), boards (replacement.board_rows), the trip view
(scheduled.synthetic_entry, trips.load_trips) and journeys (journey_legs), so all show the same delay.
"""
import logging
import time
from typing import Optional

from . import mapping, sz
from . import replacement as replaced_by

logger = logging.getLogger(__name__)

AROUND = 3 * 3600  # s: a report this far from a run's times is about another day's run of the train


def trip_updates() -> dict:
    """The combined GTFS-RT trip updates as last loaded (sources.trip_updates: the vehicles feed and boards load them
    every few seconds), never loading them here: {} when there are none (OTP's own times are used then)."""
    from . import sources
    snap = sources.trip_updates.peek()
    return snap.value if snap and snap.age < sources.trip_updates.max_stale else {}


def _around(run: dict, at: float) -> bool:
    times = run.get('scheduledDepartures') or run['departures']
    return times[0] - AROUND <= at <= times[-1] + AROUND


def station_delays(run: dict, updates: dict, reports: dict) -> tuple[list[Optional[int]], Optional[str], Optional[float]]:
    """What is reported of train `run` at each of its stations, against the train's timetable (None: nothing there),
    where from ('gtfs-rt' | 'sz') and when. The feed's trip update first (what boards and journeys show, through
    OTP), then SŽ's live report, then OTP's own times from the timetable (up to two minutes old)."""
    n = len(run['stops'])
    update = updates.get(run['id'])
    if update and _around(run, update.get('timestamp') or time.time()):
        at_stop = {u.get('stopId'): mapping.update_delay(u) for u in update.get('updates') or []}
        found = [mapping.believable(at_stop.get(s['gtfsId']), False) for s in run['stops']]
        if any(d is not None for d in found):
            return found, 'gtfs-rt', update.get('timestamp') or None
    number = sz.train_parts(mapping.route_name(run['route']))[1]
    report = reports.get(number) if number else None
    if report and report.get('delay') is not None and _around(run, report['at']):
        key = sz.station_key(report.get('next') or '')
        i = next((i for i, s in enumerate(run['stops']) if key and sz.station_key(s.get('name') or '') == key), None)
        delay = mapping.believable(report['delay'], bool(report.get('coords')))
        if i is not None and delay is not None:
            return [delay if j == i else None for j in range(n)], 'sz', report['at']
    own = [mapping.believable(d, False) for d in run.get('delays') or [None] * n]
    return (own, 'gtfs-rt', None) if any(d is not None for d in own) else ([None] * n, None, None)


def _times(vehicle: dict) -> tuple[list[float], list[float]]:
    return (vehicle.get('scheduledArrivals') or vehicle['arrivals'], vehicle.get('scheduledDepartures') or vehicle['departures'])


def _pairs(bus: dict, run: dict, a: int, b: int) -> list[tuple[int, int]]:
    """(bus stop k, train station j) for the stations the bus calls at between the train's stations a and b."""
    if bus.get('synthetic') and 'replaces' not in bus:  # a notice's bus: the train's own stations a..b
        return [(k, a + k) for k in range(b - a + 1) if a + k < len(run['stops'])]
    keys = [sz.station_key(s.get('name') or '') for s in run['stops']]
    out, j = [], a
    for k, s in enumerate(bus.get('stations') or bus['stops']):
        key = sz.station_key(s.get('name') or '')
        if key in keys[j:b + 1]:
            j = keys.index(key, j)
            out.append((k, j))
    return out


def parts(plan: dict, run: dict) -> list[tuple[dict, list[tuple[int, int]], bool]]:
    """The vehicles that run train `run`, in order: (vehicle, [(its stop k, the train's station j)], sure). The train
    runs the stations outside its replaced stretches (a change station belongs to both); `sure` is False for buses
    that run one stretch side by side."""
    crossed = replaced_by.crossed(plan, run)
    by_id = plan.get('by_id') or {}
    out, covered, last = [], 0, len(run['stops']) - 1
    for a, b, section in crossed:
        if a > covered:
            out.append((run, [(j, j) for j in range(covered, a + 1)], True))
        bus = by_id.get(section['busTripId']) or replaced_by.run_near(plan, section['busTripId'], section['start'])
        alone = sum(1 for x, y, _ in crossed if x < b and a < y) == 1
        if bus:
            out.append((bus, _pairs(bus, run, a, b), alone))
        covered = max(covered, b)
    if covered < last or not crossed:
        out.append((run, [(j, j) for j in range(covered, last + 1)], True))
    return out


def run_delays(plan: dict, run: dict, updates: dict, reports: dict) -> dict[str, dict]:
    """Vehicle id (the train's, its buses') -> {'delays' (per stop of that vehicle, against its own timetable; None
    before anything is known), 'source', 'at', 'reported' (its last stop reported itself; None when it only carries
    the delay of the vehicle before it)}."""
    found, source, at = station_delays(run, updates, reports)
    if source is None:
        return {}
    t_arr, t_dep = _times(run)
    out: dict[str, dict] = {}
    carry = None  # live arrival at the change station, from the vehicle before
    for vehicle, pairs, sure in parts(plan, run):
        v_arr, v_dep = _times(vehicle)
        bus = vehicle is not run
        entry = out.setdefault(vehicle['id'], {'delays': [None] * len(vehicle['stops']), 'source': source, 'at': at, 'reported': None})
        delays = entry['delays']
        last_k = len(vehicle['stops']) - 1
        delay = None
        for n, (k, j) in enumerate(pairs if sure else []):
            end = k == last_k
            if found[j] is not None:
                delay = (t_arr[j] if end else t_dep[j]) + found[j] - (v_arr[k] if end else v_dep[k])
                entry['reported'] = k
            elif delay is None and n == 0 and carry is not None:
                delay = carry - v_dep[k]
            if delay is not None and (bus or n == 0):
                delay = max(0, delay)
            if delay is not None:
                delays[k] = round(delay)
        k_end = pairs[-1][0] if pairs else None
        carry = v_arr[k_end] + delays[k_end] if sure and k_end is not None and delays[k_end] is not None else None
    return {k: v for k, v in out.items() if any(d is not None for d in v['delays'])}


def train_of(plan: dict, bus: dict) -> Optional[dict]:
    """The run of the train a replacement bus runs for, in a day's plan."""
    for train_id, sections in (plan.get('sections') or {}).items():
        for s in sections:
            if s['busTripId'] == bus['id']:
                run = replaced_by.run_near(plan, train_id, s['start'])
                if run and any(x[2] is s for x in replaced_by.crossed(plan, run)):
                    return run
    return None


def of(plan: Optional[dict], vehicle: dict, updates: Optional[dict] = None, reports: Optional[dict] = None) -> Optional[dict]:
    """The live delays of one vehicle of a day's plan (a train run or a replacement bus): {'delays', 'source', 'at'},
    or None when nothing is reported."""
    if not plan:
        return None
    updates = trip_updates() if updates is None else updates
    reports = sz.live.get() if reports is None else reports
    run = train_of(plan, vehicle) if mapping.is_replacement(vehicle['route']) else vehicle
    return run_delays(plan, run, updates, reports).get(vehicle['id']) if run else None


def carried(delays: list[Optional[int]]) -> list[Optional[int]]:
    """Per-stop delays carried on to later stops (None before the first one known)."""
    out, last = [], None
    for d in delays:
        last = d if d is not None else last
        out.append(last)
    return out


def applied(vehicle: dict, live: Optional[dict]) -> dict:
    """`vehicle` (a plan's trip or bus) with its live times: 'arrivals', 'departures' and 'delays' (None where
    nothing is known yet), 'delaySource'. Without live data, its timetable."""
    t_arr, t_dep = _times(vehicle)
    if not live:
        return {**vehicle, 'arrivals': list(t_arr), 'departures': list(t_dep), 'delays': [None] * len(t_arr)}
    ahead = carried(live['delays'])
    first = next((d for d in ahead if d is not None), 0)
    shift = [first if d is None else d for d in ahead]  # before its first report it was that late too
    return {**vehicle, 'arrivals': [t + d for t, d in zip(t_arr, shift)], 'departures': [t + d for t, d in zip(t_dep, shift)],
            'delays': ahead, 'delaySource': live['source'], 'scheduledArrivals': list(t_arr), 'scheduledDepartures': list(t_dep)}


def live_bus(plan: Optional[dict], bus: dict) -> dict:
    """A replacement bus of a day's plan with its live times (boards, the trip view, journeys)."""
    try:
        return applied(bus, of(plan, bus))
    except (KeyError, IndexError, TypeError) as e:  # a plan we cannot read must not take the board down
        logger.warning('Live delay of %s failed: %r', bus.get('id'), e)
        return bus

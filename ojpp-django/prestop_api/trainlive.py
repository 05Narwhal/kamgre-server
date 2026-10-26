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
import base64
import logging
import re
import threading
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


# Where a train's live delay can come from, in the order that wins when two are equally fresh. Every path carries SŽ's
# own minute reports as derp-si's scraper reads them: our own reads of the scraper (sz.py) first, as they are never
# older than what is passed on from it and say where the train is (next station, coordinates); then the combined
# feed (what boards and journeys show, through OTP), ijpp-rt's own copy of it, and OTP's SZ-DELAY alert text. A
# feed's timestamp is when it was published, not when SŽ reported (ijpp-rt republishes every few seconds), so only a
# source that stalled for over TIE s loses to a fresher one.
ORDER = ('sz-live', 'sz-delays', 'gtfs-rt', 'ijpp-rt', 'otp-alert')
TIE = 60       # s
DIFFER = 120   # s: two fresh reports at one station further apart than this disagree (counted in `agreement`)
FRESH = 180    # s between two reports for them to be compared at all


def _update_delays(run: dict, update: Optional[dict]) -> Optional[list[Optional[int]]]:
    if not update or not _around(run, update.get('timestamp') or time.time()):
        return None
    at_stop = {u.get('stopId'): mapping.update_delay(u) for u in update.get('updates') or []}
    found = [mapping.believable(at_stop.get(s['gtfsId']), False) for s in run['stops']]
    return found if any(d is not None for d in found) else None


def others() -> dict:
    """The second paths as last read, never waiting on them: {'ijpp-rt': ijpp-rt's trip updates by trip id,
    'otp-alert': OTP's SZ-DELAY alerts by trip id}."""
    from . import sources
    snap = sources.alerts_raw.peek()
    return {'ijpp-rt': sz.rt.get(), 'otp-alert': alert_reports(snap.value if snap else [])}


ALERT = re.compile(r'delayed by (\d+) min(?: on (arrival) at| on (departure) from)?\s*([^.]*)', re.I)
_alerts_memo: dict = {'ref': None, 'value': {}}


def alert_reports(raw: list) -> dict[str, dict]:
    """OTP's SZ-DELAY alerts ("Train RG 310 is delayed by 8 min on departure from Jesenice meja.") as SŽ reports by
    the trip they name: delay, station (when said), event, `at` = the alert's start."""
    if _alerts_memo['ref'] is raw:
        return _alerts_memo['value']
    out = {}
    for a in raw or []:
        if 'SZ-DELAY' not in _decoded(a.get('id') or ''):
            continue
        text = next((t.get('text') or '' for t in a.get('alertDescriptionTextTranslations') or [] if t.get('language') == 'en'), '')
        m = ALERT.search(text)
        trips = [e.get('gtfsId') for e in a.get('entities') or [] if e.get('__typename') == 'Trip' and e.get('gtfsId')]
        if not m or not trips:
            continue
        report = {'delay': int(m.group(1)) * 60, 'event': m.group(2) or m.group(3), 'station': m.group(4).strip() or None,
                  'kind': 'actual', 'at': float(a.get('effectiveStartDate') or 0)}
        for trip in trips:
            out[trip] = report
    _alerts_memo.update(ref=raw, value=out)
    return out


def _decoded(alert_id: str) -> str:
    """OTP's alert id ("alert:" + base64 "Alert:IJPP:SZ-DELAY-462770") in words."""
    try:
        return base64.b64decode(alert_id.split(':', 1)[-1] + '==').decode('utf-8', 'replace')
    except ValueError:
        return alert_id


def candidates(run: dict, updates: dict, reports: dict, second: Optional[dict] = None) -> list[dict]:
    """Every source's report of train `run`: {'name' (ORDER), 'source' ('gtfs-rt' | 'sz', as the app says it),
    'found' (per station, against the train's timetable), 'at', 'kind'}."""
    second = others() if second is None else second
    out = []
    for name, update in (('gtfs-rt', updates.get(run['id'])), ('ijpp-rt', (second.get('ijpp-rt') or {}).get(run['id']))):
        found = _update_delays(run, update)
        if found:
            out.append({'name': name, 'source': 'gtfs-rt', 'found': found, 'at': update.get('timestamp') or None, 'kind': 'actual'})
    number = sz.train_parts(mapping.route_name(run['route']))[1]
    report = reports.get(number) if number else None
    if report and report.get('delay') is not None and _around(run, report['at']):
        placed = report_delays(run, report)
        if placed:
            out.append({'name': 'sz-delays' if report.get('feed') == 'delays' else 'sz-live', 'source': 'sz', 'found': placed,
                        'at': report['at'], 'kind': report.get('kind') or 'actual'})
    alert = (second.get('otp-alert') or {}).get(run['id'])
    if alert and alert.get('station') and _around(run, alert['at']):
        placed = report_delays(run, alert)
        if placed:
            out.append({'name': 'otp-alert', 'source': 'gtfs-rt', 'found': placed, 'at': alert['at'], 'kind': 'actual'})
    return out


def pick(found: list[dict]) -> Optional[dict]:
    """The freshest measured report (SŽ's forecast only when none is measured); within TIE s the one first in ORDER."""
    pool = [c for c in found if c['kind'] == 'actual'] or found
    if not pool:
        return None
    newest = max(c['at'] or 0 for c in pool)
    return min((c for c in pool if (c['at'] or 0) >= newest - TIE), key=lambda c: ORDER.index(c['name']))


class Agreement:
    """How often two fresh sources disagree by more than DIFFER at the same train and station, per pair of sources,
    for the current day, each (run, station, pair) counted once; and which source each train's delay came from last.
    Counters, not log lines: /health (`sz`) and coverage_audit show them. The honest answer to "is it 100 % right": no
    source is, and this says how often they differ."""

    def __init__(self):
        self._lock = threading.Lock()
        self.day: Optional[str] = None
        self.checked: set = set()
        self.differ: set = set()
        self.picked: dict[str, str] = {}  # run id -> the source used last

    def note(self, run: dict, found: list[dict], best: Optional[dict]):
        day = time.strftime('%Y-%m-%d')
        with self._lock:
            if day != self.day:
                self.day, self.checked, self.differ, self.picked = day, set(), set(), {}
            if best:
                self.picked[run['id']] = best['name']
            for i, a in enumerate(found):
                for b in found[i + 1:]:
                    if abs((a['at'] or 0) - (b['at'] or 0)) > FRESH:
                        continue
                    pair = '/'.join(sorted((a['name'], b['name']), key=ORDER.index))
                    for j, (x, y) in enumerate(zip(a['found'], b['found'])):
                        if x is not None and y is not None:
                            key = (run['id'], j, pair)
                            self.checked.add(key)
                            if abs(x - y) > DIFFER:
                                self.differ.add(key)

    def counts(self) -> dict:
        """{'day', 'sources': {source: trains whose delay it gave last}, 'pairs': {pair: {'checked', 'differ'}}}."""
        with self._lock:
            pairs: dict[str, dict] = {}
            for _, _, pair in self.checked:
                pairs.setdefault(pair, {'checked': 0, 'differ': 0})['checked'] += 1
            for _, _, pair in self.differ:
                pairs[pair]['differ'] += 1
            sources: dict[str, int] = {}
            for name in self.picked.values():
                sources[name] = sources.get(name, 0) + 1
            return {'day': self.day, 'sources': dict(sorted(sources.items())), 'pairs': dict(sorted(pairs.items()))}


agreement = Agreement()


def station_delays(run: dict, updates: dict, reports: dict, second: Optional[dict] = None) -> tuple[list[Optional[int]], Optional[str], Optional[float], str]:
    """What is reported of train `run` at each of its stations, against the train's timetable (None: nothing there),
    where from ('gtfs-rt' | 'sz'), when, and whether it is measured or SŽ's forecast ('actual' | 'predicted'). The one
    place that picks the source (`pick` of `candidates`); with none, OTP's own times from the timetable (up to two
    minutes old)."""
    n = len(run['stops'])
    found = candidates(run, updates, reports, second)
    best = pick(found)
    agreement.note(run, found, best)
    if best:
        return best['found'], best['source'], best['at'], best['kind']
    own = [mapping.believable(d, False) for d in run.get('delays') or [None] * n]
    return (own, 'gtfs-rt', None, 'actual') if any(d is not None for d in own) else ([None] * n, None, None, 'actual')


def report_delays(run: dict, report: dict) -> Optional[list[Optional[int]]]:
    """SŽ's report as a departure delay at the station it names (None when the train does not call there): the next
    station of the running-trains list, or a delay-table row's station. An arrival delay holds for that arrival only:
    the train leaves at its timetable time or once in, whichever is later (it never leaves early), so a long stop
    takes some of it up. A departure, or a row without an event, holds from that departure on."""
    key = sz.station_key(report.get('station') or report.get('next') or '')
    i = next((i for i, s in enumerate(run['stops']) if key and sz.station_key(s.get('name') or '') == key), None)
    delay = mapping.believable(report['delay'], bool(report.get('coords')))
    if i is None or delay is None:
        return None
    if report.get('event') == 'arrival' and i < len(run['stops']) - 1:
        t_arr, t_dep = _times(run)
        delay = max(0, round(t_arr[i] + delay - t_dep[i]))
    return [delay if j == i else None for j in range(len(run['stops']))]


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
    # A bus on from where the feed ends the train (BUS 31006 after ICS 31 at Celje) leaves when the train is in. One
    # before where it starts (BUS 14006) has nothing reported: the train's updates are about the train.
    after = replaced_by.beyond(plan, run)[1]
    bus = after and (by_id.get(after['busTripId']) or replaced_by.run_near(plan, after['busTripId'], after['start']))
    if bus:
        out.append((bus, _pairs(bus, run, last, last), True))
    return out


def run_delays(plan: dict, run: dict, updates: dict, reports: dict) -> dict[str, dict]:
    """Vehicle id (the train's, its buses') -> {'delays' (per stop of that vehicle, against its own timetable; None
    before anything is known), 'source', 'at', 'reported' (its last stop reported itself; None when it only carries
    the delay of the vehicle before it), 'kind' ('actual' | 'predicted')}."""
    found, source, at, kind = station_delays(run, updates, reports)
    if source is None:
        return {}
    t_arr, t_dep = _times(run)
    out: dict[str, dict] = {}
    carry = None  # live arrival at the change station, from the vehicle before
    for vehicle, pairs, sure in parts(plan, run):
        v_arr, v_dep = _times(vehicle)
        bus = vehicle is not run
        entry = out.setdefault(vehicle['id'], {'delays': [None] * len(vehicle['stops']), 'source': source, 'at': at, 'reported': None,
                                               'kind': kind})
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
                if run and (any(x[2] is s for x in replaced_by.crossed(plan, run)) or any(x is s for x in replaced_by.beyond(plan, run))):
                    return run
    return None


def of(plan: Optional[dict], vehicle: dict, updates: Optional[dict] = None, reports: Optional[dict] = None) -> Optional[dict]:
    """The live delays of one vehicle of a day's plan (a train run or a replacement bus): {'delays', 'source', 'at'},
    or None when nothing is reported."""
    if not plan:
        return None
    updates = trip_updates() if updates is None else updates
    reports = sz.reports() if reports is None else reports
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
    nothing is known yet), 'delaySource', 'delayKind'. Without live data, its timetable."""
    t_arr, t_dep = _times(vehicle)
    if not live:
        return {**vehicle, 'arrivals': list(t_arr), 'departures': list(t_dep), 'delays': [None] * len(t_arr)}
    ahead = carried(live['delays'])
    first = next((d for d in ahead if d is not None), 0)
    shift = [first if d is None else d for d in ahead]  # before its first report it was that late too
    return {**vehicle, 'arrivals': [t + d for t, d in zip(t_arr, shift)], 'departures': [t + d for t, d in zip(t_dep, shift)],
            'delays': ahead, 'delaySource': live['source'], 'delayKind': live.get('kind') or 'actual',
            'scheduledArrivals': list(t_arr), 'scheduledDepartures': list(t_dep)}


def live_bus(plan: Optional[dict], bus: dict) -> dict:
    """A replacement bus of a day's plan with its live times (boards, the trip view, journeys)."""
    try:
        return applied(bus, of(plan, bus))
    except (KeyError, IndexError, TypeError) as e:  # a plan we cannot read must not take the board down
        logger.warning('Live delay of %s failed: %r', bus.get('id'), e)
        return bus

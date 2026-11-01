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
    if not mapping.is_replacement(run['route']):
        # Nothing of its own yet, or only a smaller forecast: the delay of the train whose set it is (a `sure` stay)
        came = expected(plan, run, updates, reports, own=(found, source))
        if came:
            found = [came['delay']] + [None] * (len(run['stops']) - 1)
            source, at, kind = came['source'], came['at'], 'predicted'
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


# ---------------------------------------------------------------- the delay of the train before (spec 2026-10-31 H8)

CHAIN_HOPS = 6        # trains back along `sure` stays (as predictions.CHAIN_HOPS for buses)
CHAIN_AHEAD = 3 * 3600  # s: only for a train leaving this soon
_numbers: dict = {'trips': None, 'value': {}}


def _by_number(plan: dict) -> dict[str, list[dict]]:
    """Train number -> its runs in a day's plan (trains only)."""
    trips = plan.get('trips') or {}
    if _numbers['trips'] is not trips:
        out: dict[str, list[dict]] = {}
        for runs in trips.values():
            for r in runs:
                if not mapping.is_replacement(r['route']):
                    number = sz.train_parts(mapping.route_name(r['route']))[1]
                    if number:
                        out.setdefault(number, []).append(r)
        _numbers.update(trips=trips, value=out)
    return _numbers['value']


def _service_date(run: dict):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(run['serviceDay'] + 12 * 3600, ZoneInfo('Europe/Ljubljana')).date()


HOLD_AFTER = 15 * 60  # s after a train's timetable departure: the last delay of the train before says nothing more about it
HELD_TTL = 30         # s between reads of the delays the collector stored (one read for all trains, never one per row)
_held: dict = {}      # service date -> (monotonic time, {trip id: (stop_delays, last_seen timestamp)})


def _stored_delays(plan: dict, day) -> dict[str, tuple[dict, float]]:
    """Trip id -> (TripDelay.stop_delays, its last_seen) on service day `day`, for the trains with a `sure` stay after
    them. A failed read is nothing held: a stay is optional, and a board must stand without it."""
    from prestop_statistics import train_stays
    from prestop_statistics.models import TripDelay
    hit = _held.get(day)
    if hit and time.monotonic() - hit[0] < HELD_TTL:
        return hit[1]
    by_number = _by_number(plan)
    ids = {r['id'] for number, stay in train_stays.table()['from'].items() if stay['level'] == 'sure' for r in by_number.get(number, ())}
    rows: dict[str, tuple[dict, float]] = {}
    try:
        if ids:
            rows = {t: (delays, seen.timestamp()) for t, delays, seen in TripDelay.objects.filter(service_date=day, trip_id__in=ids, canceled=False)
                    .values_list('trip_id', 'stop_delays', 'last_seen')}
    except Exception as e:  # noqa: BLE001 - see above
        logger.warning('Stored delays of %s unavailable: %r', day, e)
    if len(_held) > 3:
        _held.clear()
    _held[day] = (time.monotonic(), rows)
    return rows


def held_delay(plan: dict, before: dict) -> Optional[tuple[int, float]]:
    """(delay, when it was seen) of train `before` near its end from what the collector stored, for when it has reached
    its turn station and dropped out of SŽ's feeds. Read as the learning reads it (train_stays.end_delay: the last
    reported of its last NEAR stations), so a train lost far from its end holds nothing. A position this train does not
    have means the numbering is not the 1..n of SŽ's feed: nothing, rather than a delay from the wrong station."""
    from prestop_statistics import train_stays
    stored = _stored_delays(plan, _service_date(before)).get(before['id'])
    if not stored:
        return None
    delays, seen = stored
    n = len(before['stops'])
    if not all(str(k).isdigit() and 1 <= int(k) <= n for k in delays):
        return None
    end = train_stays.end_delay([{'delay': mapping.believable(delays.get(str(i + 1)), False)} for i in range(n)])
    return None if end is None else (end, seen)


def carried_delay(plan: Optional[dict], run: dict, updates: dict, reports: dict, now: Optional[float] = None,
                  hops: int = CHAIN_HOPS) -> Optional[dict]:
    """How late train `run` will leave because the train whose set it is (a `sure` stay, train_stays.py) is late:
    {'delay' (s, never below 0), 'source', 'at' (of the report it comes from), 'from' (that train's number)}, or None.
    That train's live delay minus the slack in the turn; once it has dropped out of the feeds, its last delay as the
    collector stored it (`held_delay`), until HOLD_AFTER past `run`'s timetable departure; when it has nothing reported
    either, its own carried delay, up to CHAIN_HOPS trains back, only through `sure` stays and for a train leaving within
    CHAIN_AHEAD. Whether it beats what is reported of `run` itself is `expected`'s to say."""
    from prestop_statistics import train_stays
    if not plan or hops <= 0 or not run.get('serviceDay'):
        return None
    now = time.time() if now is None else now
    if _times(run)[1][0] - now > CHAIN_AHEAD:
        return None
    link = train_stays.sure_link_to(number_of(run), _service_date(run))
    if not link:
        return None
    arrives = run['serviceDay'] + link['arrival']
    before = next((r for r in _by_number(plan).get(link['from_number'], ()) if abs(_times(r)[0][-1] - arrives) <= 120), None)
    if not before:
        return None
    if replaced(plan, run) or replaced(plan, before):
        return None  # a bus runs part of either: not the same set going on
    found, source, at, _ = station_delays(before, updates, reports)
    end = carried(found)[-1] if source else None
    if end is None and now - _times(run)[1][0] <= HOLD_AFTER and (held := held_delay(plan, before)):
        end, at = held
        source = 'gtfs-rt'  # the collector stores what the GTFS-Realtime feed said
    if end is None:
        earlier = carried_delay(plan, before, updates, reports, now, hops - 1)
        if not earlier:
            return None
        end, source, at = earlier['delay'], earlier['source'], earlier['at']
    return {'delay': max(0, round(end - link['slack'])), 'source': source, 'at': at, 'from': link['from_number']}


GUESS_AFTER = HOLD_AFTER  # s past a train's timetable departure what the feed says of it may still be its forecast from before


def expected(plan: Optional[dict], run: dict, updates: dict, reports: dict, now: Optional[float] = None,
             own: Optional[tuple[list[Optional[int]], Optional[str]]] = None) -> Optional[dict]:
    """The carried delay (carried_delay, at least 1 s) where it is shown for train `run`, else None: when nothing is
    reported of `run` itself, or only a forecast smaller than it (the user's call, 1 Nov 2026, after I13). Before a train
    leaves, the feed often has a forecast for it already, usually +0, that knows nothing of the late train whose set it
    is: LPV 2520 'on time' while LPV 2010, its set, was 14 min late. The feed does not say which of its numbers are
    measured, so what it says counts as a forecast until `run` is past a station after its first by those numbers, and
    at most until GUESS_AFTER past its timetable departure. SŽ's own report of `run` as measured (sz-live, sz-delays)
    always wins, and so does a larger forecast. `own`: station_delays' (delays, source) of `run` when the caller has
    them. 'over' in the answer: it replaces a forecast (the caller drops that one's live times)."""
    now = time.time() if now is None else now
    delays, source = own if own is not None else station_delays(run, updates, reports)[:2]
    if source is not None:
        t_arr, t_dep = _times(run)
        if now - t_dep[0] > GUESS_AFTER or any(d is not None and t_arr[j] + d <= now for j, d in enumerate(delays) if j):
            return None
        if any(c['source'] == 'sz' and c['kind'] == 'actual' for c in candidates(run, updates, reports)):
            return None
    came = carried_delay(plan, run, updates, reports, now)
    if not came or came['delay'] <= 0:
        return None
    if source is not None:
        mine = next((d for d in carried(delays) if d is not None), None)
        if mine is not None and mine >= came['delay']:
            return None
    return {**came, 'over': source is not None}


def replaced(plan: dict, run: dict) -> bool:
    """Buses run some of train `run` in that day's plan (a replaced stretch, or a bus on from where it ends)."""
    return bool((plan.get('sections') or {}).get(run['id'])) or any(replaced_by.beyond(plan, run))


def number_of(run: dict) -> Optional[str]:
    return sz.train_parts(mapping.route_name(run['route']))[1]


def _run_in(plan: Optional[dict], trip_id: str, when: float) -> Optional[dict]:
    """The run of a trip in a day's plan that is on its way at `when` (one of its stop times), else the nearest."""
    runs = (plan or {}).get('trips', {}).get(trip_id) or []
    return min(runs, key=lambda r: max(0, _times(r)[1][0] - when, when - _times(r)[0][-1]), default=None)


def carried_for_trip(trip_id: str, when: float) -> Optional[dict]:
    """`expected` for the run of a train trip with a stop at `when` (journeys, boards, the trip view, the train page),
    from the plan of that time, never waiting for one."""
    from . import scheduled
    run = _run_in(plan := scheduled.plan_at(when), trip_id, when)
    if not run or mapping.is_replacement(run['route']):
        return None
    try:
        return expected(plan, run, trip_updates(), sz.reports())
    except (KeyError, IndexError, TypeError) as e:  # a plan we cannot read must not take the answer down
        logger.warning('Carried delay of %s failed: %r', trip_id, e)
        return None


def may_carry(route_name: Optional[str]) -> bool:
    """Whether train `route_name` ("LPV 2002") has a learned `sure` stay before it at all: a dict lookup, so boards and
    journeys touch a day's plan only for those."""
    from prestop_statistics import train_stays
    stay = train_stays.comes_from(sz.train_parts(route_name or '')[1])
    return bool(stay and stay['level'] == 'sure')


def carried_rows(rows: list[dict]) -> list[dict]:
    """Board rows of trains without a live time of their own, or with only a smaller forecast (`expected`), get the
    carried delay (as SŽ's forecast: 'predicted'); the rest as they are. New dicts, never the cached rows."""
    from datetime import datetime
    out = []
    for row in rows:
        if row.get('mode') != 'rail' or row.get('replacement') or row.get('canceled') or not row.get('tripId') \
                or not may_carry(row.get('routeName')):
            out.append(row)
            continue
        at = datetime.fromisoformat(row['scheduledAt']).timestamp()
        came = carried_for_trip(row['tripId'], at)
        mine = datetime.fromisoformat(row['effectiveAt']).timestamp() - at if row.get('effectiveAt') else None
        if not came or came['delay'] < 60 or (mine is not None and (not came.get('over') or mine >= came['delay'])):
            out.append(row)
            continue
        out.append({**row, 'effectiveAt': mapping.iso(at + came['delay']), 'updatedAt': mapping.iso(time.time()), 'quality': 'predicted',
                    'delaySource': came['source'], 'delayKind': 'predicted'})
    return out


STAY_TTL = 600  # s a board row's "continues as" is reused (the learned table itself is reloaded at most every 10 min)
_stays_memo: dict[tuple, tuple[float, Optional[dict]]] = {}


def continues_as(number: Optional[str], day) -> Optional[dict]:
    """A board row's "continues as" (spec 2026-11-01 I12): {'name', 'destination', 'level'} when train `number`'s set
    goes on as another train on service day `day` by a learned stay that still fits the day (train_stays.holds), else
    None. Only a set that goes on alone ('continues'): a `coupled` join is left out, since which car goes where is said
    only by SŽ's notice. A dict lookup for every other train; memoised per train and day for those with a stay."""
    from prestop_statistics import train_stays
    stay = train_stays.continues_as(number)
    if not stay or stay['kind'] != 'continues' or stay['level'] not in ('sure', 'likely'):
        return None
    key = (number, day, stay['to_number'], stay['level'])
    hit = _stays_memo.get(key)
    if hit and time.monotonic() - hit[0] < STAY_TTL:
        return hit[1]
    found = None
    try:
        runs = train_stays._runs(day)
        b = runs.get(stay['to_number'])
        if b and train_stays.holds(stay, day, runs):
            found = {'name': b['name'], 'destination': b['stops'][-1]['name'], 'level': stay['level']}
    except Exception as e:  # noqa: BLE001 - optional: the board stands without it
        logger.info('Train stay of %s unavailable: %r', number, e)
    if len(_stays_memo) > 2000:
        _stays_memo.clear()
    _stays_memo[key] = (time.monotonic(), found)
    return found


def stay_rows(rows: list[dict]) -> list[dict]:
    """Board rows of trains whose set goes on as another train get `continuesAs` (new dicts; the rest as they are)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    out = []
    for row in rows:
        number =sz.train_parts(row.get('routeName') or '')[1] if row.get('mode') == 'rail' and not row.get('replacement') and not row.get('canceled') else None
        found = continues_as(number, (datetime.fromisoformat(row['scheduledAt']).astimezone(ZoneInfo('Europe/Ljubljana')) - timedelta(hours=4)).date()) if number else None
        out.append({**row, 'continuesAs': found} if found else row)
    return out


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

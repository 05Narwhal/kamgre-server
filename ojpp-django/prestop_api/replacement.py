"""SŽ replacement buses (nadomestni prevoz) and the trains they stand in for.

SŽ numbers a replacement bus after its train plus one or two digits: "BUS 18969" and
"BUS 18968" carry train 1896 from Ljubljana to Logatec, "BUS 52606" carries IC 526. The
feed usually splits the train (LPV 1896 starts at Logatec), but the live feed (sz.py)
still reports train 1896 while its bus is on the road, and a feed that keeps the whole
train would draw it on the closed track. A *replaced section* is the stretch a bus covers
for one train on one day, matched by number and by the train touching the bus's stations.

While the bus runs that section:
- live reports of the train's number at the section's stations move the bus, not the
  train (trainlive.py); the train is not drawn between the section's stations (it is
  shown again outside it);
- the train's board rows inside the section become rows of the bus (board_rows), and a journey
  over the section rides the bus there (journey_legs.py).
Each service day has its own sections (scheduled.day_plan): only the buses running that day
and the notices in effect that day count.
"""
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Callable, Optional

from . import abroad, mapping, sz, trainlive

LOCAL = ZoneInfo('Europe/Ljubljana')
MATCH_WINDOW = 3 * 3600  # s: a train this far from the bus in time is another day's run


def train_numbers(bus_name: str) -> list[str]:
    """'BUS 18969' -> ['1896', '189', '18']: the train number with the bus's own suffix digits removed, longest
    first. The suffix fills the bus number to five digits: LPV 1896 → 18969, IC 526 → 52606, ICS 14 → 14006.
    A bus of several for one train ("BUS 18969/2") is numbered like the first."""
    digits = re.sub(r'\D', '', re.sub(r'/\d+\s*$', '', bus_name or ''))
    return [digits[:-n].lstrip('0') for n in (1, 2, 3) if len(digits) - n >= 2]


def _epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def _keys(trip: dict) -> list[str]:
    return [sz.station_key(s.get('name') or '') for s in trip['stops']]


def sections(trips: list[dict]) -> dict[str, list[dict]]:
    """Train trip id -> its replaced sections: {'start', 'end' (bus times), 'fromIndex', 'toIndex'
    (the bus's first and last station in the train's stops, None where the train does not stop),
    'busTripId'}."""
    trains: dict[str, list[dict]] = {}
    buses = []
    for t in trips:
        if mapping.is_replacement(t['route']):
            buses.append(t)
        else:
            number = sz.train_parts(mapping.route_name(t['route']))[1]
            if number:
                trains.setdefault(number, []).append(t)
    out: dict[str, list[dict]] = {}
    for bus in buses:
        first, last = _keys(bus)[0], _keys(bus)[-1]
        start, end = bus['departures'][0], bus['arrivals'][-1]
        for number in train_numbers(mapping.route_name(bus['route'])):
            found = False
            for train in trains.get(number, []):
                keys = _keys(train)
                ia = keys.index(first) if first in keys else None
                ib = keys.index(last) if last in keys else None
                if ia is None and ib is None or (ia is not None and ib is not None and ia >= ib):
                    continue
                at = train['departures'][ia] if ia is not None else train['arrivals'][ib]
                if abs(at - (start if ia is not None else end)) > MATCH_WINDOW:
                    continue
                out.setdefault(train['id'], []).append({'start': start, 'end': end, 'fromIndex': ia, 'toIndex': ib, 'busTripId': bus['id']})
                found = True
            if found:
                break
    return out


def active(trip_sections: Optional[list[dict]], now: float, lead: float = 0) -> list[dict]:
    return [s for s in trip_sections or [] if s['start'] - lead <= now <= s['end']]


def inside(section: dict, stop_index: int) -> bool:
    """Whether a train heading to (or standing at) stop `stop_index` is within the replaced stretch; a stretch
    from the train's first station also covers the train waiting there."""
    ia, ib = section['fromIndex'], section['toIndex']
    return ia is not None and ib is not None and (ia < stop_index <= ib or ia == stop_index == 0)


def replaced_at(trip_sections: Optional[list[dict]], station_key: str, keys: list[str], when: float) -> bool:
    """Whether the train leaving `station_key` at `when` runs a replaced stretch from there (its board row
    says "replaced by bus")."""
    if station_key not in keys:
        return False
    i = keys.index(station_key)
    return any(s['fromIndex'] is not None and s['toIndex'] is not None and s['fromIndex'] <= i < s['toIndex']
               and abs(s['start'] - when) <= MATCH_WINDOW for s in trip_sections or [])


def run_near(plan: dict, trip_id: str, when: float) -> Optional[dict]:
    """A plan's run of trip `trip_id` closest in time to `when` (a plan can hold two days of one train)."""
    runs = (plan.get('trips') or {}).get(trip_id) or []
    return min(runs, key=lambda t: min(abs(x - when) for x in t['departures'] + t['arrivals']), default=None)


def section_at(trip_sections: Optional[list[dict]], i: int, when: float, kind: str) -> Optional[dict]:
    """The replaced section a train leaves stop `i` into (departures), or arrives at stop `i` through (arrivals)."""
    for s in trip_sections or []:
        a, b = s['fromIndex'], s['toIndex']
        if a is None or b is None or abs(s['start'] - when) > MATCH_WINDOW:
            continue
        if (a <= i < b) if kind == 'departure' else (a < i <= b):
            return s
    return None


def stretches(plan: Optional[dict], trip_id: str, when: float) -> tuple[Optional[dict], list[tuple[int, int, dict]]]:
    """The run of train `trip_id` around `when` in a day's plan, and the stretches of it a bus runs instead that day:
    [(a, b, section)], indices in the run's stops, a < b, in order. An end of the bus the train does not call at is
    the train's first or last stop (the bus runs from before the train starts, or past where it ends). The one
    source for the line view (trip_sections) and journeys (journey_legs), so they never disagree."""
    found = (plan or {}).get('sections', {}).get(trip_id)
    train = run_near(plan, trip_id, when) if found else None
    if not train:
        return None, []
    return train, crossed(plan, train)


def crossed(plan: Optional[dict], train: dict) -> list[tuple[int, int, dict]]:
    """The stretches of one run of a train (a plan's trip) a bus runs instead that day: [(a, b, section)], in order."""
    found = (plan or {}).get('sections', {}).get(train['id']) or []
    last = len(train['stops']) - 1
    out = []
    for s in found:
        ia, ib = s['fromIndex'], s['toIndex']
        at = train['departures'][ia] if ia is not None else train['arrivals'][ib]
        if abs(at - (s['start'] if ia is not None else s['end'])) > MATCH_WINDOW:
            continue  # another day's run of the train
        a, b = 0 if ia is None else ia, last if ib is None else ib
        if a < b:
            out.append((a, b, s))
    return sorted(out, key=lambda x: x[0])


def beyond(plan: Optional[dict], train: dict) -> tuple[Optional[dict], Optional[dict]]:
    """The sections of one run of a train whose bus runs only before its first station or only on from its last one,
    where the feed splits the train (ICS 14: BUS 14006 Ljubljana – Celje, then the train Celje – Maribor): (before,
    after). No stretch of the train is replaced (crossed leaves them out), but the bus runs for that train."""
    found = (plan or {}).get('sections', {}).get(train['id']) or []
    last = len(train['stops']) - 1
    before = next((s for s in found if s['fromIndex'] is None and s['toIndex'] == 0
                   and abs(train['arrivals'][0] - s['end']) <= MATCH_WINDOW), None)
    after = next((s for s in found if s['toIndex'] is None and s['fromIndex'] == last
                  and abs(train['departures'][last] - s['start']) <= MATCH_WINDOW), None)
    return before, after


def trip_sections(trip: dict, plan: Optional[dict]) -> list[dict]:
    """A train trip's (trips.build_trip) stretches a bus runs instead that day: {'fromIndex', 'toIndex' (the bus's
    first and last station in the trip's stops, None where the train does not call), 'busTripId', 'busName'}."""
    if not trip['stops']:
        return []
    train, crossed = stretches(plan, trip['id'], _epoch(trip['stops'][0]['scheduledDeparture']))
    if not train:
        return []
    keys, own = _keys(train), [sz.station_key(s['name']) for s in trip['stops']]
    out = []
    for _, _, s in crossed:
        bus = plan['by_id'].get(s['busTripId']) or run_near(plan, s['busTripId'], s['start'])
        ends = [keys[i] if i is not None else None for i in (s['fromIndex'], s['toIndex'])]
        a, b = (own.index(k) if k in own else None for k in ends)
        if a is None and b is None:
            continue
        out.append({'fromIndex': a, 'toIndex': b, 'busTripId': s['busTripId'],
                    'busName': mapping.route_name(bus['route']) if bus else None})
    return out


def bus_row(entry: dict, bus: dict, kind: str, here: str) -> dict:
    """A train's board row as the row of the bus that replaces it from (or to) this station."""
    keys = _keys(bus)
    k = keys.index(here) if here in keys else (0 if kind == 'departure' else len(keys) - 1)
    leave = kind == 'departure'
    scheduled = (bus.get('scheduledDepartures') if leave else bus.get('scheduledArrivals')) or (bus['departures'] if leave else bus['arrivals'])
    live = bus['departures'] if leave else bus['arrivals']
    end = bus['stops'][-1] if leave else bus['stops'][0]
    ends = abroad.scheduled_ends(bus)
    row = {**entry, 'id': f'{bus["id"]}@{entry["id"].split("@", 1)[-1]}', 'tripId': bus['id'], 'routeId': bus['route']['gtfsId'],
           'routeName': mapping.route_name(bus['route']) or entry['routeName'], 'mode': 'bus',
           'destination': ends[1 if leave else 0] or end.get('name') or entry['destination'], 'scheduledAt': mapping.iso(scheduled[k]),
           'effectiveAt': mapping.iso(live[k]) if bus['delays'][k] is not None else None,
           'replacement': True, 'replacesTrain': entry['routeName']}
    row.pop('delaySource', None)
    if bus['delays'][k] is not None:  # its own live time (trainlive.py), not the train's
        row.update(updatedAt=mapping.iso(time.time()), quality='predicted')
        if bus.get('delaySource'):
            row['delaySource'] = bus['delaySource']
    else:
        row.update({k: None for k in ('updatedAt', 'quality') if k in entry})
    row.pop('replacedByBus', None)
    row.pop('comesFrom', None)
    if leave and ends[0]:
        row['comesFrom'] = ends[0]
    if bus['stops'][k].get('bay'):
        row['platform'] = bus['stops'][k]['bay']
    return row


def feed_bus_row(entry: dict, plan: dict, kind: str) -> dict:
    """The board row of a feed's own replacement bus (BUS 31006): the train it runs for and, as on the map and its
    trip view, that train's live delay (trainlive.py; OTP has none for the bus)."""
    at = _epoch(entry['scheduledAt'])
    bus = run_near(plan, entry['tripId'], at)
    if not bus:
        return entry
    leave = kind == 'departure'
    times = (bus.get('scheduledDepartures') if leave else bus.get('scheduledArrivals')) or (bus['departures'] if leave else bus['arrivals'])
    k = next((k for k, s in enumerate(bus['stops']) if s['gtfsId'] == entry['stopId'] and abs(times[k] - at) < 60), None)
    if k is None:
        return entry
    row = dict(entry)
    train = trainlive.train_of(plan, bus)
    if train:
        row['replacesTrain'] = mapping.route_name(train['route'])
    live = trainlive.live_bus(plan, bus)
    if entry.get('effectiveAt') is None and live['delays'][k] is not None:
        row.update(effectiveAt=mapping.iso((live['departures'] if leave else live['arrivals'])[k]),
                   updatedAt=mapping.iso(time.time()), quality='predicted', delaySource=live['delaySource'])
    return row


def board_rows(entries: list[dict], kind: str, names: dict[str, str], plan_for: Callable[[float], Optional[dict]],
               stop_ids: Optional[list[str]] = None, start: Optional[float] = None, end: Optional[float] = None,
               drops: Optional[list] = None) -> list[dict]:
    """Rows of trains that a bus replaces at this station become that bus's rows (BUS 1896 to Logatec, its
    own line and trip), judged by each row's own service day: `plan_for(when)` gives the day's plan
    (scheduled.plan_at). A bus already listed on the board stands for its train itself.

    The buses of SŽ's replacement timetables have their own times and stops, and a train can have several
    (318/1 and 318/2 both leave Ljubljana): each gets its own row at every stop of the board (`stop_ids`) it
    calls at between `start` and `end` (the board's time), and the rows of the trains they replace there, and
    of the feed's buses they run instead of (the day's `suppressed`), are left out. `drops`: the rows left out or
    shown as their bus, and why (coverage.note)."""
    from . import coverage
    listed = {e['tripId'] for e in entries}
    plans: dict = {}

    def plan_of(when: float) -> Optional[dict]:
        day = datetime.fromtimestamp(when, LOCAL).date()
        if day not in plans:
            plans[day] = plan_for(when)
        return plans[day]
    out = []
    for e in entries:
        plan = plan_of(_epoch(e['scheduledAt'])) if e['mode'] == 'rail' or e.get('replacement') else None
        if e['tripId'] in ((plan or {}).get('suppressed') or {}):
            coverage.note(drops, 'run by a replacement timetable', e)
            continue
        trip_sections = (plan or {}).get('sections', {}).get(e['tripId']) if e['mode'] == 'rail' else None
        train = run_near(plan, e['tripId'], _epoch(e['scheduledAt'])) if trip_sections else None
        here = sz.station_key(names.get(e['stopId'], ''))
        keys = _keys(train) if train else []
        hit = section_at(trip_sections, keys.index(here), _epoch(e['scheduledAt']), kind) if here in keys else None
        if not hit:
            out.append(feed_bus_row(e, plan, kind) if plan and e['mode'] == 'bus' and e.get('replacement') else e)
            continue
        if hit['busTripId'] in listed:
            coverage.note(drops, 'replaced by a bus on the board', e)
            continue
        bus = plan['by_id'].get(hit['busTripId']) or run_near(plan, hit['busTripId'], hit['start'])
        if bus and bus.get('source') == 'timetable':
            coverage.note(drops, 'replaced by a bus on the board', e)
            continue  # its buses' own rows follow
        if bus:
            coverage.note(drops, 'shown as its replacement bus', e)
        out.append(bus_row(e, trainlive.live_bus(plan, bus), kind, here) if bus else {**e, 'replacedByBus': True})
    times = [_epoch(e['scheduledAt']) for e in entries]
    start = min(times, default=None) if start is None else start
    end = max(times, default=None) if end is None else end
    stops = set(stop_ids if stop_ids is not None else (e['stopId'] for e in entries))
    # The plan of the board's start holds its whole time (a board runs to the end of that service day; today's
    # plan also has yesterday's late trains), and asking for another day's would make it wait for that one.
    plan = plan_of(start) if start is not None and end is not None and stops else None
    if plan:
        seen = {e['id'] for e in out}
        for row in timetable_rows(plan, kind, stops, start, end, names, merged=len(stops) > 1):
            if row['id'] not in seen:
                seen.add(row['id'])
                out.append(row)
    out.sort(key=lambda e: _epoch(e['scheduledAt']))
    return out


def timetable_rows(plan: dict, kind: str, stops: set[str], start: float, end: float, names: dict[str, str], merged: bool) -> list[dict]:
    """Board rows of a day's replacement-timetable buses at `stops` between `start` and `end`."""
    out = []
    leave = kind == 'departure'
    for bus in plan.get('synthetic') or []:
        if bus.get('source') != 'timetable':
            continue
        live = None
        last = len(bus['stops']) - 1
        ends = abroad.scheduled_ends(bus)
        for k, stop in enumerate(bus['stops']):
            # Its end in Slovenia has no row, unless the bus runs on abroad (Sežana -> Opčine)
            if stop.get('gtfsId') not in stops or (k == (last if leave else 0) and not ends[1 if leave else 0]):
                continue
            at = bus['departures'][k] if leave else bus['arrivals'][k]
            if not start <= at <= end:
                continue
            live = live or trainlive.live_bus(plan, bus)
            moved = (live['departures'] if leave else live['arrivals'])[k] if live['delays'][k] is not None else None
            row = {'id': f'{bus["id"]}@{bus.get("serviceDay")}/{k}', 'stopId': stop['gtfsId'], 'tripId': bus['id'],
                   'routeId': bus['route']['gtfsId'], 'operatorId': bus['route']['agency']['gtfsId'],
                   'routeName': mapping.route_name(bus['route']), 'mode': 'bus',
                   'destination': ends[1 if leave else 0] or (bus['stops'][-1] if leave else bus['stops'][0]).get('name') or '',
                   'scheduledAt': mapping.iso(at), 'effectiveAt': mapping.iso(moved) if moved is not None else None,
                   'updatedAt': mapping.iso(time.time()) if moved is not None else None, 'quality': 'predicted' if moved is not None else None, 'canceled': False,
                   'platform': stop.get('bay') or None, 'alertIds': list(bus.get('alertIds') or []), 'replacement': True}
            if bus.get('trainName'):
                row['replacesTrain'] = bus['trainName']
            if moved is not None and live.get('delaySource'):
                row['delaySource'] = live['delaySource']
            if leave and ends[0]:
                row['comesFrom'] = ends[0]
            if merged and stop['gtfsId'] in names:
                row['stopName'] = names[stop['gtfsId']]
            out.append(row)
    return out


def mark_board(entries: list[dict], names: dict[str, str], trips: list[dict], replaced: dict[str, list[dict]]) -> list[dict]:
    """Board rows of trains that a bus replaces from this station get `replacedByBus`."""
    if not replaced:
        return entries
    keys = {t['id']: _keys(t) for t in trips if t['id'] in replaced}
    for e in entries:
        if e['mode'] == 'rail' and e['tripId'] in keys and replaced_at(
                replaced[e['tripId']], sz.station_key(names.get(e['stopId'], '')), keys[e['tripId']], _epoch(e['scheduledAt'])):
            e['replacedByBus'] = True
    return entries

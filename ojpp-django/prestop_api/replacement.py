"""SŽ replacement buses (nadomestni prevoz) and the trains they stand in for.

SŽ numbers a replacement bus after its train plus one or two digits: "BUS 18969" and
"BUS 18968" carry train 1896 from Ljubljana to Logatec, "BUS 52606" carries IC 526. The
feed usually splits the train (LPV 1896 starts at Logatec), but the live feed (sz.py)
still reports train 1896 while its bus is on the road, and a feed that keeps the whole
train would draw it on the closed track. A *replaced section* is the stretch a bus covers
for one train on one day, matched by number and by the train touching the bus's stations.

While the bus runs that section:
- the train ignores live reports (they describe the bus) and is not drawn between the
  section's stations (it is shown again outside it, by its timetable);
- the train's board rows inside the section become rows of the bus (board_rows), and a journey
  over the section rides the bus there (journey_legs.py).
Each service day has its own sections (scheduled.day_plan): only the buses running that day
and the notices in effect that day count.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Callable, Optional

from . import mapping, sz

LOCAL = ZoneInfo('Europe/Ljubljana')
MATCH_WINDOW = 3 * 3600  # s: a train this far from the bus in time is another day's run


def train_numbers(bus_name: str) -> list[str]:
    """'BUS 18969' -> ['1896', '189', '18']: the train number with the bus's own suffix digits removed, longest
    first. The suffix fills the bus number to five digits: LPV 1896 → 18969, IC 526 → 52606, ICS 14 → 14006."""
    digits = re.sub(r'\D', '', bus_name or '')
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


def bus_row(entry: dict, bus: dict, kind: str, here: str) -> dict:
    """A train's board row as the row of the bus that replaces it from (or to) this station."""
    keys = _keys(bus)
    k = keys.index(here) if here in keys else (0 if kind == 'departure' else len(keys) - 1)
    leave = kind == 'departure'
    scheduled = (bus.get('scheduledDepartures') if leave else bus.get('scheduledArrivals')) or (bus['departures'] if leave else bus['arrivals'])
    live = bus['departures'] if leave else bus['arrivals']
    end = bus['stops'][-1] if leave else bus['stops'][0]
    row = {**entry, 'id': f'{bus["id"]}@{entry["id"].split("@", 1)[-1]}', 'tripId': bus['id'], 'routeId': bus['route']['gtfsId'],
           'routeName': mapping.route_name(bus['route']) or entry['routeName'], 'mode': 'bus',
           'destination': end.get('name') or entry['destination'], 'scheduledAt': mapping.iso(scheduled[k]),
           'effectiveAt': mapping.iso(live[k]) if bus['delays'][k] is not None else None,
           'replacement': True, 'replacesTrain': entry['routeName']}
    row.pop('replacedByBus', None)
    if bus['stops'][k].get('bay'):
        row['platform'] = bus['stops'][k]['bay']
    return row


def board_rows(entries: list[dict], kind: str, names: dict[str, str], plan_for: Callable[[float], Optional[dict]]) -> list[dict]:
    """Rows of trains that a bus replaces at this station become that bus's rows (BUS 1896 to Logatec, its
    own line and trip), judged by each row's own service day: `plan_for(when)` gives the day's plan
    (scheduled.plan_at). A bus already listed on the board stands for its train itself."""
    listed = {e['tripId'] for e in entries}
    plans: dict = {}

    def plan_of(when: float) -> Optional[dict]:
        day = datetime.fromtimestamp(when, LOCAL).date()
        if day not in plans:
            plans[day] = plan_for(when)
        return plans[day]
    out = []
    for e in entries:
        plan = plan_of(_epoch(e['scheduledAt'])) if e['mode'] == 'rail' else None
        trip_sections = (plan or {}).get('sections', {}).get(e['tripId'])
        train = run_near(plan, e['tripId'], _epoch(e['scheduledAt'])) if trip_sections else None
        here = sz.station_key(names.get(e['stopId'], ''))
        keys = _keys(train) if train else []
        hit = section_at(trip_sections, keys.index(here), _epoch(e['scheduledAt']), kind) if here in keys else None
        if not hit:
            out.append(e)
            continue
        if hit['busTripId'] in listed:
            continue
        bus = plan['by_id'].get(hit['busTripId']) or run_near(plan, hit['busTripId'], hit['start'])
        out.append(bus_row(e, bus, kind, here) if bus else {**e, 'replacedByBus': True})
    out.sort(key=lambda e: _epoch(e['scheduledAt']))
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

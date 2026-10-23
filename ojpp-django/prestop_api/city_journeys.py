"""City buses OTP does not know, in journeys (E11).

derp-si's OTP cannot take the feeds supplement.py reads (Kranj's full timetable, the hand-kept Sevnica and Jesenice
feeds), so their buses are stitched in here, beside OTP's connections:

- inside a town (`town_options`): an earliest-arrival search over those feeds' runs, at most two rides, on foot to,
  between and from stops (the straight line times WALK_DETOUR, at OTP's walking speed);
- into or out of a town (`joined`): an OTP connection whose last (first) walk is long rides a city bus on from (to)
  the stop its last (first) ride ends (starts) at, when that arrives JOIN_GAIN sooner (lets the rider leave later);
- when none of OTP's connections comes near a city bus, one more OTP search to or from the town's railway station
  (`hub_search`, at most one per end of the journey, within the request's MAX_OTP_QUERIES), joined there.

Each option is made as OTP planConnection edges (PLAN_Q's legs), so build_journeys, stays, prices, alerts and the app
treat it as any other connection. Pages of earlier and later connections carry where the town search got to in
their cursors (`city:<epoch>:`): OTP's cursor knows nothing of these buses.
"""
import bisect
import hashlib
import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

from . import geometry, mapping, supplement, transfer_walk, trainlive
from . import journeys as planner
from . import operators as companies
from .upstream import UpstreamError

logger = logging.getLogger(__name__)
LOCAL = planner.LOCAL

WALK_SPEED = 1.33        # m/s, OTP's on the street (Insane: planner.INSANE_WALK_SPEED)
CITY_WALK = 1000         # m in a straight line from the start to a stop, or from a stop to the end
CHANGE_WALK = 400        # m between two stops at a change, or from where an OTP ride ends to a city bus
CHANGE_GAIN = 300        # s a change of bus must save over one bus
WALK_GAIN = 120          # s a bus must save over walking all the way
JOIN_WALK = 500          # m: OTP's first or last walk this long tries a city bus instead
JOIN_GAIN = 180          # s sooner a joined city bus must arrive (or later the rider may leave)
HUB_WALK = 1000          # m: every OTP connection leaves the rider this far from the end: search via the station
HUB_METERS = 300         # m: a railway station with a city bus stop this close is a town's hub
OPTIONS = 5              # town options per page, as many as OTP gives
WINDOW = 90 * 60         # s a page's town options reach past its time (or OTP's last connection on the page)
REACH = 24 * 3600        # s a page of earlier or later connections looks for one town option when its window has none
LONGEST = 4 * 3600       # s a town journey may take (how far before or after the window runs are read)
HUB_TTL = 300            # s a station search's answer is reused
ANCHOR = re.compile(r'city:(\d{9,11}):')

_lock = threading.Lock()
_cache: dict = {'feeds': None, 'days': {}, 'near': {}, 'along': {}, 'hubs': None}
_hub_answers: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------- runs and stops

def _feeds() -> dict:
    """The loaded supplement feeds; a reload clears what was worked out from the old ones."""
    feeds = supplement._feeds()
    with _lock:
        if _cache['feeds'] is not feeds:
            _cache.update(feeds=feeds, days={}, near={}, along={}, hubs=None)
    return feeds


def _day_runs(day: date) -> tuple[list[dict], dict]:
    """A service day's runs (timetable times, epoch) and stop -> [(run index, position)]."""
    feeds = _feeds()
    hit = _cache['days'].get(day)
    if hit is not None:
        return hit
    runs, at = [], {}
    base = supplement.day_start(day)
    for feed in feeds.values():
        for t in feed['trips'].values():
            if not supplement.runs(feed, t['serviceId'], day):
                continue
            for p, s in enumerate(t['stops']):
                at.setdefault(s['stopId'], []).append((len(runs), p))
            runs.append({'feed': feed, 'trip': t, 'day': day, 'agency': feed['routes'][t['routeId']]['agency']['gtfsId'],
                         'stops': [s['stopId'] for s in t['stops']],
                         'arr': [base + s['arrival'] for s in t['stops']], 'dep': [base + s['departure'] for s in t['stops']],
                         'board': [not s['pickup'] for s in t['stops']], 'alight': [not s['dropoff'] for s in t['stops']]})
    with _lock:
        if len(_cache['days']) > 8:
            _cache['days'].clear()
        _cache['days'][day] = (runs, at)
    return runs, at


def _live(run: dict, update: Optional[dict]) -> Optional[dict]:
    """The run with the realtime feed's times (supplement._live_times, as boards show them); None when cancelled."""
    if not update:
        return run
    times = supplement._live_times(run['trip'], run['day'], update)
    if all(t['realtimeState'] == 'CANCELED' for t in times):
        return None
    if not any(t['realtime'] for t in times):
        return run
    base = supplement.day_start(run['day'])
    skipped = [t['realtimeState'] == 'CANCELED' for t in times]
    dep = [base + t['realtimeDeparture'] for t in times]
    dep[0] = max(dep[0], run['dep'][0])  # a bus waits at its first stop for its time (mapping.EARLY_START)
    return {**run, 'live': True, 'arr': [base + t['realtimeArrival'] for t in times], 'dep': dep,
            'board': [b and not s for b, s in zip(run['board'], skipped)], 'alight': [a and not s for a, s in zip(run['alight'], skipped)]}


def _network(lo: float, hi: float, operators: list[str]) -> tuple[list[Optional[dict]], dict]:
    """Every run of the service days around lo..hi (None: cancelled, or not by a chosen operator) and the stop index."""
    allowed = set(companies.expand(operators)) if operators else None
    updates = trainlive.trip_updates()
    runs: list[Optional[dict]] = []
    at: dict[str, list] = {}
    day, last = datetime.fromtimestamp(lo, LOCAL).date() - timedelta(days=1), datetime.fromtimestamp(hi, LOCAL).date()
    while day <= last:
        day_runs, day_at = _day_runs(day)
        offset = len(runs)
        runs += [_live(r, updates.get(r['trip']['id'])) if allowed is None or r['agency'] in allowed else None for r in day_runs]
        for sid, refs in day_at.items():
            at.setdefault(sid, []).extend((offset + i, p) for i, p in refs)
        day += timedelta(days=1)
    return runs, at


def _stops() -> dict[str, dict]:
    return {sid: s for feed in _feeds().values() for sid, s in feed['stops'].items()}


def _near(lat: float, lon: float, limit: float) -> dict[str, float]:
    """City stops within `limit` m (straight line) of a point -> metres."""
    here = [lon, lat]
    out = {}
    for sid, s in _stops().items():
        if abs(s['lat'] - lat) < 0.02 and (d := geometry.distance(here, [s['lon'], s['lat']])) <= limit:
            out[sid] = d
    return out


def _neighbours(stop_id: str) -> dict[str, float]:
    """Stops a change at `stop_id` can walk to (itself included)."""
    hit = _cache['near'].get(stop_id)
    if hit is None:
        s = _stops().get(stop_id)
        hit = _near(s['lat'], s['lon'], CHANGE_WALK) if s else {}
        hit[stop_id] = 0.0
        _cache['near'][stop_id] = hit
    return hit


def _seconds(meters: float, speed: float) -> float:
    return meters * planner.WALK_DETOUR / speed


# ---------------------------------------------------------------- the search

def _options(runs: list, at: dict, access: dict, egress: dict, lo: float, hi: float, slack: float, speed: float,
             rides: int = 2) -> list[dict]:
    """The best ways from the start to the end leaving (on foot) between lo and hi: for every run boarded from a stop
    in `access`, the soonest arrival on it alone and with one change (`rides` 2). access/egress: stop -> metres from the
    start / to the end. An option: {'leave', 'arrive', 'rides': [(run, board, alight)], 'walks': [m before, between,
    after]}, times epoch; only those no other leaving as late beats (_best)."""
    walk = lambda m: _seconds(m, speed)  # noqa: E731
    # Each run reaching the end: for each position, the soonest arrival at the end getting off after it, and where.
    onward: dict[int, list] = {}
    for sid in egress:
        for ri, _ in at.get(sid, ()):
            r = runs[ri]
            if ri in onward or r is None:
                continue
            out, best = [None] * len(r['stops']), None
            for p in range(len(r['stops']) - 1, -1, -1):
                out[p] = best
                if r['alight'][p] and r['stops'][p] in egress and (best is None or r['arr'][p] + walk(egress[r['stops'][p]]) < best[0]):
                    best = (r['arr'][p] + walk(egress[r['stops'][p]]), p)
            onward[ri] = out
    # Second rides: stop -> (departure times, sorted; from each, the soonest arrival at the end of any departing then or later).
    second: dict[str, tuple[list, list]] = {}
    if rides > 1:
        rows: dict[str, list] = {}
        for ri, out in onward.items():
            r = runs[ri]
            for p, best in enumerate(out):
                if best is not None and r['board'][p]:
                    rows.setdefault(r['stops'][p], []).append((r['dep'][p], best[0], ri, p, best[1]))
        for sid, found in rows.items():
            found.sort(key=lambda row: row[0])
            suffix, best = [None] * len(found), None
            for k in range(len(found) - 1, -1, -1):
                if best is None or found[k][1] < best[1]:
                    best = found[k]
                suffix[k] = best
            second[sid] = ([row[0] for row in found], suffix)
    changes: dict[int, list] = {}

    def change_after(ri: int) -> list:
        """For each position of run ri: the best change getting off after it (arrival at the end, where, onto what)."""
        if ri not in changes:
            r = runs[ri]
            n = len(r['stops'])
            here: list = [None] * n
            for k in range(1, n):
                if not r['alight'][k]:
                    continue
                for c, meters in _neighbours(r['stops'][k]).items():
                    if c not in second:
                        continue
                    deps, suffix = second[c]
                    i = bisect.bisect_left(deps, r['arr'][k] + walk(meters) + slack)
                    if i < len(deps) and suffix[i][2] != ri and (here[k] is None or suffix[i][1] < here[k][0]):
                        here[k] = (suffix[i][1], k, meters, suffix[i])
            after, best = [None] * n, None
            for k in range(n - 1, -1, -1):
                after[k] = best
                if here[k] and (best is None or here[k][0] < best[0]):
                    best = here[k]
            changes[ri] = after
        return changes[ri]

    found = []
    for sid, meters in access.items():
        for ri, p in at.get(sid, ()):
            r = runs[ri]
            if r is None or not r['board'][p] or not lo <= (leave := r['dep'][p] - walk(meters)) <= hi:
                continue
            direct = onward[ri][p] if ri in onward else None
            if direct:
                found.append({'leave': leave, 'arrive': direct[0], 'rides': [(r, p, direct[1])], 'walks': [meters, egress[r['stops'][direct[1]]]]})
            if second and (via := change_after(ri)[p]):
                arrive, k, between, (_, _, ri2, p2, j2) = via
                r2 = runs[ri2]
                found.append({'leave': leave, 'arrive': arrive, 'rides': [(r, p, k), (r2, p2, j2)],
                              'walks': [meters, between, egress[r2['stops'][j2]]]})
    return _best(found)


def _best(found: list[dict]) -> list[dict]:
    """Options no other beats: one leaving as late or later, arriving as soon or sooner, with no more rides. A change is
    kept only when it arrives CHANGE_GAIN sooner than one bus leaving as late. In order of leaving."""
    found.sort(key=lambda o: (-o['leave'], len(o['rides']), o['arrive']))
    kept, best = [], {1: float('inf'), 2: float('inf')}
    for o in found:
        n = len(o['rides'])
        if o['arrive'] >= best[n] or (n == 2 and o['arrive'] > best[1] - CHANGE_GAIN):
            continue
        kept.append(o)
        best[n] = o['arrive']
    return kept[::-1]


def _speed(req: dict) -> float:
    return planner.INSANE_WALK_SPEED if req.get('riskMode') == 'insane' or req.get('wider') else WALK_SPEED


def _slack(req: dict) -> float:
    return max(0, req['minTransferSeconds'])


def town_options(req: dict, lo: float, hi: float) -> list[dict]:
    """Ways by city bus from the request's start to its end leaving between lo and hi, faster than walking."""
    o, d = req['origin'], req['destination']
    access, egress = _near(o['latitude'], o['longitude'], CITY_WALK), _near(d['latitude'], d['longitude'], CITY_WALK)
    if not access or not egress:
        return []
    runs, at = _network(lo, hi + LONGEST, req.get('operators') or [])
    speed = _speed(req)
    found = _options(runs, at, access, egress, lo, hi, _slack(req), speed, 1 if req.get('maxTransfers') == 0 else 2)
    on_foot = _seconds(geometry.distance([o['longitude'], o['latitude']], [d['longitude'], d['latitude']]), speed)
    return [x for x in found if x['arrive'] - x['leave'] + WALK_GAIN <= on_foot]


def _page(options: list[dict], req: dict, anchor: Optional[int], span: Optional[tuple]) -> tuple[list[dict], dict]:
    """The town options of this page and where the next and previous pages go on from ({'next', 'previous'}: epoch,
    leaving when departing, arriving when arriving by). The first page starts at the asked time; a page of later
    (earlier) connections after (before) its anchor. A page reaches WINDOW past its start or as far as OTP's
    connections on it go (`span`: their first and last time), and holds one option further on when none is within."""
    by = 'leave' if req['timeMode'] == 'departAt' else 'arrive'
    asked = req['dateTime'].timestamp()
    first = anchor is None
    later = req['timeMode'] == 'departAt' if first else req.get('pageDirection') != 'earlier'
    edge = asked if first else anchor
    if first:
        reach = planner.day_window(req)  # the asked day only, as OTP's own first page
    else:
        reach = REACH
    if later:
        pool = sorted((x for x in options if x[by] > edge or (first and x[by] == edge)), key=lambda x: x[by])
        cap = max(edge + WINDOW, span[1] if span else edge)
        taken = [x for x in pool if x[by] <= cap][:OPTIONS] or [x for x in pool[:1] if x[by] <= edge + reach]
        onward = taken[-1][by] if len(taken) == OPTIONS or (taken and taken[-1][by] > cap) else cap
        return taken, {'next': int(onward), 'previous': int(edge if first else (taken[0][by] if taken else edge))}
    pool = sorted((x for x in options if x[by] < edge or (first and x[by] == edge)), key=lambda x: -x[by])
    cap = min(edge - WINDOW, span[0] if span else edge)
    taken = [x for x in pool if x[by] >= cap][:OPTIONS] or [x for x in pool[:1] if x[by] >= edge - reach]
    onward = taken[-1][by] if len(taken) == OPTIONS or (taken and taken[-1][by] < cap) else cap
    return taken[::-1], {'previous': int(onward), 'next': int(edge if first else (taken[0][by] if taken else edge))}


def _search_range(req: dict, anchor: Optional[int]) -> tuple[float, float]:
    """Leaving times the town search covers for this page."""
    edge = req['dateTime'].timestamp() if anchor is None else anchor
    later = req['timeMode'] == 'departAt' if anchor is None else req.get('pageDirection') != 'earlier'
    arriving = req['timeMode'] == 'arriveBy'
    if later:
        return edge - (LONGEST if arriving else 0), edge + REACH
    return edge - REACH - (LONGEST if arriving else 0), edge


# ---------------------------------------------------------------- OTP-shaped legs

def _iso(t: float) -> str:
    return datetime.fromtimestamp(round(t), LOCAL).isoformat()


def _end(stop: dict) -> dict:
    return {'name': stop['name'], 'lat': stop['lat'], 'lon': stop['lon'], 'stop': {'gtfsId': stop['gtfsId'], 'platformCode': None},
            'vehicleRentalStation': None, 'rentalVehicle': None, 'vehicleParking': None}


def _spot(place: dict) -> dict:
    """An OTP leg end for a request place, or for an OTP leg's own end (kept as it is)."""
    if 'lat' in place:
        return place
    stop = {'gtfsId': place['stopId'], 'platformCode': None} if place.get('stopId') else None
    return {'name': place['name'], 'lat': place['latitude'], 'lon': place['longitude'], 'stop': stop,
            'vehicleRentalStation': None, 'rentalVehicle': None, 'vehicleParking': None}


def _walk(a: dict, b: dict, start: float, seconds: float, meters: float) -> dict:
    return {'mode': 'WALK', 'transitLeg': False, 'realtimeState': None, 'interlineWithPreviousLeg': False,
            'duration': round(seconds), 'distance': round(meters * planner.WALK_DETOUR, 1), 'rentedBike': False,
            'start': {'scheduledTime': _iso(start), 'estimated': None}, 'end': {'scheduledTime': _iso(start + seconds), 'estimated': None},
            'from': a, 'to': b, 'route': None, 'headsign': None, 'trip': None, 'alerts': [], 'intermediatePlaces': [],
            'legGeometry': {'points': mapping.encode_polyline([[a['lon'], a['lat']], [b['lon'], b['lat']]])}}


def _along(run: dict) -> tuple[list, list, list]:
    """The run's shape, its running length and each stop's distance along it (cached per trip)."""
    t = run['trip']
    hit = _cache['along'].get(t['id'])
    if hit is None:
        shape = run['feed']['shapes'].get(t['shapeId']) or []
        stops = [run['feed']['stops'][sid] for sid in run['stops']]
        if len(shape) < 2:
            shape = [[s['lon'], s['lat']] for s in stops]
        hit = _cache['along'][t['id']] = (shape, geometry.cumulative(shape), geometry.stop_distances(shape, stops))
    return hit


def _ride(run: dict, i: int, j: int) -> dict:
    """The OTP transit leg riding `run` from position i to j."""
    feed, t = run['feed'], run['trip']
    route = feed['routes'][t['routeId']]
    stops = [feed['stops'][sid] for sid in run['stops']]
    base = supplement.day_start(run['day'])
    live = run.get('live')
    shape, cum, along = _along(run)
    part = geometry.slice_between(shape, cum, along[i], along[j]) if along[j] > along[i] else []
    if len(part) < 2:
        part = [[s['lon'], s['lat']] for s in stops[i:j + 1]]
    return {
        'mode': route['mode'], 'transitLeg': True, 'realtimeState': 'UPDATED' if live else 'SCHEDULED', 'interlineWithPreviousLeg': False,
        'duration': round(run['arr'][j] - run['dep'][i]), 'distance': round(max(0.0, along[j] - along[i]), 1), 'rentedBike': False,
        'start': {'scheduledTime': _iso(base + t['stops'][i]['departure']), 'estimated': {'time': _iso(run['dep'][i])} if live else None},
        'end': {'scheduledTime': _iso(base + t['stops'][j]['arrival']), 'estimated': {'time': _iso(run['arr'][j])} if live else None},
        'from': _end(stops[i]), 'to': _end(stops[j]),
        'route': {'gtfsId': route['gtfsId'], 'shortName': route['shortName'], 'longName': route['longName'], 'mode': route['mode'],
                  'agency': {'gtfsId': route['agency']['gtfsId']}},
        'headsign': t['headsign'],
        'trip': {'gtfsId': t['id'], 'tripHeadsign': t['headsign'], 'blockId': None,
                 'departureStoptime': {'scheduledDeparture': t['stops'][0]['departure']},
                 'stoptimes': [{'stop': {'gtfsId': sid}} for sid in run['stops']]},
        'legGeometry': {'points': mapping.encode_polyline(part)}, 'alerts': [],
        'intermediatePlaces': [{'name': s['name'], 'lat': s['lat'], 'lon': s['lon'], 'stop': {'gtfsId': s['gtfsId']}} for s in stops[i + 1:j]],
    }


def _legs(option: dict, start: dict, end: dict, speed: float) -> list[dict]:
    """An option's OTP legs from `start` to `end` (OTP leg ends): on foot to the stop, ride, change, ride, on foot."""
    legs, here, t = [], start, option['leave']
    for k, ((run, i, j), meters) in enumerate(zip(option['rides'], option['walks'])):
        board = _end(run['feed']['stops'][run['stops'][i]])
        if meters >= 1:
            seconds = _seconds(meters, speed)
            legs.append(_walk(here, board, run['dep'][i] - seconds if k == 0 else t, seconds, meters))
        legs.append(_ride(run, i, j))
        here, t = _end(run['feed']['stops'][run['stops'][j]]), run['arr'][j]
    if option['walks'][-1] >= 1:
        legs.append(_walk(here, end, t, _seconds(option['walks'][-1], speed), option['walks'][-1]))
    return legs


def _edge(legs: list[dict]) -> dict:
    return {'node': {'walkTime': sum(l['duration'] for l in legs if not l.get('transitLeg') and l.get('mode') == 'WALK'), 'legs': legs, 'city': True}}


# ---------------------------------------------------------------- joined to OTP's connections

def _exit(leg: dict, end: dict) -> float:
    """Seconds between a train's track at `end` (one of the leg's ends) and the street (transfer_walk); none for a bus."""
    if mapping.mode_of((leg.get('route') or {}).get('mode')) != 'rail':
        return 0
    stop = (end.get('stop') or {}).get('gtfsId') or ''
    return transfer_walk.TRACK_EXIT_SECONDS.get(stop, transfer_walk.TRACK_EXIT_DEFAULT)


def _meters(legs: list[dict]) -> float:
    return sum(l.get('distance') or 0 for l in legs)


def _apart(end: dict, place: dict) -> float:
    """Metres in a straight line from an OTP leg end to a request place."""
    return geometry.distance([end['lon'], end['lat']], [place['longitude'], place['latitude']])


def _onward(legs: list[dict], req: dict, net: tuple) -> Optional[list[dict]]:
    """OTP's legs with what follows the last ride (a walk to the end, or nothing when OTP's search ended at a town's
    station, hub_search) replaced by a city bus from where that ride ends, when the bus arrives JOIN_GAIN sooner than
    walking from there would; None otherwise."""
    rides = [i for i, l in enumerate(legs) if l.get('transitLeg')]
    d = req['destination']
    if not rides or (far := _apart(legs[rides[-1]]['to'], d)) < JOIN_WALK:
        return None
    last = legs[rides[-1]]
    access, egress = _near(last['to']['lat'], last['to']['lon'], CHANGE_WALK), _near(d['latitude'], d['longitude'], CITY_WALK)
    if not access or not egress:
        return None
    arrived = planner._when(last['end'])
    ready = arrived + _slack(req) + _exit(last, last['to'])
    found = _options(*net, access, egress, ready, ready + LONGEST, 0, _speed(req), rides=1)
    best = min(found, key=lambda x: x['arrive'], default=None)
    if not best or best['arrive'] + JOIN_GAIN > arrived + _seconds(far, _speed(req)):
        return None
    if req['timeMode'] == 'arriveBy' and best['arrive'] > req['dateTime'].timestamp() + planner.TIME_SLACK:
        return None
    return legs[:rides[-1] + 1] + _legs(best, _spot(last['to']), _spot(d), _speed(req))


def _feeder(legs: list[dict], req: dict, net: tuple) -> Optional[list[dict]]:
    """OTP's legs with what comes before the first ride (a walk from the start, or nothing from a town's station)
    replaced by a city bus to where that ride starts, when the rider may then leave JOIN_GAIN later than walking there
    would let them; None otherwise."""
    rides = [i for i, l in enumerate(legs) if l.get('transitLeg')]
    o = req['origin']
    if not rides or (far := _apart(legs[rides[0]]['from'], o)) < JOIN_WALK:
        return None
    first = legs[rides[0]]
    access, egress = _near(o['latitude'], o['longitude'], CITY_WALK), _near(first['from']['lat'], first['from']['lon'], CHANGE_WALK)
    if not access or not egress:
        return None
    board = planner._when(first['start']) - _slack(req) - _exit(first, first['from'])
    found = [x for x in _options(*net, access, egress, board - LONGEST, board, 0, _speed(req), rides=1) if x['arrive'] <= board]
    best = max(found, key=lambda x: x['leave'], default=None)
    if not best or best['leave'] < board - _seconds(far, _speed(req)) + JOIN_GAIN:
        return None
    if req['timeMode'] == 'departAt' and best['leave'] < req['dateTime'].timestamp() - planner.TIME_SLACK:
        return None
    return _legs(best, _spot(o), _spot(first['from']), _speed(req)) + legs[rides[0]:]


def joined(edges: list[dict], req: dict, net: tuple) -> list[dict]:
    """City buses at either end of OTP's connections (one new connection per OTP one at most)."""
    out = []
    for e in edges:
        legs = e['node'].get('legs') or []
        if e['node'].get('city') or not any(l.get('transitLeg') for l in legs):
            continue
        fed = _feeder(legs, req, net)
        on = _onward(fed or legs, req, net)
        if fed or on:
            out.append(_edge(on or fed))
    return out


# ---------------------------------------------------------------- via a town's railway station

def _hubs() -> list[dict]:
    """Railway stations (stop markers) with a city bus stop within HUB_METERS."""
    from . import sources
    snap = sources.stops.peek()
    if snap is None:
        return []
    hit = _cache['hubs']
    if hit is not None and hit[0] is snap.value:
        return hit[1]
    found = [s for s in snap.value['list'] if 'rail' in (s.get('modes') or []) and _near(s['latitude'], s['longitude'], HUB_METERS)]
    _cache['hubs'] = (snap.value, found)
    return found


def _feeds_near(place: dict) -> set[str]:
    return {sid.split(':', 1)[0] for sid in _near(place['latitude'], place['longitude'], CITY_WALK)}


def _hub_for(place: dict, other: dict) -> Optional[dict]:
    """The station nearest `place` whose city buses serve it, when `other` is outside the town (no stop of the same
    city feed near it: inside a town the town search answers)."""
    feeds = _feeds_near(place)
    if not feeds or feeds & _feeds_near(other):
        return None
    here = [place['longitude'], place['latitude']]
    hubs = [h for h in _hubs() if {sid.split(':', 1)[0] for sid in _near(h['latitude'], h['longitude'], HUB_METERS)} & feeds
            and geometry.distance(here, [h['longitude'], h['latitude']]) >= JOIN_WALK]
    h = min(hubs, key=lambda h: geometry.distance(here, [h['longitude'], h['latitude']]), default=None)
    return {'name': h['name'], 'latitude': h['latitude'], 'longitude': h['longitude'], 'stopId': h['id']} if h else None


def _far(edges: list[dict], req: dict, end: str) -> bool:
    """Every OTP connection (with a ride) leaves the rider HUB_WALK or more from `end`'s place, or there are none."""
    place = req[end]
    for e in edges:
        legs = e['node'].get('legs') or []
        rides = [l for l in legs if l.get('transitLeg')]
        if not rides:
            continue
        stop = rides[-1]['to'] if end == 'destination' else rides[0]['from']
        if geometry.distance([stop['lon'], stop['lat']], [place['longitude'], place['latitude']]) < HUB_WALK:
            return False
    return True


def _ask(query, variables: dict) -> Optional[dict]:
    key = hashlib.sha1(json.dumps(variables, sort_keys=True, default=str).encode()).hexdigest()
    hit = _hub_answers.get(key)
    if hit and time.monotonic() - hit[0] < HUB_TTL:
        return hit[1]
    try:
        answer = query(planner.PLAN_Q, variables)
    except UpstreamError as e:
        logger.info('City station search failed: %r', e)
        return None
    _hub_answers[key] = (time.monotonic(), answer)
    if len(_hub_answers) > 200:
        for k, _ in sorted(_hub_answers.items(), key=lambda kv: kv[1][0])[:100]:
            _hub_answers.pop(k, None)
    return answer


def hub_search(edges: list[dict], req: dict, net: tuple, query, budget: int) -> list[dict]:
    """When OTP's connections all end (start) far from the town end of the journey: one more OTP search to (from) the
    town's railway station, its connections joined to a city bus there. At most one per end, within `budget`."""
    out = []
    speed, slack, arriving = _speed(req), _slack(req), req['timeMode'] == 'arriveBy'
    asked = req['dateTime'].timestamp()
    for end in ('destination', 'origin'):
        if budget <= 0 or not _far(edges, req, end):
            continue
        hub = _hub_for(req[end], req['origin' if end == 'destination' else 'destination'])
        if not hub:
            continue
        sub = {**req, end: hub, 'via': [], 'pageCursor': None}
        hub_stops, near = _near(hub['latitude'], hub['longitude'], CHANGE_WALK), _near(req[end]['latitude'], req[end]['longitude'], CITY_WALK)
        # City buses between the station and the place, leaving after the asked time or arriving by it: none, no search.
        lo, hi = (asked - LONGEST, asked) if arriving else (asked, asked + LONGEST)
        found = [x for x in _options(*net, *((hub_stops, near) if end == 'destination' else (near, hub_stops)), lo, hi, 0, speed, rides=1)
                 if not arriving or x['arrive'] <= asked]
        if not found:
            continue
        if end == 'destination' and arriving:
            # The last city bus from the station that arrives in time; OTP brings the rider there before it.
            sub['dateTime'] = datetime.fromtimestamp(max(x['leave'] for x in found) - slack, req['dateTime'].tzinfo)
        elif end == 'origin' and not arriving:
            # The first city bus to the station; OTP goes on from there after it.
            sub['dateTime'] = datetime.fromtimestamp(min(x['arrive'] for x in found) + slack, req['dateTime'].tzinfo)
        budget -= 1
        answer = _ask(query, planner.otp_variables(sub))
        for e in planner._edges(answer or {}):
            legs = (_onward if end == 'destination' else _feeder)(e['node']['legs'], req, net)
            if legs:
                out.append(_edge(legs))
    return out


# ---------------------------------------------------------------- the request

def take_anchor(req: dict) -> tuple[dict, Optional[int]]:
    """The request without the town search's mark on its cursor, and where that search got to (None: none)."""
    cursor = req.get('pageCursor') or ''
    m = ANCHOR.match(cursor)
    if not m:
        return req, None
    return {**req, 'pageCursor': cursor[m.end():] or None}, int(m[1])


def mark(page: dict, anchors: Optional[dict]) -> dict:
    """OTP's cursors with where the town search goes on from on each page."""
    if not anchors:
        return page
    return {k: f'city:{anchors[k]}:{v}' if v and anchors.get(k) is not None else v for k, v in page.items()}


def _times(edges: list[dict], req: dict) -> Optional[tuple]:
    key = (lambda n: planner._when(n['legs'][0]['start'])) if req['timeMode'] == 'departAt' else (lambda n: planner._when(n['legs'][-1]['end']))
    times = [key(e['node']) for e in edges if e['node'].get('legs')]
    return (min(times), max(times)) if times else None


def _signature(node: dict) -> tuple:
    """The runs a connection rides (line and the run's first departure), whichever stops it boards at."""
    return tuple((mapping.route_name(l.get('route') or {}), ((l.get('trip') or {}).get('departureStoptime') or {}).get('scheduledDeparture'),
                  l['start']['scheduledTime'][:10]) for l in node['legs'] if l.get('transitLeg'))


def _by_transit(node: dict) -> bool:
    legs = node.get('legs') or []
    return any(l.get('transitLeg') for l in legs) and all(l.get('transitLeg') or l.get('mode') == 'WALK' for l in legs)


def _beaten(node: dict, others: list[dict]) -> bool:
    """An OTP connection by public transport leaves as late, arrives as soon, with no more rides and no more walking
    (100 m)."""
    leave, arrive = planner._when(node['legs'][0]['start']), planner._when(node['legs'][-1]['end'])
    rides, walked = len(_signature(node)), _meters([l for l in node['legs'] if not l.get('transitLeg')])
    for o in others:
        legs = o['node']['legs']
        if (_by_transit(o['node']) and planner._when(legs[0]['start']) >= leave and planner._when(legs[-1]['end']) <= arrive
                and sum(1 for l in legs if l.get('transitLeg')) <= rides and _meters([l for l in legs if not l.get('transitLeg')]) <= walked + 100):
            return True
    return False


def add(data: dict, req: dict, anchor: Optional[int], query, budget: int) -> tuple[dict, Optional[dict]]:
    """`data` with the city bus connections after OTP's, and where the town search's pages go on from (None: there is
    no town search, cursors stay OTP's). `query`: the request's counted OTP query; `budget`: OTP queries left."""
    if 'bus' not in req['modes'] or req['via'] or not _feeds():
        return data, None
    starts, ends = _feeds_near(req['origin']), _feeds_near(req['destination'])
    if not starts and not ends:
        return data, None  # no city bus anywhere near: nothing to add
    edges = planner._edges(data)
    anchors = None
    found: list[dict] = []
    try:
        if starts & ends and (req.get('pageCursor') is None or anchor is not None):
            lo, hi = _search_range(req, anchor)
            options, anchors = _page(town_options(req, lo, hi), req, anchor, _times(edges, req))
            o, d = _spot(req['origin']), _spot(req['destination'])
            found += [_edge(_legs(x, o, d, _speed(req))) for x in options]
        times = _times(edges, req) or (req['dateTime'].timestamp(), req['dateTime'].timestamp())
        net = _network(times[0] - LONGEST, times[1] + 2 * LONGEST, req.get('operators') or [])
        found += joined(edges, req, net)
        if not req.get('pageCursor') and not found:
            found += hub_search(edges, req, net, query, min(2, budget))
    except (KeyError, IndexError, ValueError, TypeError) as e:  # a bad row in a feed must not cost OTP's answer
        logger.warning('City bus search failed: %r', e)
        return data, None
    seen = {_signature(e['node']) for e in edges}
    added = []
    for e in found:
        sig = _signature(e['node'])
        if sig in seen or _beaten(e['node'], edges):
            continue
        seen.add(sig)
        added.append(e)
    if not added:
        return data, anchors
    connection = dict(data.get('planConnection') or {})
    connection['edges'] = edges + added
    return {**data, 'planConnection': connection}, anchors

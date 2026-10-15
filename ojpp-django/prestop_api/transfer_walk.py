"""How long a change of vehicle really takes on foot, and whether it is comfortable or tight (A4).

OTP walks between two stops on OpenStreetMap, but where a change stays at one feed stop it walks nothing, and a
namesake stop across the road is a few metres off: Ljubljana AP is one stop for its 46 bays, a railway station one
stop for all its tracks. The walk OTP gives is the floor; on top of it, by station layout:

- the stop for the other direction across the road (same name, close by, not merged with it): crossing the road;
- a railway station: track to track through the underpass, when both trains' tracks are known (tracks.py, the day's
  board or the usual track); from a known track out to the station front when the change is to a bus;
- a bus station with mapped bays (Ljubljana AP): from where the bus sets down to the bay the next one leaves from.

OTP's GraphQL takes one transfer slack per request (the rider's buffer), not one per stop, so these times rate the
connections OTP found; per-stop times would need transfers.txt in the OTP build, which is not ours.
"""
import math
import re
from typing import Optional

from . import mapping, platforms, stopgroups

# ---------------------------------------------------------------- the numbers, all in one place
WALK_SPEED = 1.2           # m/s inside a station or between bays, with luggage (OTP walks 1.33 on the street)
DETOUR = 1.4               # metres walked per straight-line metre between bays (round the yard, not across it)
CROSSING_SECONDS = 60      # waiting at and crossing the road to the stop for the other direction
NAMESAKE_METERS = 120      # the stop of the same name this close, passed the other way, is across the road
OPPOSITE = 0.7             # cosine: travel through two stops this close to opposite is the other direction
# A bus station's stops: buses come in one way and leave the other, but its stops are bays, not across a road.
BUS_STATION = re.compile(r'\b(ap|avtobusna postaja|avtobusni postaji)\b')
SAME_TRACK_SECONDS = 30    # off one train, onto another at the same platform
LJUBLJANA_RAIL = 'IJPP:1122804'
TRACK_CHANGE_SECONDS = {LJUBLJANA_RAIL: 240}  # track to track through the underpass; long platforms in Ljubljana
TRACK_CHANGE_DEFAULT = 150
TRACK_EXIT_SECONDS = {LJUBLJANA_RAIL: 150}    # from a platform out to the station front (and the bus station)
TRACK_EXIT_DEFAULT = 90
FRONT_TRACKS = {'1'}       # the track at the station building: no underpass
# Rating: a change is comfortable with at least the rider's buffer (minTransferSeconds) to spare after the walk,
# tight with less, missed when the walk alone takes longer than there is.


def rate(available: float, walk: float, buffer: float) -> tuple[str, bool, str]:
    """(status, meets the buffer, rating) of a change in normal mode: safe/comfortable, tight, or missed (tight)."""
    meets = available >= walk + buffer
    status = 'missed' if available < walk else ('safe' if meets else 'tight')
    return status, meets, rating_of(status)


def rating_of(status: str) -> str:
    return 'comfortable' if status == 'safe' else 'tight'


def _meters(a: dict, b: dict) -> float:
    kx = 111_320 * math.cos(math.radians(a['latitude']))
    return math.hypot((a['longitude'] - b['longitude']) * kx, (a['latitude'] - b['latitude']) * 110_574)


def _on_foot(meters: float) -> float:
    return meters * DETOUR / WALK_SPEED


def _same_side(a: str, b: str) -> bool:
    """One stop, or stops merged into one (stopgroups: the same direction only, never opposite sides)."""
    from .sources import stop_group
    return a == b or b in stop_group(a)


def _opposite_ways(a: str, b: str) -> bool:
    """Vehicles pass the two stops in opposite directions (and never the same way): the stop across the road, not
    another bay of a bus station or the next pole along the kerb."""
    from .sources import stop_directions
    wa, wb = stop_directions(a), stop_directions(b)
    dots = [x[0] * y[0] + x[1] * y[1] for x in wa for y in wb]
    return bool(dots) and min(dots) <= -OPPOSITE and max(dots) < OPPOSITE


def _bay_point(station: str, platform: Optional[str]) -> Optional[dict]:
    bays = platforms.bays(station)
    ref = platforms.first_bay(platform or '', bays)
    if not ref:
        return None
    return {'latitude': bays[ref]['lat'], 'longitude': bays[ref]['lon']}


def walk(arrive: dict, depart: dict, otp_walk: float, arrive_track: Optional[str] = None) -> tuple[int, str]:
    """(seconds, kind) on foot from leaving `arrive` (a ride, as journeys builds it) to boarding `depart`. `otp_walk`:
    OTP's walk legs between them; `arrive_track`: the arriving train's track there. Kinds: same-stop, same-side,
    cross-road, track, track-to-bus, bus-to-track, bay, walk."""
    a, b = arrive['destination'], depart['origin']
    a_id, b_id = a.get('stopId'), b.get('stopId')
    rail_a, rail_b = arrive['mode'] == 'rail', depart['mode'] == 'rail'
    depart_track = depart.get('platform') if rail_b else None
    seconds, kind = float(otp_walk), 'walk'
    if not a_id or not b_id:
        return round(seconds), kind
    if rail_a and rail_b:
        if _same_side(a_id, b_id) and arrive_track and depart_track:
            change = SAME_TRACK_SECONDS if arrive_track == depart_track else TRACK_CHANGE_SECONDS.get(a_id, TRACK_CHANGE_DEFAULT)
            return round(max(seconds, change)), 'track'
        return round(seconds), 'same-stop' if a_id == b_id else kind
    if rail_a != rail_b:
        # A train and a bus: out to the station front from a known track, and to the bus's bay at a bus station.
        station, track = (a_id, arrive_track) if rail_a else (b_id, depart_track)
        if track and track not in FRONT_TRACKS:
            seconds += TRACK_EXIT_SECONDS.get(station, TRACK_EXIT_DEFAULT)
        bus_end = depart if rail_a else arrive
        bus_stop = b if rail_a else a
        bay = _bay_point(bus_stop['stopId'], bus_end.get('platform')) if bus_stop['stopId'] in platforms.STATIONS else None
        if bay:
            seconds += _on_foot(_meters(bus_stop, bay))
        return round(seconds), ('track-to-bus' if rail_a else 'bus-to-track') if (track or bay) else kind
    # Bus to bus.
    if b_id in platforms.STATIONS or a_id in platforms.STATIONS:
        station = b_id if b_id in platforms.STATIONS else a_id
        bay = _bay_point(station, depart.get('platform')) if b_id == station else None
        if bay:
            # Buses set down at the station's own stop (no source gives arrival bays): from there to the bay; from
            # another stop, OTP's walk to the station and then on to the bay.
            inside = _on_foot(_meters(a if a_id == station else b, bay))
            return round(max(seconds, inside) if a_id == station else seconds + inside), 'bay'
    if a_id == b_id:
        return round(seconds), 'same-stop'
    if _same_side(a_id, b_id):
        return round(seconds), 'same-side'
    across = stopgroups.similar(a.get('name') or '', b.get('name') or '') and not BUS_STATION.search(mapping.fold(a.get('name') or ''))
    if across and _meters(a, b) <= NAMESAKE_METERS and _opposite_ways(a_id, b_id):
        return round(seconds + CROSSING_SECONDS), 'cross-road'
    return round(seconds), kind

"""Where a bus stop belongs: on the road the lines through it actually use (M9).

Pure functions; `manage.py place_stops` feeds them every bus pattern's repaired road shape and writes the answers to
`data/stop_places.json`, which `stopfix` applies (after `stop_overrides.csv`, before the old road snap). The cache is
keyed by the stop's feed position (`stopfix.snap_key`), so applying it twice changes nothing and a stop the feed moves
is placed afresh.

Rules (spec 2026-11-04, "Placement (M9)"):
- Trust: a hand row in `stop_overrides.csv` wins (the command skips those stops), then OSM's pole tagged with the
  stop's id (`gtfs:stop_id:<feed>`) when it stands by the line on the right side, then the lines.
- Each pattern through the stop gives the point where its road shape passes the stop (the projection that keeps stop
  order, `geometry.project_stops`) and its direction of travel there. Patterns that pass more than AGREE metres apart
  use different roads: a person looks.
- One way: the kerb on the right of travel (KERB metres off the road's centre line). Both ways (a two-way pole): the
  centre line.
- A pole the feed puts clearly on the left of travel (more than SIDE_SLACK metres) is not moved: it would cross the road.
- Moves only MIN_MOVE..MAX_MOVE metres: closer is already fine, further is listed for a person.
"""
import math
from typing import Optional

from . import geometry

KY = geometry.KY
KERB = 3.0         # m from a road's centre line to its right-hand kerb (a two-lane road is ~6-7 m wide)
AGREE = 12.0       # m: patterns whose road points are further apart than this use different roads
TWO_WAY = 120.0    # degrees: patterns this far apart in heading pass the pole in opposite directions
SIDE_SLACK = 4.0   # m left of the centre line a pole may stand (GPS noise) before it counts as the other side
POLE_NEAR = 25.0   # m: OSM's tagged pole counts only this close to the lines' road point
MIN_MOVE = 8.0     # m: a stop closer than this to its place stays where it is
MAX_MOVE = 60.0    # m: a longer move is listed for a person, not applied
LOOK = 15.0        # m before and after the stop over which the direction of travel is read


def _kx(lat: float) -> float:
    return KY * math.cos(math.radians(lat))


def passing(coords: list, cum: list[float], along: float) -> tuple[float, float, float]:
    """(lat, lon, heading) where a shape passes a stop projected at `along` metres; heading in degrees from north."""
    lon, lat = geometry.point_at(coords, cum, along)
    a = geometry.point_at(coords, cum, max(0.0, along - LOOK))
    b = geometry.point_at(coords, cum, min(cum[-1], along + LOOK))
    heading = (math.degrees(math.atan2((b[0] - a[0]) * _kx(lat), (b[1] - a[1]) * KY)) + 360) % 360
    return lat, lon, heading


def _offset(lat: float, lon: float, heading: float, metres: float) -> tuple[float, float]:
    """The point `metres` to the right of travel (negative: left)."""
    side = math.radians(heading + 90)
    return lat + metres * math.cos(side) / KY, lon + metres * math.sin(side) / _kx(lat)


def _right_of(lat: float, lon: float, heading: float, plat: float, plon: float) -> float:
    """Signed metres of a point right of the line through (lat, lon) heading `heading` (negative: left)."""
    side = math.radians(heading + 90)
    return (plon - lon) * _kx(lat) * math.sin(side) + (plat - lat) * KY * math.cos(side)


def _metres(lat: float, lon: float, lat2: float, lon2: float) -> float:
    return math.hypot((lon2 - lon) * _kx(lat), (lat2 - lat) * KY)


def _gap(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _mean_heading(headings: list[float]) -> float:
    x = sum(math.sin(math.radians(h)) for h in headings)
    y = sum(math.cos(math.radians(h)) for h in headings)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def place(lat: float, lon: float, passes: list[tuple[float, float, float]], pole: Optional[tuple[float, float]] = None) -> dict:
    """Where a stop at (lat, lon) belongs, given where each pattern through it passes (`passing`) and OSM's tagged
    pole. {'lat', 'lon', 'metres', 'why', 'move'}: `move` is True only for a move this module applies; otherwise
    `why` says what a person should know ('no line', 'lines disagree', 'other side', 'close', 'far')."""
    out = {'lat': lat, 'lon': lon, 'metres': 0.0, 'move': False}
    if not passes:
        return {**out, 'why': 'no line'}
    mlat = sum(p[0] for p in passes) / len(passes)
    mlon = sum(p[1] for p in passes) / len(passes)
    if max(_metres(mlat, mlon, p[0], p[1]) for p in passes) > AGREE:
        return {**out, 'why': 'lines disagree'}
    headings = [p[2] for p in passes]
    two_way = any(_gap(a, b) > TWO_WAY for a in headings for b in headings)
    if two_way:
        target, why = (mlat, mlon), 'two-way centre'
    else:
        heading = _mean_heading(headings)
        if _right_of(mlat, mlon, heading, lat, lon) < -SIDE_SLACK:
            return {**out, 'metres': round(_metres(lat, lon, mlat, mlon), 1), 'why': 'other side'}
        target, why = _offset(mlat, mlon, heading, KERB), 'right kerb'
        if pole and _metres(mlat, mlon, *pole) <= POLE_NEAR and _right_of(mlat, mlon, heading, *pole) >= -SIDE_SLACK:
            target, why = pole, 'osm pole'
    if two_way and pole and _metres(mlat, mlon, *pole) <= POLE_NEAR:
        target, why = pole, 'osm pole'
    metres = _metres(lat, lon, *target)
    out = {'lat': round(target[0], 6), 'lon': round(target[1], 6), 'metres': round(metres, 1), 'why': why}
    if metres < MIN_MOVE:
        return {**out, 'lat': lat, 'lon': lon, 'why': 'close', 'move': False}
    if metres > MAX_MOVE:
        return {**out, 'why': 'far', 'move': False}
    return {**out, 'move': True}

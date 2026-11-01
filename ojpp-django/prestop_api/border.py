"""Slovenia's border, for what must stay inside it (data/slovenia.json, scripts/build-slovenia-border.py)."""
import json
import math
from functools import lru_cache
from pathlib import Path

from . import geometry

DATA = Path(__file__).resolve().parent / 'data' / 'slovenia.json'
BAND = 0.01   # degrees of latitude per band of edges: a point only looks at the few edges level with it
STEP = 10.0   # m between the points tested along a line
MARGIN = 25.0 # m a cut line stops short of the border: more than the file's own tolerance, so it is inside the real one


@lru_cache(maxsize=1)
def _bands() -> dict[int, list[tuple[float, float, float, float]]]:
    bands: dict[int, list] = {}
    for ring in json.loads(DATA.read_text(encoding='utf-8'))['rings']:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            for band in range(int(min(y1, y2) / BAND), int(max(y1, y2) / BAND) + 1):
                bands.setdefault(band, []).append((x1, y1, x2, y2))
    return bands


def contains(lon: float, lat: float) -> bool:
    """Inside Slovenia: an odd number of border edges lies to the east of the point."""
    inside = False
    for x1, y1, x2, y2 in _bands().get(int(lat / BAND), ()):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def until_abroad(coords: list) -> list:
    """`coords` from their start up to MARGIN before they first leave Slovenia (whole if they never do); empty when they
    start outside it."""
    points = geometry.densify(coords, STEP)
    for i, point in enumerate(points):
        if not contains(point[0], point[1]):
            return points[:max(0, i - math.ceil(MARGIN / STEP))]
    return points


def inside_parts(coords: list) -> list[list]:
    """The stretches of `coords` in Slovenia, each stopping MARGIN short of the border; `coords` itself when it never
    leaves, so a line that stays home keeps its points."""
    points = geometry.densify(coords, STEP)
    flags = [contains(p[0], p[1]) for p in points]
    if all(flags):
        return [coords]
    short = math.ceil(MARGIN / STEP)
    parts: list[list] = []
    i = 0
    while i < len(points):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(points) and flags[j + 1]:
            j += 1
        a, b = i + (short if i > 0 else 0), j - (short if j + 1 < len(points) else 0)
        if b > a:
            parts.append(points[a:b + 1])
        i = j + 1
    return parts

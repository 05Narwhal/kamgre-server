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
DIP = 40.0    # m: a stretch that goes no deeper than this past the border, with Slovenia on both sides, is the file's roughness
              # (a track running along the border, e.g. Sv. Rok ob Sotli - Rogatec), not a crossing


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


def _depth(lon: float, lat: float) -> float:
    """Metres from the point to the nearest border edge (those within a band either side of it)."""
    kx = math.cos(math.radians(lat)) * geometry.KY
    best = math.inf
    for band in (int(lat / BAND) - 1, int(lat / BAND), int(lat / BAND) + 1):
        for x1, y1, x2, y2 in _bands().get(band, ()):
            ax, ay, bx, by = (x1 - lon) * kx, (y1 - lat) * geometry.KY, (x2 - lon) * kx, (y2 - lat) * geometry.KY
            dx, dy = bx - ax, by - ay
            along = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(ax + along * dx, ay + along * dy))
    return best


def _inside(points: list) -> list[bool]:
    """Per point: in Slovenia. A stretch outside that is shallow (DIP) and has Slovenia on both sides counts as inside."""
    flags = [contains(p[0], p[1]) for p in points]
    i = 0
    while i < len(flags):
        if flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(flags) and not flags[j + 1]:
            j += 1
        if i > 0 and j + 1 < len(flags) and max(_depth(points[k][0], points[k][1]) for k in range(i, j + 1)) <= DIP:
            flags[i:j + 1] = [True] * (j - i + 1)
        i = j + 1
    return flags


def until_abroad(coords: list) -> list:
    """`coords` from their start up to MARGIN before they first leave Slovenia (whole if they never do); empty when they
    start outside it."""
    points = geometry.densify(coords, STEP)
    for i, inside in enumerate(_inside(points)):
        if not inside:
            return points[:max(0, i - math.ceil(MARGIN / STEP))]
    return points


def inside_parts(coords: list) -> list[list]:
    """The stretches of `coords` in Slovenia, each stopping MARGIN short of the border; `coords` itself when it never
    leaves, so a line that stays home keeps its points."""
    points = geometry.densify(coords, STEP)
    flags = _inside(points)
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

"""Stops with no trip in the next days leave the map and search (spec 2026-10-23 E7).

A marker none of whose member stops has a departure or arrival in the next SERVICE_DAYS days is left out of
/stops and place search, and so of the prerendered station pages and the sitemap (scripts/prerender.mjs reads
/stops). A stop counts as served when OTP's board lists a trip there (asked in batches of BATCH stops), a trip of
a feed read here serves it (supplement.py), an SŽ replacement bus of today's or tomorrow's plan stops there, or the
collector saw a vehicle of one of its lines live in the last SERVICE_DAYS days (TripDelay). The check takes ~25 s
of OTP time for the whole country, so it runs in the cache warmer every few hours; service coming back brings a
stop back with the next one.

Its board still answers (saved stops and links keep working) and `/stops?stopId=` still finds it. Until the first
check, and for stops the check has not seen yet, nothing is hidden; railway stations and `keep` rows in
stop_overrides.csv never are.
"""
import json
import time
from datetime import timedelta
from typing import Optional

from . import sources, stopfix, supplement, trips
from .upstream import Cached, otp

SERVICE_DAYS = 7
BATCH = 200  # stops per OTP query (200 boards of one departure: ~0.4 s)


def members(marker: dict) -> list[str]:
    return marker.get('memberIds') or [marker['id']]


def departures(ids: list[str], most: int, batch: int = BATCH) -> dict[str, int]:
    """Stop id -> departures and arrivals in the next SERVICE_DAYS days, at most `most` (0 for a stop OTP lacks)."""
    out, now = {}, int(time.time())
    for i in range(0, len(ids), batch):
        part = ids[i:i + batch]
        q = '{ ' + ' '.join(
            f's{k}: stop(id: {json.dumps(sid)}) {{ stoptimesWithoutPatterns(startTime: {now}, timeRange: {SERVICE_DAYS * 86400}, '
            f'numberOfDepartures: {most}, omitNonPickups: false) {{ serviceDay }} }}' for k, sid in enumerate(part)) + ' }'
        data = otp().query(q, timeout=(5, 120))
        for k, sid in enumerate(part):
            stop = data.get(f's{k}')
            out[sid] = len(stop.get('stoptimesWithoutPatterns') or []) if stop else 0
    return out


def live_routes() -> set[str]:
    """Routes the collector saw a vehicle of in the last SERVICE_DAYS days."""
    from prestop_statistics.models import TripDelay
    since = trips.service_day() - timedelta(days=SERVICE_DAYS)
    return set(TripDelay.objects.filter(service_date__gte=since).values_list('route_id', flat=True).distinct())


def served_stops(snap: dict) -> tuple[set, dict]:
    """(stop ids with a trip in the next SERVICE_DAYS days, stop id -> why one has none)."""
    today = trips.service_day()
    by_stop = sources.patterns.get().value['by_stop']
    ids = [s['id'] for s in snap['all']]
    served = supplement.running_stops(today + timedelta(days=i) for i in range(SERVICE_DAYS))
    counts = departures([i for i in ids if i in by_stop and not supplement.owns(i)], 1)
    served |= {i for i, n in counts.items() if n}
    seen = live_routes()
    served |= {i for i in ids if (snap['routes'].get(i) or set()) & seen}
    # SŽ's replacement buses (closures.py, sztimetables.py) are not in OTP: today's and tomorrow's plans, kept warm.
    from . import scheduled
    for day in (today, today + timedelta(days=1)):
        plan = scheduled.day_plan(day) or {}
        served |= {s.get('gtfsId') for bus in plan.get('synthetic') or [] for s in bus.get('stops') or []}
    why = {i: 'no OTP pattern' if i not in by_stop and not supplement.owns(i) else f'no trip in {SERVICE_DAYS} days'
           for i in ids if i not in served}
    return served, why


def _load() -> dict:
    try:
        served_ids, why = served_stops(sources.stops.get().value)
    finally:
        from django.db import connection
        connection.close()  # the warmer's thread for it (see `warm`)
    return {'served': served_ids, 'unserved': set(why)}


served = Cached(_load, ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)


def warm():
    """From the cache warmer: starts the check in a thread of its own when it is due, so the warmer's other caches
    are not held up for its ~25 s."""
    snap = served.peek()
    if snap is None or snap.age >= served.ttl * 0.8 or snap.error:
        served._refresh_in_background()
_memo: dict = {'of': None, 'ids': frozenset()}


def empty_markers(markers: list[dict], unserved: set, keep: set) -> set[str]:
    """Ids of the markers all of whose member stops were checked and have no trip, none of them kept. A railway
    station stays: SŽ's replacement buses can stop there with no trip in OTP (sztimetables.py, closures.py)."""
    return {m['id'] for m in markers if 'rail' not in m['modes'] and all(i in unserved for i in members(m)) and not keep & set(members(m))}


def hidden() -> frozenset:
    """Marker ids /stops and search leave out (empty when the check or the stop index is not loaded yet)."""
    index, check = sources.stops.peek(), served.peek()
    if not index or not check:
        return frozenset()
    of = (index.value, check.value)
    if _memo['of'] is None or _memo['of'][0] is not of[0] or _memo['of'][1] is not of[1]:
        keep = stopfix.tables()[0]['keep']
        _memo.update(of=of, ids=frozenset(empty_markers(index.value['list'], check.value['unserved'], keep)))
    return _memo['ids']


def markers(held: Optional[str] = None) -> list[dict]:
    """The map's stop markers without the empty ones; with `held`, only the marker holding that stop, empty or not."""
    listed = sources.stops.get().value['list']
    if held:
        return [m for m in listed if held in members(m)]
    gone = hidden()
    return [m for m in listed if m['id'] not in gone] if gone else listed

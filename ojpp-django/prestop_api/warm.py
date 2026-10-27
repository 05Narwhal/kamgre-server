"""Keeps the slow-to-build caches fresh while people use the app, so no request waits on a rebuild.

The day's train timetable (two whole-day OTP queries, 3–11 s) expires every two minutes, and
the stop and route indexes every hour. A request that finds one expired used to rebuild it
while the person waited: a station board took 11 s instead of 0.3 s. A daemon thread, started
by the first API request, refreshes each cache shortly before it expires, but only while a
request arrived in the last `ACTIVE` seconds: an idle server leaves the public OTP alone.
"""
import logging
import threading
import time
from datetime import timedelta

logger = logging.getLogger(__name__)

TICK = 20          # s between checks
ACTIVE = 30 * 60   # s after the last request that the caches are kept warm

_started = threading.Lock()
_last_request = 0.0


def touch():
    """Called on every API request: notes the activity and starts the thread once per process."""
    global _last_request
    _last_request = time.time()
    if _started.acquire(blocking=False):
        threading.Thread(target=_run, daemon=True, name='prestop-warm').start()


def boot():
    """Starts warming as the server process starts (wsgi.py), if PRESTOP_WARM is on."""
    from django.conf import settings
    if getattr(settings, 'PRESTOP_WARM', False):
        touch()


def caches():
    from . import scheduled, sources, supplement
    tomorrow = scheduled.service_day() + timedelta(days=1)
    # Live vehicles too: after ~30 s without a request their next read rebuilds them (and maybe the timetable).
    # Tomorrow's trains: the date people look up most after today (a 9 s load otherwise).
    # The operator GTFS that replaces OTP's broken Kranj timetable (supplement.py) before the indexes built on it.
    from . import operator_notices
    return [scheduled.timetable, scheduled.shapes, supplement.gtfs, sources.stops, sources.routes, sources.alerts_raw, sources.vehicles,
            scheduled.day_timetable(tomorrow), scheduled.day_timetable(tomorrow + timedelta(days=1)), operator_notices.arriva, operator_notices.sz_news]


def plans():
    """Today's, tomorrow's and the next day's replacement plans, worked out ahead of the boards and journeys that need
    them, with SŽ's replacement timetables as last read (at most once a minute, sztimetables.load)."""
    from . import scheduled, sztimetables
    sztimetables.load()
    today = scheduled.service_day()
    for day in (today, today + timedelta(days=1), today + timedelta(days=2)):
        scheduled.day_plan(day, refresh=True)


def tick(now: float):
    """One round: refresh what is about to expire, if the app is in use."""
    if now - _last_request > ACTIVE:
        return
    from . import predictions
    try:
        predictions.learned_table()  # the learned stays, before the slow caches: a first search must not find them missing
    finally:
        from django.db import connection
        connection.close()  # this thread's own connection
    for cache in caches():
        cache.warm()
    from . import zamudil
    if zamudil.enabled():  # zamudil.si's copies that are due, beside the warming (one poll at a time)
        threading.Thread(target=zamudil.poll, daemon=True, name='prestop-zamudil').start()
    from . import sources
    sources.warm_alerts()  # the alert lists boards and journeys share, rebuilt here instead of in a request
    plans()
    from . import variants
    variants.table()  # route groups (contract 4): rebuilt only when routes or patterns were reloaded
    from . import stopservice
    stopservice.warm()  # stops with a trip in the next days, in a thread of its own (~25 s of OTP every few hours)


def _run():
    while True:
        try:
            tick(time.time())
        except Exception as e:  # never let the warmer die
            logger.warning('Cache warmer: %r', e)
        time.sleep(TICK)

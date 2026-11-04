"""Has a city feed gone quiet? An alarm in /health, so an expired timetable can't empty boards silently.

Marprom's published weekday service ended on 31 August and nothing replaced it: every stop was empty Monday to Friday
for two months and nothing said so, since its Saturdays still ran and the feed looked healthy. So the cache warmer asks,
every few hours, how many trips each city network has on the next and the last weekday and Saturday of the coming
WINDOW days (the last ones call a feed that is about to end, as citytt.health does). Public holidays are not asked.

A feed read here (supplement.py: hand-kept folders, Kranj's own file) counts from its own calendar, the rest from OTP.
`empty` lists each day a feed normally runs and has no trip; `server:top` shows it. It informs, nothing changes for riders.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from . import mapping, supplement
from .sztimetables import holiday
from .upstream import Cached, otp

log = logging.getLogger(__name__)

WINDOW = 14  # days ahead

# Every city network (spec 2026-11-04): does it normally run on Saturdays? All run on weekdays. False for CELEBUS, MONM
# and Postojna is only what their feeds show so far: M-A2 checks each against its operator's timetable.
FEEDS = {'LPP': True, 'MARPROM': True, 'CELEBUS': False, 'MONM': False, 'MONG': True, 'MOKoper': True, 'MOKranj': True, 'MOKrsko': True,
         'MOMS': True, 'MOVelenje': True, 'Postojna': False, 'Ptuj': True, 'Brezice': True, 'Sevnica': False, 'Jesenice': True,
         'Piran': True}


def days_to_check(today: date) -> list[tuple[str, date]]:
    """(kind, day): the first and the last working weekday and Saturday of the window after today."""
    window = [today + timedelta(days=n) for n in range(1, WINDOW + 1)]
    window = [d for d in window if not holiday(d)]
    out = []
    for kind, of_kind in (('weekday', lambda d: d.weekday() < 5), ('saturday', lambda d: d.weekday() == 5)):
        days = [d for d in window if of_kind(d)]
        out += [(kind, d) for d in dict.fromkeys(days[:1] + days[-1:])]
    return out


def _from_otp(names: list[str], days: list[date]) -> dict[str, list[int]]:
    counts = {name: [0] * len(days) for name in names}
    asked = ' '.join(f'd{n}: tripsForDate(serviceDate: "{d:%Y%m%d}") {{ gtfsId }}' for n, d in enumerate(days))
    feeds = ', '.join(f'"{name}"' for name in names)
    data = otp().query('{ routes(feeds: [%s]) { gtfsId patterns { %s } } }' % (feeds, asked), timeout=(5, 120))
    for route in data.get('routes') or []:
        name = route['gtfsId'].split(':', 1)[0]
        if name in counts:
            for pattern in route.get('patterns') or []:
                for n in range(len(days)):
                    counts[name][n] += len(pattern.get(f'd{n}') or [])
    return counts


def check(today: date) -> dict:
    wanted = days_to_check(today)
    days = [d for _, d in wanted]
    own = supplement.whole(supplement._feeds())  # a correction (replaces.txt) holds a few lines: the feed counts from OTP
    trips = {name: [sum(1 for t in own[name]['trips'].values() if supplement.runs(own[name], t['serviceId'], d)) for d in days]
             for name in FEEDS if name in own}
    others = [name for name in FEEDS if name not in own]
    if others:
        trips.update(_from_otp(others, days))
    empty = [{'feed': name, 'kind': kind, 'day': d.isoformat()} for name, saturdays in FEEDS.items() for n, (kind, d) in enumerate(wanted)
             if not trips[name][n] and (kind == 'weekday' or saturdays)]
    if empty:
        log.warning('City feeds with no trips on a day they normally run: %s', empty)
    return {'checkedAt': mapping.iso(datetime.now(supplement.LOCAL).timestamp()), 'days': [d.isoformat() for d in days], 'trips': trips, 'empty': empty}


checked = Cached(lambda: check(datetime.now(supplement.LOCAL).date()), ttl=6 * 3600, max_stale=48 * 3600, revalidate=6 * 3600)


def warm() -> None:
    """From the cache warmer, in a thread of its own."""
    snap = checked.peek()
    if snap is None or snap.age >= checked.ttl * 0.8 or snap.error:
        checked._refresh_in_background()


def latest() -> Optional[dict]:
    """The last check, or None before the first (/health must not wait for OTP)."""
    snap = checked.peek()
    return snap.value if snap else None

"""SŽ's replacement timetables: the PDF each closure notice links ("Vozni red nadomestnega prevoza").

A separate job (`manage.py szpdf_sync`) reads every PDF into one JSON file per PDF in
`PRESTOP_SZ_TIMETABLES_DIR`, `<sha256>.json`, and lists which notice links which file in `index.json`
(the contract is in docs/specs/2026-10-14-sz-replacement-timetables.md). This module only reads those
files: the web workers never touch a PDF.

A file holds tables of columns, one per bus ("318/2": train 318's second bus), each with its calls in
travel order, footnote numbers that say on which days it runs, and the problems the reader found. A
file the reader is sure of is "ok"; an "unsure" one has columns with problems, which are not used;
a "failed" one is not used at all. Which buses this gives on a service day is closures.py's business.

Reading is cheap but not free, and the server's disk can be slow to stat (a 9p mount locally): the
files are read again at most once a minute (RELOAD), only when index.json changed, and only by a
background thread (`load`, see warm.py); requests use what was read last (`current`).
"""
import json
import logging
import os
import re
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from django.conf import settings

from .mapping import fold

logger = logging.getLogger(__name__)

RELOAD = 60  # s between looks at index.json
_lock = threading.Lock()
_state: dict = {'checked': None, 'stamp': None, 'tables': None, 'files': {}}


class Timetables:
    """The files of one index.json: `file(notice)` is the timetable a notice links, or None."""

    def __init__(self, notices: dict[str, str], files: dict[str, dict], updated: Optional[str] = None):
        self.notices, self.files, self.updated = notices, files, updated

    def file(self, notice: Optional[str]) -> Optional[dict]:
        return self.files.get(self.notices.get(notice or '', ''))


def directory() -> Optional[Path]:
    path = getattr(settings, 'PRESTOP_SZ_TIMETABLES_DIR', '') or ''
    return Path(path) if path else None


def reset():
    """Forget what was read (tests)."""
    with _lock:
        _state.update(checked=None, stamp=None, tables=None, files={})


def current() -> Optional[Timetables]:
    """The timetables read last; never touches the disk."""
    return _state['tables']


def load(now: Optional[float] = None) -> Optional[Timetables]:
    """The timetables, read again when index.json changed, looking at most once a minute. None when the
    directory or its index is missing (then everything behaves as without timetables)."""
    now = time.monotonic() if now is None else now
    with _lock:
        if _state['checked'] is not None and now - _state['checked'] < RELOAD:
            return _state['tables']
        _state['checked'] = now
        where = directory()
        try:
            info = os.stat(where / 'index.json') if where else None
        except OSError:
            info = None
        stamp = (info.st_mtime_ns, info.st_size) if info else None
        if stamp == _state['stamp']:
            return _state['tables']
        _state['stamp'] = stamp
        _state['tables'] = _read(where) if stamp else None
        return _state['tables']


def _read(where: Path) -> Optional[Timetables]:
    try:
        index = json.loads((where / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        logger.warning('SŽ timetables: index.json unreadable: %r', e)
        return None
    notices = {str(k): str(v) for k, v in (index.get('notices') or {}).items() if v}
    old, files = _state['files'], {}
    for sha in set(notices.values()):
        if sha in old:  # a file is named by its PDF's checksum: one already read has not changed
            files[sha] = old[sha]
            continue
        try:
            data = json.loads((where / f'{sha}.json').read_text(encoding='utf-8'))
            if not isinstance(data.get('tables'), list):
                raise ValueError('no tables')
        except (OSError, ValueError, AttributeError) as e:
            logger.warning('SŽ timetables: %s.json left out: %r', sha, e)
            continue
        files[sha] = data
    _state['files'] = files
    return Timetables({n: s for n, s in notices.items() if s in files}, files, index.get('updated'))


# ---------------------------------------------------------------- days

def _easter(year: int) -> date:
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


# Slovenia's work-free public holidays ("prazniki", dela prosti dnevi): fixed days, plus Easter Monday
# (Easter and Whit Sunday fall on a Sunday anyway).
FIXED_HOLIDAYS = {(1, 1), (1, 2), (2, 8), (4, 27), (5, 1), (5, 2), (6, 25), (8, 15), (10, 31), (11, 1), (12, 25), (12, 26)}


def holiday(day: date) -> bool:
    easter = _easter(day.year)
    return (day.month, day.day) in FIXED_HOLIDAYS or day in (easter, easter + timedelta(days=1), easter + timedelta(days=49))


def _weekend(day: date) -> bool:
    return day.weekday() >= 5 or holiday(day)


# What a footnote's rule allows ("2 - Ne vozi ob sobotah, nedeljah in praznikih" is "workdays").
RULES = {
    'workdays': lambda day, note: not _weekend(day),
    'weekends_holidays': lambda day, note: _weekend(day),
    'not_saturday': lambda day, note: day.weekday() != 5,
    # "98 - dne 19.10. se nadomestni prevoz NE opravlja; VOZI VLAK!": that day the train runs instead.
    'train_runs_on': lambda day, note: day.isoformat() not in (note.get('dates') or []),
}
WORKDAYS_ONLY = re.compile(r'^\*\s*vozi le ob delovnikih')  # the legend of a starred extra bus ("BUS*")


def valid_on(data: dict, day: date) -> bool:
    valid = data.get('valid') or {}
    if valid.get('dates'):
        return day.isoformat() in valid['dates']
    start, end = valid.get('from'), valid.get('to')
    return bool(start and end) and start <= day.isoformat() <= end


def _star_means_workdays(data: dict) -> bool:
    return any(WORKDAYS_ONLY.match(fold(n).strip()) for n in data.get('notes') or [])


def unusable(data: dict, col: dict) -> Optional[str]:
    """Why a column cannot be used (problems the reader found, a footnote it could not read), or None."""
    if data.get('status') not in ('ok', 'unsure'):
        return f'timetable {data.get("status")}'
    if col.get('problems'):
        return '; '.join(map(str, col['problems']))
    if len(col.get('calls') or []) < 2:
        return 'fewer than two calls'
    for key in col.get('footnotes') or []:
        note = (data.get('footnotes') or {}).get(str(key))
        if not note:
            return f'footnote {key} undefined'
        if note.get('rule') not in RULES:
            return f'footnote {key} not understood ({note.get("rule")!r}: {note.get("text")!r})'
    if col.get('mark') and not (col['mark'] == '*' and _star_means_workdays(data)):
        return f'mark {col["mark"]!r} not understood'
    return None


def runs_on(data: dict, col: dict, day: date) -> bool:
    """Whether the column's bus runs on service day `day`: in the validity, on every footnote's days."""
    if not valid_on(data, day):
        return False
    notes = data.get('footnotes') or {}
    for key in col.get('footnotes') or []:
        note = notes.get(str(key)) or {}
        allows = RULES.get(note.get('rule'))
        if not allows or not allows(day, note):
            return False
    if col.get('mark') == '*' and _weekend(day):
        return False
    return True


def numbers(col: dict) -> list[str]:
    """The train numbers a column can stand for, most likely first: the printed number, and where SŽ printed
    the bus's own five-digit number (Ljubljana - Logatec: "26729") the train numbers it is made from (2672)."""
    from .replacement import train_numbers
    printed = re.sub(r'\D', '', str(col.get('train') or ''))
    if not printed:
        return []
    return [printed] + (train_numbers(printed) if len(printed) >= 5 else [])

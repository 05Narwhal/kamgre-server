"""The planned train set of each train from our reader's timetable-finder searches (`<PRESTOP_SZSITE_DIR>/train_sets.json`,
read from the file, not over HTTP), as trainClass records (`zamudil.train_class`: SŽ names its sets the way zamudil.si does).

`classes(day)` is empty unless PRESTOP_SZSITE_CLASSES is on and the reader's list is of `day`. zamudil.classes lays it
over zamudil.si's list: SŽ's set wins, zamudil's record of the same series is kept (it has the features), and trains
the reader's searches do not reach (branch lines) keep zamudil's class.
"""
import os
import time
from datetime import date
from typing import Optional

from django.conf import settings

SOURCE_NAME = 'potniski.sz.si'
LOOK_EVERY = 60  # s between looks at the file
_memo: dict = {'looked': float('-inf'), 'stamp': None, 'day': None, 'value': {}}


def _path() -> Optional[str]:
    directory = getattr(settings, 'PRESTOP_SZSITE_DIR', '')
    if not getattr(settings, 'PRESTOP_SZSITE_CLASSES', False) or not directory:
        return None
    return os.path.join(directory, 'train_sets.json')


def classes(day: date, now: Optional[float] = None) -> dict[str, dict]:
    """Train number (text, no leading zeros) → trainClass, for `day`; empty without the reader's list of that date."""
    path = _path()
    if path is None:
        return {}
    now = time.monotonic() if now is None else now
    if now - _memo['looked'] >= LOOK_EVERY:
        _memo['looked'] = now
        try:
            info = os.stat(path)
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            stamp = None
        if stamp != _memo['stamp']:
            from .. import zamudil
            from .store import Store
            saved = Store(os.path.dirname(path)).load('train_sets') if stamp else None
            data = (saved or {}).get('data') or {}
            made = {}
            for number, found in (data.get('trains') or {}).items():
                if str(number).isdigit() and isinstance(found, dict) and found.get('set'):
                    made[str(int(number))] = {**zamudil.train_class({'name': found['set']}), 'source': SOURCE_NAME}
            _memo.update(stamp=stamp, day=data.get('date'), value=made)
    return _memo['value'] if _memo['day'] == day.isoformat() else {}

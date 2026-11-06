"""The last good copy of each job's data, on disk, and what /status says about each job.

`<dir>/<job>.json` holds {'at', 'count', 'data'}; `<dir>/status.json` holds {job: {'at', 'ok', 'error', 'count'}}.
A fetch that parsed but looks wrong never replaces a good copy: an empty list, or one under half the size of a
list that had 10 or more items, is refused and reported as `layout` (the site changed, or answered with a stub).
Only the live trains may be empty, and only at night: 04:30 to 00:30 local is service time.
"""
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .client import atomic_write

logger = logging.getLogger(__name__)
LOCAL = ZoneInfo('Europe/Ljubljana')
BIG = 10              # items a last good list needs for the collapse test to apply
SERVICE = (4 * 60 + 30, 30)  # minutes of the day: service starts 04:30 and ends 00:30
NIGHT_EMPTY = ('active_trains',)  # jobs whose list may be empty outside service hours


def in_service(now: Optional[float] = None) -> bool:
    """Whether trains are running: 04:30 to 00:30 local."""
    t = datetime.fromtimestamp(time.time() if now is None else now, LOCAL)
    minute = t.hour * 60 + t.minute
    return minute >= SERVICE[0] or minute < SERVICE[1]


class Store:
    def __init__(self, state_dir: str):
        self.dir = Path(state_dir)
        self._lock = threading.Lock()

    def _path(self, job: str) -> Path:
        return self.dir / f'{job}.json'

    def load(self, job: str) -> Optional[dict]:
        """{'at', 'count', 'data'} of the last good copy, or None."""
        try:
            saved = json.loads(self._path(job).read_text(encoding='utf-8'))
            return saved if isinstance(saved, dict) and 'data' in saved else None
        except (OSError, ValueError):
            return None

    def jobs(self, prefix: str) -> list[str]:
        """The stored jobs whose name starts with `prefix`."""
        try:
            return sorted(p.stem for p in self.dir.glob(f'{prefix}*.json'))
        except OSError:
            return []

    def keep(self, job: str, data: Any, count: Optional[int] = None, now: Optional[float] = None) -> tuple[bool, Optional[str]]:
        """Store `data` (`count`: its number of items, default len(data)) unless it collapsed against the last good copy.
        Returns (kept, error): (False, 'layout') for a refusal, which is also written to the job's status."""
        now = time.time() if now is None else now
        count = len(data) if count is None else count
        last = self.load(job)
        before = int(last.get('count') or 0) if last else 0
        collapsed = before >= BIG and (count == 0 or count * 2 < before)
        if collapsed and job in NIGHT_EMPTY and not in_service(now):
            collapsed = False  # the last trains are in, the list thins out and empties at night
        if collapsed:
            logger.warning('SŽ site %s: %d items where there were %d, keeping the last copy', job, count, before)
            self.status(job, False, 'layout', before, now)
            return False, 'layout'
        with self._lock:
            atomic_write(self._path(job), json.dumps({'at': now, 'count': count, 'data': data}, ensure_ascii=False))
        self.status(job, True, None, count, now)
        return True, None

    def fail(self, job: str, kind: str, now: Optional[float] = None) -> None:
        """Note a failed fetch of `job`; its last good copy stays."""
        last = self.load(job)
        self.status(job, False, kind, int(last.get('count') or 0) if last else 0, now)

    def status(self, job: Optional[str] = None, ok: bool = True, error: Optional[str] = None, count: int = 0,
               now: Optional[float] = None) -> dict:
        """Record one job's state (when `job` is given) and return every job's: {job: {'at', 'ok', 'error', 'count'}}."""
        with self._lock:
            path = self.dir / 'status.json'
            try:
                every = json.loads(path.read_text(encoding='utf-8'))
                every = every if isinstance(every, dict) else {}
            except (OSError, ValueError):
                every = {}
            if job:
                every[job] = {'at': time.time() if now is None else now, 'ok': ok, 'error': error, 'count': count}
                atomic_write(path, json.dumps(every, ensure_ascii=False))
            return every

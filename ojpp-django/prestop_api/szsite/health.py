"""/health entries for our SŽ website reader (`sz:site-*`), from its own /status on 127.0.0.1 (serve.py).

Only when PRESTOP_SZSITE_STATUS_URL is set (the server sets it with PRESTOP_SZSITE=on): with the reader off nothing is
listed. A reader that does not answer makes every entry unavailable; a job past twice its interval is stale. Outside
service hours (00:30-04:30) the live list is read every NIGHT_LIVE_EVERY s, so it is stale only past twice that.
Train sets (`sz:site-classes`) are read once a service day from 01:00: stale 28 h after the last good list (a missed night
shows by the next morning).
"""
import json
import time
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from django.conf import settings

from .jobs import LIVE_EVERY, NIGHT_LIVE_EVERY, STATUS_EVERY

# id, name, capabilities, the reader's job names (first one present counts), its interval in s
ENTRIES = (
    ('sz:site-notices', "SŽ notices list (our reader of SŽ's website)", ['alerts'], ('notices',), STATUS_EVERY),
    ('sz:site-works', "Works on railway lines (our reader of SŽ's website)", ['alerts'], ('works',), STATUS_EVERY),
    ('sz:site-classes', "Train sets per train (our reader of SŽ's website)", ['vehicles'], ('train_sets',), 14 * 3600),
    ('sz:site-live', "SŽ live trains and delays (our reader of SŽ's website)", ['vehicles'], ('active_trains',), LIVE_EVERY),
)
CACHE = 15  # s: server:top asks /health every few seconds
_last: dict = {'at': 0.0, 'value': None}


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat().replace('+00:00', 'Z')


def _fetch(url: str) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=1) as r:  # loopback only
            data = json.loads(r.read())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def entries(status: Optional[dict], now: float) -> list[dict]:
    """The /health entries for one /status answer ({'now', 'inService', 'jobs': {job: {'at', 'ok', 'error', 'count'}}}),
    None when the reader did not answer."""
    jobs = (status or {}).get('jobs') or {}
    in_service = bool((status or {}).get('inService', True))
    out = []
    for id_, name, capabilities, names, every in ENTRIES:
        job = next((jobs[n] for n in names if isinstance(jobs.get(n), dict)), None)
        at = float(job.get('at') or 0) if job else 0
        if id_ == 'sz:site-live' and not in_service:
            every = NIGHT_LIVE_EVERY
        if not job or not at:
            state = 'unavailable'
        elif not job.get('ok'):
            state = 'stale'
        else:
            state = 'live' if now - at <= 2 * every + 120 else 'stale'
        stamp = _iso(at) if at else None
        out.append({'id': id_, 'name': name, 'status': state, 'updatedAt': stamp, 'capabilities': capabilities, 'since': stamp})
    return out


def health(now: Optional[float] = None, fetch: Callable[[str], Optional[dict]] = _fetch) -> list[dict]:
    url = getattr(settings, 'PRESTOP_SZSITE_STATUS_URL', '')
    if not url:
        return []
    now = time.time() if now is None else now
    if _last['value'] is None or now - _last['at'] > CACHE:
        _last.update(at=now, value=entries(fetch(url), now))
    return _last['value']

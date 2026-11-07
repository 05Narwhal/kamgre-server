"""The reader's answers to the API, over HTTP on 127.0.0.1 only (the API's workers read them like derp-si's scraper).

- `/active_trains`: the last good list of SŽ's running trains, as SŽ gives it (`sz.parse_trains` reads it). 503 once it
  is older than FRESH s (at night NIGHT_LIVE_EVERY more), so `upstream.Mirrors` goes on to the next URL (derp-si) instead of showing stale positions.
- `/train_data?date=YYYY-MM-DD`: {"trains": [{train_id, ijpp_id, platform}]} for `tracks.py`; 503 when no board of
  that date has been read.
- `/works`: {"at", "works": [...]}, the works on the lines. `/status`: every job's state.
"""
import json
import logging
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from . import jobs
from .store import Store, in_service

logger = logging.getLogger(__name__)
FRESH = 120  # s a live list is served


class Handler(BaseHTTPRequestHandler):
    server_version = 'kamgre-szsite'

    def log_message(self, *args):  # quiet: the API polls every 20 s
        pass

    def _send(self, status: int, body) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 - http.server's name
        url = urlsplit(self.path)
        store: Store = self.server.store
        now = self.server.clock()
        if url.path == '/active_trains':
            saved = store.load('active_trains')
            fresh = FRESH if in_service(now) else jobs.NIGHT_LIVE_EVERY + FRESH  # polled every 2 min at night
            if not saved or now - float(saved.get('at') or 0) > fresh:
                return self._send(503, {'error': 'stale', 'age': None if not saved else round(now - float(saved.get('at') or 0))})
            return self._send(200, saved['data'])
        if url.path == '/train_data':
            day = (parse_qs(url.query).get('date') or [''])[0]
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
                return self._send(400, {'error': 'date=YYYY-MM-DD'})
            rows = jobs.train_data(store, day)
            return self._send(200, {'trains': rows}) if rows else self._send(503, {'error': 'no boards for that date'})
        if url.path == '/works':
            saved = store.load('works')
            return self._send(200, {'at': saved['at'], 'works': saved['data']}) if saved else self._send(503, {'error': 'no works yet'})
        if url.path == '/status':
            return self._send(200, {'now': now, 'inService': in_service(now), 'jobs': store.status()})
        return self._send(404, {'error': 'not found'})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, store: Store, port: int, clock: Callable[[], float] = time.time):
        super().__init__(('127.0.0.1', port), Handler)
        self.store, self.clock = store, clock

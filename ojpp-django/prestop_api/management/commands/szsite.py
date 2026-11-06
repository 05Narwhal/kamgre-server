"""Our own reader of SŽ's passenger site, as a service or one fetch at a time (prestop_api/szsite).

    manage.py szsite                          # the loop plus the 127.0.0.1 server the API reads (one process, SIGTERM stops it)
    manage.py szsite --once live              # one fetch of live, status or boards, and a one-line summary
    manage.py szsite --clearance edge.json    # use a browser's cookies and user agent (local testing; no solver needed)

Settings / environment: PRESTOP_SZSITE_SOLVER (FlareSolverr's URL), PRESTOP_SZSITE_DIR (state folder),
PRESTOP_SZSITE_PORT (default 8095). The server sets PRESTOP_SZ_LIVE_URL=http://127.0.0.1:8095/active_trains,<derp-si>.
"""
import logging
import os
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prestop_api.szsite import jobs
from prestop_api.szsite.client import Client, SiteError
from prestop_api.szsite.serve import Server
from prestop_api.szsite.store import Store

PORT = 8095


class Command(BaseCommand):
    help = "Read SŽ's site (live trains, notices, works, station boards) and serve it to the API on 127.0.0.1."

    def add_arguments(self, parser):
        parser.add_argument('--once', choices=['live', 'status', 'boards'], help='fetch one job once and print a summary')
        parser.add_argument('--station', help="with --once boards: the station's SŽ code (default: Ljubljana, 42300)")
        parser.add_argument('--clearance', help="JSON file with a browser's {cookies, userAgent}")
        parser.add_argument('--port', type=int, default=int(os.environ.get('PRESTOP_SZSITE_PORT') or PORT))

    def handle(self, *args, once=None, station=None, clearance=None, port=PORT, **options):
        directory = getattr(settings, 'PRESTOP_SZSITE_DIR', '')
        if not directory:
            raise CommandError('PRESTOP_SZSITE_DIR is not set')
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
        client = Client(getattr(settings, 'PRESTOP_SZSITE_SOLVER', ''), directory, proxy=getattr(settings, 'PRESTOP_SZSITE_PROXY', ''))
        if clearance:
            try:
                with open(clearance, encoding='utf-8') as f:
                    client.seed(f.read())
            except (OSError, ValueError) as e:
                raise CommandError(f'{clearance}: {e}')
        store = Store(directory)
        if once:
            try:
                summary = jobs.run_once(once, client, store, code=station)
            except SiteError as e:
                store.fail(once if once != 'boards' else f'board-{station or "42300"}', e.kind)
                raise CommandError(str(e))
            self.stdout.write(f'{once}: ' + ' '.join(f'{k}={v}' for k, v in summary.items()))
            return
        if not client.solver_url and not client.cleared:
            self.stdout.write('szsite: no PRESTOP_SZSITE_SOLVER and no clearance file (--clearance, or clearance.json in '
                              f'{directory}): nothing can pass Cloudflare, not starting.')
            return
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        server = Server(store, port)
        threading.Thread(target=server.serve_forever, daemon=True, name='szsite-serve').start()
        self.stdout.write(f'szsite: serving http://127.0.0.1:{port}/active_trains, state in {directory}')
        try:
            jobs.Loop(client, store).run(stop)
        finally:
            server.shutdown()
            server.server_close()

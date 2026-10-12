import logging
import time

from django.conf import settings
from django.core.management import BaseCommand, CommandError

from prestop_push.watcher import tick

logger = logging.getLogger('prestop push')


class Command(BaseCommand):
    help = "Send due reminders and live trip changes as Web Push notifications (runs continuously)."

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run one pass and exit')
        parser.add_argument('--interval', type=int, default=20, help='Seconds between passes (default 20)')

    def handle(self, once, interval, **options):
        if not (settings.PRESTOP_VAPID_PRIVATE_KEY and settings.PRESTOP_VAPID_PUBLIC_KEY):
            raise CommandError('PRESTOP_VAPID_PUBLIC_KEY and PRESTOP_VAPID_PRIVATE_KEY are not set (see backend/deploy/oracle/README.md, "Push notifications")')
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
        while True:
            started = time.monotonic()
            try:
                logger.info('tick: sent %s', tick())
            except Exception:  # keep the service alive through database or upstream hiccups
                logger.exception('push tick failed')
            if once:
                return
            time.sleep(max(1.0, interval - (time.monotonic() - started)))

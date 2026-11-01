"""Arriva's notices read somewhere else, for a server its site blocks: `yarn server:update` reads the posts on the
deployer's PC and sends them here (backend/deploy/oracle/notices-remote.sh).

    manage.py arriva_notices --import < posts.json   # checks them and hands them to the API, whose workers notice the file
    manage.py arriva_notices                         # what the server has now
"""
import json
import sys
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from prestop_api import operator_notices as notices


class Command(BaseCommand):
    help = "Show Arriva's uploaded notices, or replace them with --import (the site's JSON list of posts on stdin)."

    def add_arguments(self, parser):
        parser.add_argument('--import', dest='import_posts', action='store_true', help="read the site's posts from stdin")

    def handle(self, *args, import_posts=False, **options):
        if import_posts:
            self.save(sys.stdin.buffer.read(notices.ARRIVA_LIMIT + 1))
        upload = notices.arriva_upload()
        if not upload:
            self.stdout.write("No upload of Arriva's notices yet: run `yarn server:update` on your PC.")
            return
        at = datetime.fromtimestamp(upload['at'], notices.LOCAL)
        current = notices.arriva_alerts(upload['posts'], '', {})
        self.stdout.write(f'Arriva: {len(upload["posts"])} posts from {at:%d. %m. %Y %H:%M}, {len(current)} notices in effect:')
        for alert in sorted(current, key=lambda a: a['_from']):
            start, end = (datetime.fromtimestamp(alert[k], notices.LOCAL) for k in ('_from', '_to'))
            self.stdout.write(f'  {start:%d. %m.} - {end:%d. %m.}  {alert["title"][:90]}')

    def save(self, body: bytes) -> None:
        if len(body) > notices.ARRIVA_LIMIT:
            raise CommandError(f'More than {notices.ARRIVA_LIMIT} bytes: this is not the list of posts. The notices stay as they were.')
        try:
            notices.save_arriva_upload(json.loads(body), time.time())
        except (ValueError, TypeError) as e:
            raise CommandError(f'Not saved, the notices stay as they were: {e}') from e
        except OSError as e:
            raise CommandError(f'Not saved: {e}') from e

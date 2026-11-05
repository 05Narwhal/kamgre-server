"""SŽ's list of disruptions, saved from a browser: `yarn server:update --sz <file>` sends the page here
(backend/deploy/oracle/notices-remote.sh).

    manage.py sz_notices --import < page.html   # checks it and hands it to the API, whose workers notice the file
    manage.py sz_notices                        # what the server has now
"""
import sys
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from prestop_api import sz_list


class Command(BaseCommand):
    help = "Show the uploaded SŽ list of disruptions, or replace it with --import (the saved page on stdin)."

    def add_arguments(self, parser):
        parser.add_argument('--import', dest='import_page', action='store_true', help='read the saved page from stdin')

    def handle(self, *args, import_page=False, **options):
        if import_page:
            self.save(sys.stdin.buffer.read(sz_list.LIMIT + 1))
        upload = sz_list.loaded()
        if not upload:
            self.stdout.write("No list uploaded yet: save SŽ's page in your browser, then run `yarn server:update --sz <file>`.")
            return
        now = time.time()
        running = [n for n in upload['notices'] if sz_list.spans(n)[-1][1].isoformat() >= datetime.fromtimestamp(now, sz_list.LOCAL).date().isoformat()]
        timetables = [n for n in running if sz_list._is_timetable(n)]
        at = datetime.fromtimestamp(upload['at'], sz_list.LOCAL)
        self.stdout.write(f'SŽ: {len(upload["notices"])} notices from {at:%d. %m. %Y %H:%M}, {len(running)} in effect or to come, {len(timetables)} with a replacement timetable.')
        for notice in sorted(running, key=lambda n: n['from']):
            self.stdout.write(f'  {notice["from"]} - {notice["to"]}  {notice["title"][:90]}')

    def save(self, body: bytes) -> None:
        if len(body) > sz_list.LIMIT:
            raise CommandError(f'More than {sz_list.LIMIT} bytes: this is not the page. The notices stay as they were.')
        page = body.decode('utf-8', 'replace')
        notices = sz_list.parse(page)
        try:
            sz_list.save(notices, time.time())
        except ValueError as e:
            raise CommandError(f'Not saved, the notices stay as they were: {e}') from e
        except OSError as e:
            raise CommandError(f'Not saved: {e}') from e
        missed = sz_list.left_out(page, notices)
        if missed:
            self.stdout.write(f'Not read (no dates or no heading): {"; ".join(missed)}')

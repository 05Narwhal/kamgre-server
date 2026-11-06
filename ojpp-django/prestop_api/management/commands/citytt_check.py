"""The cheap look at the hand-kept city timetables (prestop_api/citytt/watch.py): which expires soon, which one's source changed.

    manage.py citytt_check            # every feed; updates the state file /health `cityTimetables` serves (nightly, 02:15)
    manage.py citytt_check --no-save  # look and print only (yarn live on the PC)
    manage.py citytt_check --json

Reads the operators' list pages and the headers of the files the folders were built from; downloads no PDF. Exit 0
whatever it finds: the alarm is the answer, not the exit code.
"""
import json
from datetime import datetime

from django.core.management.base import BaseCommand

from prestop_api import supplement
from prestop_api.citytt import watch


class Command(BaseCommand):
    help = 'Look at the hand-kept city timetables: expiry and changed sources.'

    def add_arguments(self, parser):
        parser.add_argument('--no-save', action='store_true', help='do not write the state file')
        parser.add_argument('--json', dest='as_json', action='store_true', help='print the answer as JSON')

    def handle(self, *args, no_save=False, as_json=False, **options):
        result = watch.run(datetime.now(supplement.LOCAL).date(), path='' if no_save else None)
        if as_json:
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return
        for f in result['feeds']:
            self.stdout.write(f'{f["feed"]:9} {f["state"]:11} {f["text"]}' + (f'  [{"; ".join(f["detail"][:3])}]' if f['detail'] else ''))
        urgent = watch.lines(result)
        self.stdout.write('City timetables: ' + (' · '.join(urgent) if urgent else 'all fine'))

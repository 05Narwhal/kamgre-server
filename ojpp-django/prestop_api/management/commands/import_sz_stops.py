"""Import SŽ's list of replacement-bus stops from a hand scrape (see szstops.py).

    manage.py import_sz_stops path/to/sz-bus-stops-candidates.json

Writes `prestop_api/data/sz_replacement_stops.csv`, one row per line and station. The running
server re-reads the file when it changes.
"""
import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from prestop_api import szstops

HEADER = ("# SŽ replacement-bus stops per line (potniski.sz.si 'Lokacije postankov nadomestnih prevozov'),\n"
          "# imported by manage.py import_sz_stops. source: how the position was read from SŽ's map link;\n"
          "# map_camera_only is only where the map was looking (treated as unverified). Fix a stop in\n"
          "# stop_overrides.csv (type replacement), which wins over this list.\n")


class Command(BaseCommand):
    help = "Import SŽ's replacement-bus stop list (JSON from the hand scrape) into data/sz_replacement_stops.csv."

    def add_arguments(self, parser):
        parser.add_argument('path', help='sz-bus-stops-candidates.json from the scrape')

    def handle(self, *args, path, **options):
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            raise CommandError(f'Cannot read {path}: {e}')
        rows = szstops.from_scrape(data)
        if not rows:
            raise CommandError('No stops with positions in that file.')
        with open(szstops.FILE, 'w', encoding='utf-8', newline='') as f:
            f.write(HEADER)
            writer = csv.DictWriter(f, fieldnames=szstops.FIELDS, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        lines = len({r['route'] for r in rows})
        rough = sum(1 for r in rows if r['source'] in szstops.APPROXIMATE)
        self.stdout.write(f'{len(rows)} stops on {lines} lines written to {szstops.FILE} ({rough} only approximate).')

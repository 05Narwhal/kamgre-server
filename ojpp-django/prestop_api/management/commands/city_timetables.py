"""City bus timetables from the operators' own pages into data/gtfs/<feed>/ (prestop_api/citytt).

    manage.py city_timetables                    # every city: fetch, read, place, route, check, write when changed
    manage.py city_timetables --city Jesenice
    manage.py city_timetables --check            # build and compare with the folder, write nothing (exit 1: differs)
    manage.py city_timetables --fixtures prestop_api/tests/fixtures/citytt --write-goldens
        # rewrite <file>.expected.json for every fixture PDF: check each changed run against the PDF first

arriva.si answers only from Slovenia: run it on a PC there (`yarn city-timetables`) and commit the folder. Needs
OTP, Overpass and Valhalla (ojpp.sh uses the local one on :8002 when it runs). Marprom needs none of them, only
marprom.si, the published GTFS and vozniredi.marprom.si (about 60 requests for the PDFs and 1,800 for the site's
stop pages, one a second: some 35 minutes, `--city MARPROM` alone).
"""
import importlib
import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from prestop_api.citytt import CITIES, build


class Command(BaseCommand):
    help = "Build the hand-kept city bus feeds from the operators' timetables."

    def add_arguments(self, parser):
        parser.add_argument('--city', default='', help=f'one of {", ".join(CITIES)}')
        parser.add_argument('--check', action='store_true', help='compare with the folder, write nothing')
        parser.add_argument('--fixtures', default='', help='with --write-goldens: the fixture PDFs')
        parser.add_argument('--write-goldens', action='store_true', help='rewrite <file>.expected.json for each fixture PDF')

    def handle(self, *args, city='', check=False, fixtures='', write_goldens=False, **options):
        if write_goldens:
            return self.goldens(fixtures)
        if city and city not in CITIES:
            raise CommandError(f'Unknown city {city!r}: {", ".join(CITIES)}')
        today = date.today()
        failed = differs = False
        for c in [CITIES[city]] if city else CITIES.values():
            try:
                reader = importlib.import_module(f'prestop_api.citytt.{c.reader}')
                if hasattr(reader, 'run'):  # a reader that fetches and builds on its own (Marprom: no poles, no routing)
                    out, status = reader.run(c, today)
                else:
                    page, files = build.fetch(c)
                    stops, runs = build.feed_poles(c)
                    osm_stops, osm_runs = build.osm_poles(c)
                    legs = build.feed_legs(c) if c.replaces else {}  # a correction: OTP's drawing where no road route is plausible
                    out, status = build.build(c, build.Sources(page, files, stops, runs, osm_stops, osm_runs, legs), today)
            except build.BuildError as e:
                failed = True
                self.stderr.write(f'{c.name}: build failed, the folder stays as it was:\n  ' + str(e).replace('\n', '\n  '))
                if not check:
                    build.fail(c, str(e), today)
                continue
            lines = ', '.join(f'{k} {n} runs' for k, n in status['lines'].items())
            if check:
                changed = build.changes(c, out)
                differs |= bool(changed)
                self.stdout.write(f'{c.name}: {lines}; ' + (f'differs from the folder: {", ".join(changed)}' if changed else 'same as the folder'))
            else:
                changed = build.write(c, out, status, today)
                self.stdout.write(f'{c.name}: {lines}; ' + (f'wrote {", ".join(changed)}' if changed else 'unchanged') + f' ({build.folder(c)})')
        if failed or differs:
            raise SystemExit(1)

    def goldens(self, fixtures: str):
        from prestop_api.citytt import arriva
        if not fixtures:
            raise CommandError('--write-goldens needs --fixtures <dir>.')
        for pdf in sorted(Path(fixtures).glob('*.pdf')):
            doc = arriva.parse(pdf)
            pdf.with_name(f'{pdf.stem}.expected.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
            self.stdout.write(f'{pdf.stem}: line {doc["line"]}, {len(doc["stops"])} stops, {len(doc["runs"])} runs')

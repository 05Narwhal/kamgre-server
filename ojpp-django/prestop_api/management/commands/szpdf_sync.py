"""Read SŽ's replacement-bus timetables from the PDFs its disruption notices link (prestop_api/szpdf) into
PRESTOP_SZ_TIMETABLES_DIR: one <sha256>.json per PDF and index.json, which the API reads.

    manage.py szpdf_sync                       # the live notices (PRESTOP_SZ_NOTICES_URL); the prestop-szpdf timer
    manage.py szpdf_sync --report              # … and print one line per notice
    manage.py szpdf_sync --from prestop_api/tests/fixtures/szpdf/notices-2026-10-14.json \\
                         --fixtures prestop_api/tests/fixtures/szpdf --report   # the test snapshot, nothing downloaded
    manage.py szpdf_sync --fixtures prestop_api/tests/fixtures/szpdf --write-goldens
        # rewrite <id>.expected.json for every fixture: check each changed column against the rendered page first
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prestop_api.szpdf import sync
from prestop_api.upstream import Mirrors, UpstreamError


class Command(BaseCommand):
    help = "Read the SŽ notices' replacement-timetable PDFs into PRESTOP_SZ_TIMETABLES_DIR."

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='source', default='', help='a saved notices JSON instead of PRESTOP_SZ_NOTICES_URL')
        parser.add_argument('--fixtures', default='', help='read <ID_ovire>.pdf from this directory instead of downloading')
        parser.add_argument('--report', action='store_true', help='print one line per notice')
        parser.add_argument('--write-goldens', action='store_true', help='with --fixtures: rewrite <id>.expected.json')

    def handle(self, *args, source='', fixtures='', report=False, write_goldens=False, **options):
        if write_goldens:
            return self.goldens(fixtures)
        if not settings.PRESTOP_SZ_TIMETABLES_DIR:
            raise CommandError('PRESTOP_SZ_TIMETABLES_DIR is empty.')
        notices = self.notices(source)
        fetch = sync.fixture_fetcher(notices, Path(fixtures)) if fixtures else sync.download
        rows = sync.run(Path(settings.PRESTOP_SZ_TIMETABLES_DIR), notices, fetch)
        counts = {}
        for r in rows:
            counts[r['status']] = counts.get(r['status'], 0) + 1
        if report:
            for r in rows:
                why = sorted({e.rsplit(': ', 1)[-1] for e in r['errors']})
                extra = f'  ({r["missing"]} PDF not fetched: {", ".join(why) or "?"})' if r['missing'] else ''
                self.stdout.write(f'{r["id"]:>6}  {r["status"]:<7} {r["columns"]:>4} columns {r["problems"]:>4} problems  '
                                  f'{r["title"][:60]}{extra}')
        self.stdout.write(f'{len(rows)} notices with a timetable PDF: '
                          + ', '.join(f'{n} {s}' for s, n in sorted(counts.items())) + f' → {settings.PRESTOP_SZ_TIMETABLES_DIR}')

    def notices(self, source: str) -> list:
        if source:
            return json.loads(Path(source).read_text(encoding='utf-8'))
        mirrors = Mirrors('PRESTOP_SZ_NOTICES_URL')
        if not mirrors.urls:
            raise CommandError('No notices: set PRESTOP_SZ_NOTICES_URL or pass --from.')
        try:
            return mirrors.get_json(limit=8 * 1024 * 1024, timeout=(5, 30))
        except UpstreamError as e:
            raise CommandError(f'Notices unavailable: {e}') from e

    def goldens(self, fixtures: str):
        from prestop_api import szpdf
        if not fixtures:
            raise CommandError('--write-goldens needs --fixtures <dir>.')
        for pdf in sorted(Path(fixtures).glob('*.pdf')):
            doc = szpdf.parse(pdf)
            sync.write_json(pdf.with_name(f'{pdf.stem}.expected.json'), doc)
            self.stdout.write(f'{pdf.stem}: {doc["status"]}')

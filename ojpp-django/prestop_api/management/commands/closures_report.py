"""Where each SŽ closure's replacement buses come from on a service day, and which trains they replace.

    manage.py closures_report 2026-10-14

Per notice in effect that day: the source (the replacement timetable SŽ links, "ok" or "unsure"; guessed
from the notice; or the feed's own buses / none), how many of the feed's buses its timetable runs instead
of, and each bus: the train it replaces, its stretch and times. Reads the live notices and timetable (OTP)
and the files in PRESTOP_SZ_TIMETABLES_DIR (closures.plan, sztimetables.py).
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from prestop_api import closures, mapping, replacement, scheduled, sources, sztimetables
from prestop_api.upstream import UpstreamError


class Command(BaseCommand):
    help = "Report each SŽ closure's replacement buses on a day: timetable, guessed or feed."

    def add_arguments(self, parser):
        parser.add_argument('date', help='service day, YYYY-MM-DD')

    def handle(self, *args, date: str = '', **options):
        try:
            day = date_from(date)
        except ValueError as e:
            raise CommandError(f'not a date: {date!r}') from e
        sztimetables.reset()
        tables = sztimetables.load()
        where = sztimetables.directory()
        if tables:
            files = sorted(tables.files.values(), key=lambda f: ','.join(f.get('notices') or []))
            self.stdout.write(f'Timetables in {where}: {len(files)} files, ' +
                              ', '.join(f'{"/".join(f.get("notices") or [])} {f.get("status")}' for f in files))
        else:
            self.stdout.write(f'No timetables in {where or "(PRESTOP_SZ_TIMETABLES_DIR unset)"}: every closure is guessed as before.')
        trips = scheduled.day_timetable(day).get().value
        try:
            linked = closures.points.get().value
        except UpstreamError:
            linked = {}
        loaded = (sources.alerts_raw.get().value, closures.bus_patterns.get().value, linked, sources.stops.get().value)
        built = closures.build(trips, replacement.sections(trips), loaded, tables)
        rows = closures.report(built, mapping.build_alerts(loaded[0], 'sl'), day.strftime('%Y%m%d'))
        self.stdout.write(closures.format_report(rows) or 'No closure notice in effect that day.')


def date_from(text: str) -> date:
    return date.fromisoformat(text)

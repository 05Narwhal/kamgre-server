"""`manage.py gps_habit --measure [--days N]`: what the "no live data" rule (gps_habit.py, spec 2026-11-25 B1) would
have marked on recorded days, and how many marked trips still came (false marks). `--backtest [--days 14]`: which
listed buses the run-rate rule (part 5) would have hidden on each recorded day, learned only from the days before it,
and how many of them ran anyway (false hides), with the stored SŽ closure days left out of each line's rate. Read-only
(asks OTP for the timetables of steady operators' lines). `--learn` (nightly): adds today's SŽ closures to
PRESTOP_GHOST_FILE. `--seed FILE ...`: the closures in saved notice copies (SŽ's list, zamudil's daily notices), written
to `--out` (default the seed file shipped with the code, gps_habit.SEED_FILE)."""
import json
from datetime import date

from django.core.management.base import BaseCommand

from prestop_api import gps_habit


class Command(BaseCommand):
    help = 'Measure the no-live-data rule on recorded history (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--measure', action='store_true', help='measure on recorded days')
        parser.add_argument('--backtest', action='store_true', help='backtest the rarely-runs rule on recorded days')
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--today', type=date.fromisoformat, default=None, help='measure up to this day (YYYY-MM-DD)')
        parser.add_argument('--no-timetable', action='store_true', help='skip the timetable lookups (no marked counts)')
        parser.add_argument('--learn', action='store_true', help="store today's SŽ closures (nightly)")
        parser.add_argument('--seed', nargs='+', default=None, help='saved notice copies to read closures from')
        parser.add_argument('--out', default=None, help='--seed: the file to add them to (default: the shipped seed)')
        parser.add_argument('--rates', default=str(gps_habit.GHOST_RATE),
                            help='backtest: ghost run-rate thresholds to compare, comma-separated (e.g. 0.1,0.2)')

    def handle(self, *args, **options):
        today = options['today'] or date.today()
        if options['learn'] or options['seed']:
            return self.closures(today, options['seed'], options['out'])
        known = gps_habit.learn_from_db(today)
        self.stdout.write(f"steady operators: {len(known['operators'])}, steady lines: {len(known['steady'])}, "
                          f"partial lines: {len(known['partial'])}, rarely live lines: {len(known['rare'])}")
        if options['backtest']:
            return self.backtest(today, options['days'], known, [float(r) for r in options['rates'].split(',') if r.strip()])
        if not options['measure']:
            return
        from prestop_api.views import scheduled_trip_counts
        result = gps_habit.measure(today, options['days'], None if options['no_timetable'] else scheduled_trip_counts)
        for d in result['days']:
            share = f"{100 * d['late'] / d['live']:.1f} %" if d['live'] else '-'
            self.stdout.write(f"{d['day']}: lines {d['lines']} (steady {d['steady']}, partial {d['partial']}, operators {d['operators']}), marked {d['marked']}, live {d['live']}, came late {d['late']} ({share})")
        self.stdout.write(json.dumps(result['mostMarked']))

    def backtest(self, today, days, known, rates):
        from datetime import timedelta
        from prestop_api.upstream import otp
        past = gps_habit.history(today - timedelta(days=days + gps_habit.LONG), today - timedelta(days=1))
        routes = sorted(r for r, o in past[2].items() if o in known['operators'] and gps_habit.judgeable(r, o, None))
        self.stdout.write(f'asking the timetable of {len(routes)} lines of {len(known["operators"])} steady operators ...')
        listed, failed = [], 0
        for route in routes:
            try:
                listed += gps_habit.listing(otp().query(gps_habit.ROUTE_TRIPS_Q, {'id': route}).get('route') or {})
            except Exception:  # the timetable service did not answer: that line is left out
                failed += 1
        sections = gps_habit.load_closures()
        closed = gps_habit.closed_lines(listed, sections)
        self.stdout.write(f'closure sections stored {len(sections)}, lines with closure days {len(closed)}: '
                          + ', '.join(f'{n} ({len(d)} d)' for (_, n), d in sorted(closed.items(), key=lambda x: x[0][1])))
        for rate in rates:
            result = gps_habit.backtest(today, days, listed, past, rate, closed)
            self.stdout.write(f'--- ghost at run rate <= {rate:.2f} (day share {gps_habit.DAY_SHARE})')
            for d in result['days']:
                self.stdout.write(f"{d['day']}: steady operators {d['operators']}, hidden {d['hidden']}, ran anyway {d['ranAnyway']}, irregular {d['irregular']}")
            self.stdout.write(f"total hidden {result['hidden']}, ran anyway {result['ranAnyway']} ({100 * result['falseShare']:.1f} %), "
                              f"slots hidden on 2+ days they ran {result['hiddenOn2DaysItRan']}, lines left out {failed}")
            for line in result['lines']:
                self.stdout.write(f"  {line['line']}: hidden {line['hidden']} slot-days, ran {line['ran']}, rate {line['rate']:.2f}, "
                                  f"days {' '.join(d[5:] for d in line['days'])}")

    def closures(self, today, seed, out):
        from pathlib import Path
        from django.conf import settings
        from prestop_api import scheduled
        trains = gps_habit.rail_trains(scheduled.day_timetable(today).get().value)
        if seed:
            alerts = gps_habit.notices_from_files(seed)
            path = out or str(Path(gps_habit.__file__).parent / gps_habit.SEED_FILE)
        else:
            from prestop_api import sources
            alerts = sources.alerts('sl')
            path = out or getattr(settings, 'PRESTOP_GHOST_FILE', '')
            if not path:
                self.stdout.write('PRESTOP_GHOST_FILE unset: nothing stored')
                return
        sections = gps_habit.closure_sections(alerts, trains)
        for keys, days in sections:
            self.stdout.write(f"  {len(keys)} stations ({', '.join(sorted(keys)[:4])} ...): {' '.join(sorted(d.isoformat()[5:] for d in days))}")
        stored = gps_habit.save_closures(sections, path, today)
        self.stdout.write(f'{len(alerts)} notices, {len(trains)} trains, {len(sections)} closures; {stored} sections in {path}')

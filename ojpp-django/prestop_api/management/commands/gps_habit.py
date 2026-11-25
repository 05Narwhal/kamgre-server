"""`manage.py gps_habit --measure [--days N]`: what the "no live data" rule (gps_habit.py, spec 2026-11-25 B1) would
have marked on recorded days, and how many marked trips still came (false marks). `--backtest [--days 14]`: which
listed buses the run-rate rule (part 5) would have hidden on each recorded day, learned only from the days before it,
and how many of them ran anyway (false hides). Read-only (asks OTP for the timetables of steady operators' lines)."""
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
        parser.add_argument('--rates', default=str(gps_habit.GHOST_RATE),
                            help='backtest: ghost run-rate thresholds to compare, comma-separated (e.g. 0.1,0.2)')

    def handle(self, *args, **options):
        today = options['today'] or date.today()
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
        for rate in rates:
            result = gps_habit.backtest(today, days, listed, past, rate)
            self.stdout.write(f'--- ghost at run rate <= {rate:.2f} (day share {gps_habit.DAY_SHARE})')
            for d in result['days']:
                self.stdout.write(f"{d['day']}: steady operators {d['operators']}, hidden {d['hidden']}, ran anyway {d['ranAnyway']}, irregular {d['irregular']}")
            self.stdout.write(f"total hidden {result['hidden']}, ran anyway {result['ranAnyway']} ({100 * result['falseShare']:.1f} %), "
                              f"slots hidden on 2+ days they ran {result['hiddenOn2DaysItRan']}, lines left out {failed}")
            for line in result['lines']:
                self.stdout.write(f"  {line['line']}: hidden {line['hidden']} slot-days, ran {line['ran']}, rate {line['rate']:.2f}, "
                                  f"days {' '.join(d[5:] for d in line['days'])}")

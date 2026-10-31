"""manage.py train_stay_backtest: how staying on the train would have been learned on the rolled-up days (spec
2026-10-31 H5), read-only unless --save.

For every day with TrainDay rows (up to --days back): the candidates from that date's timetable (OTP), the evidence
from the rollups, the coverage behind the gate. Then: outcomes, informative days per pair, the levels the nightly job
would learn today (and, while the gate is closed, the levels it would learn if it were open), and the backtest (each
informative day predicted from the days before it; precision = right / predicted). --pairs N lists the N pairs with the
most evidence. --save also stores the days (TrainLinkDay, TrainCoverDay) as the nightly job does.
"""
from collections import Counter
from datetime import timedelta

from django.core.management import BaseCommand

from prestop_api import trips
from prestop_statistics import train_stays as ts


def pct(a: int, b: int) -> str:
    return f'{100 * a / b:5.1f} %' if b else '    -  '


class Command(BaseCommand):
    help = 'Backtest staying on the train on the rolled-up days (read-only unless --save).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=ts.KEEP_DAYS)
        parser.add_argument('--pairs', type=int, default=20)
        parser.add_argument('--save', action='store_true')

    def handle(self, days, pairs, save, **options):
        from prestop_statistics.models import RecorderDay, TrainDay
        today = trips.service_day()
        dates = sorted(set(TrainDay.objects.filter(service_date__gte=today - timedelta(days=days), service_date__lt=today)
                           .values_list('service_date', flat=True)))
        seconds = dict(RecorderDay.objects.filter(feed='*', day__in=dates).values_list('day', 'seconds'))
        links, covers = [], []
        for day in dates:
            runs, rows = ts.timetable(day), ts.rollups(day)
            found, cover = ts.observe(day, runs, rows)
            cover['collector_seconds'] = seconds.get(day, 0)
            links += [{**x, 'level': ''} for x in found]
            covers.append(cover)
            ok = day in ts.complete([cover])
            self.stdout.write(f'{day}  timetable {cover["trains"]:>4}  reported {cover["reported"]:>4} ({pct(cover["reported"], cover["trains"])})'
                              f'  collector {cover["collector_seconds"] / 3600:4.1f} h  {"complete" if ok else "not complete"}  candidates {len(found)}')
            if save:
                ts.record(day, runs, rows)
        turns = ts.station_turns(links)
        outcomes = Counter(ts.outcome(x, turns.get(x['station'], ts.MIN_TURN)) for x in links)
        groups = ts.histories(links, turns)
        informative = Counter(min(sum(1 for _, r in h if r in ts.INFORMATIVE), 6) for h in groups.values())
        self.stdout.write(f'\npairs {len(groups)}, pair-days {len(links)}; outcomes {dict(outcomes)}')
        self.stdout.write(f'informative days per pair (6 = 6+): {dict(sorted(informative.items()))}')
        self.stdout.write(f'least turns learned: {turns or "none yet (MIN_TURN 4 min everywhere)"}')
        rows, summary = ts.learn_rows(links, covers, today)
        self.stdout.write(f'\nlearned today: {summary}')
        open_rows, open_summary = ts.learn_rows(links, [{**c, 'collector_seconds': 86400, 'reported': c['trains']} for c in covers] +
                                                [{'day': today - timedelta(days=k), 'trains': 1, 'reported': 1, 'collector_seconds': 86400}
                                                 for k in range(1, ts.GATE_DAYS + 1)], today)
        self.stdout.write(f'if the gate were open: {open_summary}')
        for name, cell in open_summary.get('backtest', {}).items():
            self.stdout.write(f'  backtest {name:<6} predicted {cell["predicted"]:>4}  right {cell["hits"]:>4}  precision {pct(cell["hits"], cell["predicted"])}')
        for r in open_rows:
            self.stdout.write(f'  {r["level"]:<6} {r["from_number"]:>5} -> {r["to_number"]:<5} at {r["station_name"]} ({r["agree_days"]} agree / {r["informative_days"]} informative)')
        ranked = sorted(groups.items(), key=lambda kv: (-sum(1 for _, r in kv[1] if r == ts.AGREE), -sum(1 for _, r in kv[1] if r in ts.INFORMATIVE)))
        self.stdout.write(f'\npairs with the most evidence:')
        for (a, b), hist in ranked[:pairs]:
            if not any(r in ts.INFORMATIVE for _, r in hist):
                break
            self.stdout.write(f'  {a:>5} -> {b:<5} ' + ' '.join(f'{d.isoformat()[5:]}:{r}' for d, r in hist if r not in (ts.NODATA,)))

"""manage.py train_stays [--date YYYY-MM-DD] [--status]: the learned train stays (TrainStay), the coverage behind the gate,
and with --date that day's outcomes and joined trains (spec 2026-10-31 H6). --status: "why isn't it showing?" in words
(spec 2026-11-01 I14), reached by `yarn server:stays --trains --status`. Read-only."""
import json
from datetime import date

from django.core.management import BaseCommand

from prestop_statistics import train_stays as ts

NEVER_LISTED = 40


def status_lines(s: dict) -> list[str]:
    out = [f'Staying on the train on {s["today"]}. A day counts with the collector at {ts.stays.FULL_DAY / 86400:.0%} or more and '
           f'{ts.COVERED:.0%} or more of its trains reported.', '']
    out.append('day          collector  trains reported        counts')
    for d in s['days']:
        share = f'{d["reported"] / d["trains"]:6.1%}' if d['trains'] else '    - '
        why = ' + '.join(d['misses'])
        out.append(f'{d["day"]}  {d["collector"]:8.1%}  {d["trains"]:6} {d["reported"]:4} {share}  {"yes" if d["counts"] else f"no ({why})"}'
                   f'{"" if d["recorded"] else "  (not recorded yet: a coming night backfills it)"}')
    if not s['days']:
        out.append('(no days rolled up or recorded in the last days)')
    out += ['', f'Streak: {s["streak"]}/{s["needs"]} days in a row.',
            f'Gate: open since {s["opens"]}.' if s['open'] else f'Gate: closed; the earliest it can open is {s["opens"]}.',
            f'Learned: {s["sure"]} sure, {s["likely"]} likely, of {s["pairs"]} candidate pairs recorded.']
    if s['top']:
        out += ['', 'Pairs with the most agreeing days (learning only uses days that count):']
        out += [f'  {p["level"] or "-":<6} {p["from"]:>5} -> {p["to"]:<5} at {p["station"]}: {p["agree"]} agree, {p["contradict"]} contradict, {p["later"]} later' for p in s['top']]
    if 'unreported' in s:
        u = s['unreported']
        never = u['never']
        looked = ', '.join(str(d) for d in s['looked'])
        out += ['', f'Trains of the timetable with no report on {looked}: {len(never)} of {u["trains"]}.', 'Reported / in the timetable, by category:']
        out += [f'  {name:<5} {cell[0]:>4} / {cell[1]:<4}' for name, cell in u['categories'].items()]
        if never:
            short = sum(1 for n in never if n['stops'] <= ts.SHORT_TRAIN)
            abroad = sum(1 for n in never if n['abroad'])
            out += [f'Of those never reported: {abroad} international, {short} with {ts.SHORT_TRAIN} stops or fewer.']
            out += [f'  {n["name"]:<10} {n["from"]} - {n["to"]} ({n["stops"]} stops{", international" if n["abroad"] else ""})' for n in never[:NEVER_LISTED]]
            if len(never) > NEVER_LISTED:
                out.append(f'  ... and {len(never) - NEVER_LISTED} more')
    return out + ['', s['sentence']]


class Command(BaseCommand):
    help = 'List the learned train stays (and one day with --date); --status says why they do or do not show.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=date.fromisoformat, default=None)
        parser.add_argument('--status', action='store_true')

    def handle(self, date=None, status=False, **options):
        if status:
            self.stdout.write('\n'.join(status_lines(ts.status())))
            return
        out = ts.report(date)
        if date:
            out['joined'] = ts.notice_links(date, ts.timetable(date))
        self.stdout.write(json.dumps(out, ensure_ascii=False, indent=1, default=str))

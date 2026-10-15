from django.core.management import BaseCommand, CommandError

from prestop_api.analytics_report import parse_period, report


class Command(BaseCommand):
    help = 'Usage report: visitors, new users, requests, features and platforms (yarn server:stats).'

    def add_arguments(self, parser):
        parser.add_argument('words', nargs='*', help='today (default), week, month or all; "this week" works too')
        parser.add_argument('--period', default=None, help='Same as the words: today, week, month, all, "this week", ...')

    def handle(self, words, period, **options):
        try:
            name = parse_period(period if period is not None else ' '.join(words))
        except ValueError as e:
            raise CommandError(str(e))
        self.stdout.write(report(name), ending='')

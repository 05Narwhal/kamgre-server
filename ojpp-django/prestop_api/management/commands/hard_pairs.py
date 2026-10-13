"""Plan known-hard trips (rural to city, across operators) through the running API and fail if any comes back empty.

    manage.py hard_pairs                                   # the local API, next weekday and the coming Saturday
    manage.py hard_pairs --api https://api.kamgre.si/api/v1 --date 2026-10-14

Each pair is asked in normal mode at four times: leaving 07:00, 12:00 and 18:30, and arriving by 15:00. A day
without any connection is fine only when Insane mode finds nothing either (the planner widens on its own,
journeys.plan). Every request goes to the API, so the whole pipeline is checked, not only OTP.
"""
import json
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

# (from, to): name, lat, lon. Kropa → Ljubljana returned nothing in normal mode on 2026-10-13 (OTP's 70 min window).
PAIRS = [
    (('Kropa', 46.2914, 14.2055), ('Ljubljana AP', 46.0577, 14.5111)),
    (('Trenta', 46.3820, 13.7530), ('Ljubljana', 46.0514, 14.5060)),
    (('Bohinjska Bistrica', 46.2733, 13.9550), ('Maribor', 46.5547, 15.6459)),
    (('Kranjska Gora', 46.4845, 13.7856), ('Novo mesto', 45.8030, 15.1689)),
    (('Piran', 45.5280, 13.5680), ('Murska Sobota', 46.6625, 16.1664)),
    (('Velike Lašče', 45.8325, 14.6367), ('Kamnik', 46.2259, 14.6121)),
    (('Lendava', 46.5636, 16.4506), ('Nova Gorica', 45.9560, 13.6480)),
    (('Gornji Grad', 46.2953, 14.8061), ('Koper', 45.5481, 13.7302)),
    (('Črnomelj', 45.5711, 15.1889), ('Jesenice', 46.4366, 14.0526)),
    (('Ljubljana Bavarski dvor', 46.0588, 14.5059), ('Bled', 46.3683, 14.1146)),
]
ASKS = [('departAt', '07:00'), ('departAt', '12:00'), ('departAt', '18:30'), ('arriveBy', '15:00')]


LOCAL = ZoneInfo('Europe/Ljubljana')


class Command(BaseCommand):
    help = 'Plan known-hard trips through the API; fail when one returns nothing although Insane mode finds a way.'

    def add_arguments(self, parser):
        parser.add_argument('--api', default='http://127.0.0.1:8066/api/v1')
        parser.add_argument('--date', action='append', help='YYYY-MM-DD (repeatable); default the next weekday and Saturday')

    def plan(self, api: str, origin, destination, mode: str, when: str, risk: str) -> dict:
        place = lambda p: {'name': p[0], 'latitude': p[1], 'longitude': p[2]}
        body = {'origin': place(origin), 'destination': place(destination), 'via': [], 'dateTime': when, 'timeMode': mode,
                'modes': ['walk', 'bus', 'rail'], 'riskMode': risk, 'minTransferSeconds': 180 if risk == 'normal' else 0}
        request = urllib.request.Request(f'{api}/journeys', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            return json.load(e)

    def handle(self, *args, **opts):
        today = date.today()
        weekday = next(today + timedelta(days=i) for i in range(1, 8) if (today + timedelta(days=i)).weekday() < 5)
        saturday = next(today + timedelta(days=i) for i in range(1, 8) if (today + timedelta(days=i)).weekday() == 5)
        days = [date.fromisoformat(d) for d in opts['date']] if opts['date'] else [weekday, saturday]
        failures = 0
        for day in days:
            for origin, destination in PAIRS:
                row = []
                for mode, clock in ASKS:
                    when = datetime.combine(day, time.fromisoformat(clock), tzinfo=LOCAL).isoformat()
                    normal = self.plan(opts['api'], origin, destination, mode, when, 'normal')
                    if 'error' in normal:
                        row.append(f'{clock}{mode[0]} ERROR {normal["error"].get("code")}')
                        failures += 1
                        continue
                    found = len(normal['data'])
                    if not found and self.plan(opts['api'], origin, destination, mode, when, 'insane').get('data'):
                        row.append(f'{clock}{mode[0]} EMPTY (Insane finds one)')
                        failures += 1
                    else:
                        row.append(f'{clock}{mode[0]} {found}{"w" if normal.get("wider") else ""}')
                self.stdout.write(f'{day} {origin[0]} → {destination[0]}: ' + ', '.join(row))
        if failures:
            raise CommandError(f'{failures} searches came back empty or failed')
        self.stdout.write(self.style.SUCCESS('every hard pair found connections'))

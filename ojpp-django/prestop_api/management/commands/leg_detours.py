"""Report drawn bus lines that take a way a bus does not drive: loops and long detours between two stops.

    manage.py leg_detours                                 # today's trips at Ljubljana AP: stretches within 1.5 km of it
    manage.py leg_detours --stations IJPP:1126954,IJPP:1127365
    manage.py leg_detours --all                           # every flagged stretch of those trips, wherever it is
    manage.py leg_detours --legs                          # also the stored routed legs (RoadLeg)
    manage.py leg_detours --legs --delete                 # ... and drop the ones serving refuses, to be routed again

A stretch is flagged when it loops back on itself (roads.LOOP) or is much longer than the straight path between its
stops (roads.DETOUR_FLAG), see roads.detours. Serving already refuses routed legs that turn round at a stop
(roads.plausible) and routes looping feed stretches (roads.bad_segments); this shows what is left. Real loops are flagged
too (a motorway junction's loop ramp, switchbacks), so a person checks what --all lists. Exits non-zero when a stretch
near a checked station is flagged.
"""
import time

from django.core.management.base import BaseCommand, CommandError

from prestop_api import geometry, roads, sources, trips


class Command(BaseCommand):
    help = 'Flag drawn bus lines with loops or detours between stops; optionally drop bad stored road legs.'

    def add_arguments(self, parser):
        parser.add_argument('--stations', default='IJPP:1126954', help='comma-separated stop ids whose trips are checked')
        parser.add_argument('--legs', action='store_true', help='also check the stored routed legs (RoadLeg)')
        parser.add_argument('--delete', action='store_true', help='with --legs: delete the flagged legs')
        parser.add_argument('--all', action='store_true', help='report flagged stretches anywhere on the trips')
        parser.add_argument('--near', type=float, default=1500, help='metres around a station that count as near it')

    def handle(self, *args, stations='', legs=False, delete=False, near=1500.0, **options):
        flagged = 0
        now = int(time.time())
        places = {s['id']: [s['longitude'], s['latitude']] for s in sources.stops.get().value['all']}
        for station in [s for s in stations.split(',') if s]:
            here = places.get(station)
            ids = {e['tripId'] for kind in ('departure', 'arrival') for e in sources.board(station, kind, now, 'sl') or [] if e['mode'] == 'bus'}
            # Wait for legs still being routed: a provisional line is not what serving settles on.
            for attempt in range(3):
                loaded = trips.load_trips(sorted(ids))
                if all(e['static'].get('complete', True) for e in loaded.values()):
                    break
                time.sleep(10)
            for trip_id, entry in sorted(loaded.items()):
                static = entry['static']
                stops = [{'lat': s['latitude'], 'lon': s['longitude'], 'name': s['name']} for s in static['stops']]
                cum = geometry.cumulative(static['geometry'])
                along = [a for a, _ in geometry.project_stops(static['geometry'], stops)]
                for d in roads.detours(static['geometry'], stops):
                    part = geometry.slice_between(static['geometry'], cum, along[d['segment']], along[d['segment'] + 1])
                    if not options['all'] and not (here and min(geometry.distance(p, here) for p in part) <= near):
                        continue
                    flagged += 1
                    self.stdout.write(f'{station} {trip_id} {static["routeName"]}: {d["from"]} → {d["to"]} {d["length"]} m '
                                      f'(straight {d["straight"]} m{", loop " + str(d["loop"]) + " m" if d["loop"] else ""})')
            self.stdout.write(f'{station}: {len(loaded)} trips checked')
        if legs:
            self._legs(delete)
        if flagged:
            raise CommandError(f'{flagged} stretches loop or detour')
        self.stdout.write(self.style.SUCCESS('no loops or detours'))

    def _legs(self, delete: bool):
        """Stored routed legs serving now refuses (roads.plausible: a router loop or turn-round) are bad cached legs;
        legs that only detour or loop in between (switchbacks, a junction's ramp) are counted for a person to check."""
        from prestop_api.models import RoadLeg
        bad, odd = [], 0
        for row in RoadLeg.objects.exclude(key__startswith='m:').iterator():
            if not row.geometry or len(row.geometry) < 2:
                continue
            a, b = ({'lat': float(p.split(',')[0]), 'lon': float(p.split(',')[1])} for p in row.key.split(';'))
            if not roads.plausible(row.geometry, a, b):
                bad.append(row.key)
                self.stdout.write(f'leg {row.key}: {round(geometry.cumulative(row.geometry)[-1])} m, refused')
            elif roads.detours(row.geometry, [a, b]):
                odd += 1
        self.stdout.write(f'{len(bad)} stored legs refused (loop or turn-round), {odd} more detour or loop in between')
        if delete and bad:
            RoadLeg.objects.filter(key__in=bad).delete()
            self.stdout.write(f'deleted {len(bad)}; they are routed again when next needed')

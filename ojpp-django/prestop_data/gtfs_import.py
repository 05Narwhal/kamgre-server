"""Import a static GTFS feed into the upstream OJPP tables.

Rows are matched through `GtfsRef` (feed-qualified GTFS ids), then through the
upstream provider ids (`ijpp_id`, `lpp_id`) so records created by the original
OJPP adapters are reused rather than duplicated. Nothing is deleted: trips that
leave the feed are marked inactive, and stop times are only replaced for trips
whose stop pattern or times changed.
"""
import csv
import io
import logging
import zipfile
from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, Iterator, List, Optional

from django.contrib.gis.geos import LineString, Point
from django.db import connection, transaction

from ojpp_common.models import (
    Operator, Route, RouteGroup, Schedule, Stop, StopLocation, StopTime, TimetableException, Trip,
)
from prestop_data.models import GtfsRef

logger = logging.getLogger(__name__)

BATCH = 5000
Kind = GtfsRef.Kind


@dataclass(frozen=True)
class FeedConfig:
    name: str
    filename: str
    # Feed ids are IJPP ids (agency, stop, route, trip), as in NAP's GTFS export.
    ijpp_ids: bool = False
    # stop_code is the LPP station ref_id and route_id the LPP route id used by the LPP adapter.
    lpp_ids: bool = False
    # agency_id -> upstream operator name, for feeds whose agency names differ from OJPP's.
    operator_names: Dict[str, str] = field(default_factory=dict)


FEEDS = {
    'ijpp': FeedConfig(name='ijpp', filename='ijpp_gtfs.zip', ijpp_ids=True),
    'lpp': FeedConfig(
        name='lpp', filename='lpp_gtfs.zip', lpp_ids=True,
        operator_names={'lpp': 'Javno podjetje Ljubljanski potniški promet d.o.o.'},
    ),
}


def parse_gtfs_time(value: str) -> Optional[time]:
    """GTFS times may exceed 24:00 for after-midnight service; OJPP stores a wall-clock TimeField."""
    if not value:
        return None
    h, m, s = (int(part) for part in value.strip().split(':'))
    return time(h % 24, m, s)


def parse_gtfs_date(value: str) -> date:
    return datetime.strptime(value.strip(), '%Y%m%d').date()


def _int_or_none(value: str) -> Optional[int]:
    value = (value or '').strip()
    return int(value) if value.isdigit() else None


def _chunks(items: list, size: int = BATCH) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


class GtfsArchive:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self.names = {n.rsplit('/', 1)[-1]: n for n in self.zip.namelist()}

    def has(self, table: str) -> bool:
        return f'{table}.txt' in self.names

    def rows(self, table: str) -> Iterable[dict]:
        if not self.has(table):
            return
        with self.zip.open(self.names[f'{table}.txt']) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig', newline=''))

    def close(self):
        self.zip.close()


class GtfsImporter:
    def __init__(self, feed: FeedConfig, archive: GtfsArchive, log=logger.info):
        self.feed = feed
        self.gtfs = archive
        self.log = log
        self.counts: Dict[str, int] = defaultdict(int)
        self.refs: Dict[str, Dict[str, int]] = defaultdict(dict)

    # -- refs ---------------------------------------------------------------

    def _load_refs(self):
        for kind, gtfs_id, object_id in GtfsRef.objects.filter(feed=self.feed.name).values_list('kind', 'gtfs_id', 'object_id'):
            self.refs[kind][gtfs_id] = object_id

    def _save_refs(self, kind: str, mapping: Dict[str, int]):
        new = [
            GtfsRef(feed=self.feed.name, kind=kind, gtfs_id=gtfs_id, object_id=object_id)
            for gtfs_id, object_id in mapping.items() if self.refs[kind].get(gtfs_id) != object_id
        ]
        GtfsRef.objects.bulk_create(
            new, batch_size=BATCH, update_conflicts=True,
            unique_fields=['feed', 'kind', 'gtfs_id'], update_fields=['object_id'],
        )
        self.refs[kind].update(mapping)

    def _upsert(self, kind: str, model, items: Dict[str, object], fields: List[str],
                fallback: Optional[str] = None) -> Dict[str, int]:
        """Create or update `items` (gtfs_id -> unsaved instance) and return gtfs_id -> pk.

        `fallback` names a unique upstream field used to adopt rows the OJPP adapters created.
        """
        known = self.refs[kind]
        existing_ids = {gid: known[gid] for gid in items if gid in known}
        if fallback:
            wanted = {getattr(obj, fallback): gid for gid, obj in items.items()
                      if gid not in existing_ids and getattr(obj, fallback) is not None}
            for pk, value in model.objects.filter(**{f'{fallback}__in': list(wanted)}).values_list('pk', fallback):
                existing_ids[wanted[value]] = pk
        alive = set(model.objects.filter(pk__in=list(existing_ids.values())).values_list('pk', flat=True))
        existing_ids = {gid: pk for gid, pk in existing_ids.items() if pk in alive}

        to_update, to_create = [], []
        for gid, obj in items.items():
            if gid in existing_ids:
                obj.pk = existing_ids[gid]
                to_update.append(obj)
            else:
                to_create.append((gid, obj))
        for chunk in _chunks(to_update):
            model.objects.bulk_update(chunk, fields)
        created = model.objects.bulk_create([obj for _, obj in to_create], batch_size=BATCH)
        result = dict(existing_ids)
        result.update({gid: obj.pk for (gid, _), obj in zip(to_create, created)})
        self._save_refs(kind, result)
        self.counts[f'{kind}_created'] += len(to_create)
        self.counts[f'{kind}_updated'] += len(to_update)
        return result

    # -- tables -------------------------------------------------------------

    def import_agencies(self) -> Dict[str, int]:
        mapping = {}
        for row in self.gtfs.rows('agency'):
            agency_id = row.get('agency_id') or ''
            name = self.feed.operator_names.get(agency_id) or row['agency_name'].strip()
            ijpp_id = _int_or_none(agency_id) if self.feed.ijpp_ids else None
            op = None
            if agency_id in self.refs[Kind.AGENCY]:
                op = Operator.objects.filter(pk=self.refs[Kind.AGENCY][agency_id]).first()
            if op is None and ijpp_id is not None:
                op = Operator.objects.filter(ijpp_id=ijpp_id).first()
            if op is None:
                op = Operator.objects.filter(name=name).first()
            if op is None:
                op = Operator.objects.create(
                    name=name,
                    ijpp_id=ijpp_id,
                    ijpp_avl_id=f'gtfs:{self.feed.name}:{agency_id}',
                    website=row.get('agency_url') or None,
                )
                self.counts['agency_created'] += 1
            elif ijpp_id is not None and op.ijpp_id is None:
                op.ijpp_id = ijpp_id
                op.save(update_fields=['ijpp_id'])
            mapping[agency_id] = op.pk
        self._save_refs(Kind.AGENCY, mapping)
        return mapping

    def service_dates(self) -> Dict[str, set]:
        weekday_cols = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
        dates: Dict[str, set] = defaultdict(set)
        for row in self.gtfs.rows('calendar'):
            days = {i for i, col in enumerate(weekday_cols) if row[col].strip() == '1'}
            d, end = parse_gtfs_date(row['start_date']), parse_gtfs_date(row['end_date'])
            while d <= end:
                if d.weekday() in days:
                    dates[row['service_id']].add(d)
                d += timedelta(days=1)
        for row in self.gtfs.rows('calendar_dates'):
            d = parse_gtfs_date(row['date'])
            if row['exception_type'].strip() == '1':
                dates[row['service_id']].add(d)
            else:
                dates[row['service_id']].discard(d)
        return dates

    def import_services(self) -> Dict[str, int]:
        """Each GTFS service becomes a schedule whose running days are explicit SET exceptions.

        OJPP's period evaluation ignores years, so explicit dates keep GTFS semantics exact.
        """
        dates = self.service_dates()
        items = {
            sid: Schedule(name=f'{self.feed.name}:{sid}'[:50], description=f'GTFS service {sid} ({self.feed.name})',
                          default_state=False)
            for sid in dates
        }
        mapping = self._upsert(Kind.SERVICE, Schedule, items, ['name', 'description', 'default_state'])
        existing = defaultdict(set)
        for sched_id, d in TimetableException.objects.filter(schedule_id__in=list(mapping.values()), action=True).values_list('schedule_id', 'date'):
            existing[sched_id].add(d)
        changed = {mapping[sid] for sid, ds in dates.items() if existing[mapping[sid]] != ds}
        for chunk in _chunks(list(changed), 500):
            TimetableException.objects.filter(schedule_id__in=chunk).delete()
        TimetableException.objects.bulk_create([
            TimetableException(schedule_id=mapping[sid], action=True, date=d)
            for sid, ds in dates.items() if mapping[sid] in changed for d in sorted(ds)
        ], batch_size=BATCH)
        self.counts['service_dates_rewritten'] = len(changed)
        return mapping

    def import_stops(self):
        rows = [r for r in self.gtfs.rows('stops') if (r.get('location_type') or '0').strip() in ('', '0')]
        groups: Dict[str, Stop] = {}
        for r in rows:
            name = r['stop_name'].strip()
            if name not in groups:
                groups[name] = Stop(name=name[:50], location=Point(float(r['stop_lon']), float(r['stop_lat']), srid=4326))
        group_map = self._upsert(Kind.STOP_GROUP, Stop, groups, ['name', 'location'])

        locations: Dict[str, StopLocation] = {}
        code_counts = Counter(_int_or_none(r.get('stop_code', '')) for r in rows) if self.feed.lpp_ids else Counter()
        lpp_unique = {c for c, n in code_counts.items() if c is not None and n == 1}
        for r in rows:
            code = _int_or_none(r.get('stop_code', '')) if self.feed.lpp_ids else None
            locations[r['stop_id']] = StopLocation(
                stop_id=group_map[r['stop_name'].strip()],
                name=r['stop_name'].strip()[:100],
                location=Point(float(r['stop_lon']), float(r['stop_lat']), srid=4326),
                ijpp_id=_int_or_none(r['stop_id']) if self.feed.ijpp_ids else None,
                lpp_id=code if code in lpp_unique else None,
                is_active=True,
            )
        fallback = 'ijpp_id' if self.feed.ijpp_ids else 'lpp_id' if self.feed.lpp_ids else None
        update_fields = ['stop', 'name', 'location', 'is_active'] + ([fallback] if fallback else [])
        return self._upsert(Kind.STOP, StopLocation, locations, update_fields, fallback=fallback)

    def import_routes(self, agencies: Dict[str, int]) -> Dict[str, int]:
        default_agency = next(iter(agencies.values()))
        group_items: Dict[str, RouteGroup] = {}
        routes: Dict[str, Route] = {}
        route_group_key: Dict[str, str] = {}
        for r in self.gtfs.rows('routes'):
            operator_id = agencies.get(r.get('agency_id') or '', default_agency)
            short = (r.get('route_short_name') or '').strip()
            long_name = (r.get('route_long_name') or '').strip()
            if short and not self.feed.ijpp_ids:
                key = f"{r.get('agency_id') or ''}:{short}"
                route_group_key[r['route_id']] = key
                color = (r.get('route_color') or '').strip()
                group_items.setdefault(key, RouteGroup(
                    operator_id=operator_id, number=short[:5], name=(long_name or short)[:100],
                    color=f'#{color}' if len(color) == 6 else '#444444',
                ))
            routes[r['route_id']] = Route(
                operator_id=operator_id,
                name=long_name[:250] if long_name and not self.feed.ijpp_ids else None,
                nvr_name=long_name[:100] or None if self.feed.ijpp_ids else None,
                nvr_number=short[:16] or None,
                route_type=f"gtfs:{(r.get('route_type') or '').strip()}",
                ijpp_id=_int_or_none(r['route_id']) if self.feed.ijpp_ids else None,
                lpp_id=r['route_id'][:36] if self.feed.lpp_ids else None,
                active=True,
            )
        group_map = self._upsert(Kind.ROUTE_GROUP, RouteGroup, group_items, ['operator', 'number', 'name', 'color'])
        for route_id, key in route_group_key.items():
            routes[route_id].route_group_id = group_map[key]
        fields = ['operator', 'name', 'nvr_name', 'nvr_number', 'route_type', 'route_group', 'active']
        if self.feed.ijpp_ids:
            fields.append('ijpp_id')
        if self.feed.lpp_ids:
            fields.append('lpp_id')
        return self._upsert(Kind.ROUTE, Route, routes, fields, fallback='ijpp_id' if self.feed.ijpp_ids else None)

    def load_shapes(self, shape_ids: set) -> Dict[str, LineString]:
        points: Dict[str, tuple] = {}
        for r in self.gtfs.rows('shapes'):
            sid = r['shape_id']
            if sid not in shape_ids:
                continue
            seq, lon, lat = points.setdefault(sid, (array('l'), array('d'), array('d')))
            seq.append(int(r['shape_pt_sequence']))
            lon.append(float(r['shape_pt_lon']))
            lat.append(float(r['shape_pt_lat']))
        shapes = {}
        for sid, (seq, lon, lat) in points.items():
            order = sorted(range(len(seq)), key=seq.__getitem__)
            if len(order) >= 2:
                shapes[sid] = LineString([(lon[i], lat[i]) for i in order], srid=4326)
        self.counts['shapes'] = len(shapes)
        return shapes

    def import_trips(self, routes: Dict[str, int], services: Dict[str, int], with_shapes: bool) -> Dict[str, int]:
        rows = list(self.gtfs.rows('trips'))
        shapes = self.load_shapes({r.get('shape_id') for r in rows if r.get('shape_id')}) if with_shapes else {}
        trips: Dict[str, Trip] = {}
        for r in rows:
            if r['route_id'] not in routes:
                self.counts['trips_skipped_unknown_route'] += 1
                continue
            shape = shapes.get(r.get('shape_id') or '')
            trips[r['trip_id']] = Trip(
                route_id=routes[r['route_id']],
                schedule_id=services.get(r['service_id']),
                headsign=(r.get('trip_headsign') or '').strip()[:256] or None,
                ijpp_id=_int_or_none(r['trip_id']) if self.feed.ijpp_ids else None,
                geometry=shape,
                geometry_is_final=shape is not None,
                active=True,
            )
        fields = ['route', 'schedule', 'headsign', 'active'] + (['geometry', 'geometry_is_final'] if with_shapes else [])
        if self.feed.ijpp_ids:
            fields.append('ijpp_id')
        mapping = self._upsert(Kind.TRIP, Trip, trips, fields, fallback='ijpp_id' if self.feed.ijpp_ids else None)
        gone = [pk for gid, pk in self.refs[Kind.TRIP].items() if gid not in mapping]
        for chunk in _chunks(gone):
            self.counts['trips_deactivated'] += Trip.objects.filter(pk__in=chunk, active=True).update(active=False)
        return mapping

    def import_stop_times(self, trips: Dict[str, int], stops: Dict[str, int]):
        wanted = defaultdict(list)
        for r in self.gtfs.rows('stop_times'):
            trip_pk, stop_pk = trips.get(r['trip_id']), stops.get(r['stop_id'])
            if trip_pk is None or stop_pk is None:
                self.counts['stop_times_skipped'] += 1
                continue
            wanted[trip_pk].append((
                int(r['stop_sequence']), stop_pk,
                parse_gtfs_time(r.get('arrival_time', '')), parse_gtfs_time(r.get('departure_time', '')),
            ))
        for pattern in wanted.values():
            pattern.sort()

        existing = defaultdict(list)
        trip_pks = list(trips.values())
        for chunk in _chunks(trip_pks, 20000):
            for trip_id, seq, stop_id, arr, dep in (
                StopTime.objects.filter(trip_id__in=chunk, active=True)
                .values_list('trip_id', 'sequence_num', 'stop_location_id', 'time_arrival', 'time_departure')
            ):
                existing[trip_id].append((seq, stop_id, arr, dep))
        changed = [pk for pk in trip_pks if sorted(existing.get(pk, [])) != wanted.get(pk, [])]
        for chunk in _chunks(changed, 2000):
            StopTime.objects.filter(trip_id__in=chunk).delete()
        new_rows = [
            StopTime(trip_id=pk, sequence_num=seq, stop_location_id=stop_id, time_arrival=arr, time_departure=dep, active=True)
            for pk in changed for seq, stop_id, arr, dep in wanted.get(pk, [])
        ]
        for chunk in _chunks(new_rows, 20000):
            StopTime.objects.bulk_create(chunk, batch_size=BATCH)
        self.counts['trips_with_new_stop_times'] = len(changed)
        self.counts['stop_times_written'] = len(new_rows)

    def refresh_computed_fields(self):
        """Fill the computed columns bulk writes bypass (trip name, route ends, stop location count)."""
        trip_tbl, st_tbl, sl_tbl, stop_tbl, route_tbl, ref_tbl = (
            m._meta.db_table for m in (Trip, StopTime, StopLocation, Stop, Route, GtfsRef))
        with connection.cursor() as c:
            c.execute(f'''
                WITH ends AS (
                    SELECT st.trip_id,
                           (array_agg(s.name ORDER BY st.sequence_num))[1] AS first_name,
                           (array_agg(s.name ORDER BY st.sequence_num DESC))[1] AS last_name
                    FROM {st_tbl} st
                    JOIN {sl_tbl} sl ON sl.id = st.stop_location_id
                    JOIN {stop_tbl} s ON s.id = sl.stop_id
                    JOIN {ref_tbl} r ON r.feed = %s AND r.kind = 'trip' AND r.object_id = st.trip_id
                    GROUP BY st.trip_id
                )
                UPDATE {trip_tbl} t SET name = left(ends.first_name || ' - ' || ends.last_name, 300)
                FROM ends WHERE t.id = ends.trip_id
            ''', [self.feed.name])
            c.execute(f'''
                WITH first_trip AS (
                    SELECT t.route_id, min(t.id) AS trip_id FROM {trip_tbl} t
                    JOIN {ref_tbl} r ON r.feed = %s AND r.kind = 'route' AND r.object_id = t.route_id
                    WHERE t.active GROUP BY t.route_id
                ), ends AS (
                    SELECT ft.route_id,
                           (array_agg(sl.stop_id ORDER BY st.sequence_num))[1] AS first_stop,
                           (array_agg(sl.stop_id ORDER BY st.sequence_num DESC))[1] AS last_stop
                    FROM first_trip ft
                    JOIN {st_tbl} st ON st.trip_id = ft.trip_id
                    JOIN {sl_tbl} sl ON sl.id = st.stop_location_id
                    GROUP BY ft.route_id
                )
                UPDATE {route_tbl} rt SET first_stop_id = ends.first_stop, last_stop_id = ends.last_stop
                FROM ends WHERE rt.id = ends.route_id
            ''', [self.feed.name])
            c.execute(f'''
                UPDATE {stop_tbl} s SET location_count = sub.n
                FROM (SELECT stop_id, count(*) AS n FROM {sl_tbl} GROUP BY stop_id) sub
                WHERE s.id = sub.stop_id AND s.location_count IS DISTINCT FROM sub.n
            ''')

    # -- entry point --------------------------------------------------------

    def run(self, with_shapes: bool = True) -> Dict[str, int]:
        with transaction.atomic():
            self._load_refs()
            self.log(f'[{self.feed.name}] agencies')
            agencies = self.import_agencies()
            self.log(f'[{self.feed.name}] services')
            services = self.import_services()
            self.log(f'[{self.feed.name}] stops')
            stops = self.import_stops()
            self.log(f'[{self.feed.name}] routes')
            routes = self.import_routes(agencies)
            self.log(f'[{self.feed.name}] trips{" and shapes" if with_shapes else ""}')
            trips = self.import_trips(routes, services, with_shapes)
            self.log(f'[{self.feed.name}] stop times')
            self.import_stop_times(trips, stops)
            self.log(f'[{self.feed.name}] computed fields')
            self.refresh_computed_fields()
        return dict(self.counts)

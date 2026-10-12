import io
import zipfile
from datetime import date, time

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from ojpp_common.models import Operator, Route, Schedule, StopLocation, StopTime, Trip, Vehicle, VehicleLocation
from ojpp_common.util import is_schedule_active
from prestop_data.gtfs_import import FEEDS, GtfsArchive, GtfsImporter, parse_gtfs_time
from prestop_data.models import GtfsImport

BASE = {
    'agency.txt': 'agency_id,agency_name,agency_url,agency_timezone\n1123,Arriva d.o.o.,http://www.ijpp.si,Europe/Ljubljana\n',
    'calendar.txt': 'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n'
                    '10,1,1,1,1,1,0,0,20261005,20261018\n',
    'calendar_dates.txt': 'service_id,date,exception_type\n10,20261010,1\n10,20261012,2\n',
    'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon\n'
                 '501,Kranj AP,46.2437,14.3559\n502,Kranj AP,46.2438,14.3560\n503,Ljubljana AP,46.0569,14.5103\n',
    'routes.txt': 'route_id,agency_id,route_short_name,route_long_name,route_type\n700,1123,,KR LJ 1 (700),3\n',
    'shapes.txt': 'shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n'
                  's1,46.0569,14.5103,2\ns1,46.2437,14.3559,1\n',
    'trips.txt': 'route_id,service_id,trip_id,trip_headsign,shape_id\n700,10,9001,Ljubljana,s1\n700,10,9002,,\n',
    'stop_times.txt': 'trip_id,arrival_time,departure_time,stop_id,stop_sequence\n'
                      '9001,23:50:00,23:50:00,501,1\n9001,24:40:00,24:40:00,503,2\n'
                      '9002,6:03:00,6:03:00,502,1\n9002,6:50:00,6:50:00,503,2\n',
}


def make_zip(files: dict) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    buf.seek(0)
    return buf


def run_import(files: dict) -> dict:
    return GtfsImporter(FEEDS['ijpp'], GtfsArchive(make_zip(files)), log=lambda _: None).run()


class GtfsImportTest(TestCase):
    def test_after_midnight_times_wrap_to_wall_clock(self):
        self.assertEqual(parse_gtfs_time('24:40:00'), time(0, 40))
        self.assertEqual(parse_gtfs_time('6:03:00'), time(6, 3))
        self.assertIsNone(parse_gtfs_time(''))

    def test_import_maps_ijpp_ids_and_computed_fields(self):
        run_import(BASE)
        trip = Trip.objects.get(ijpp_id=9001)
        self.assertEqual(trip.name, 'Kranj AP - Ljubljana AP')
        self.assertEqual(trip.headsign, 'Ljubljana')
        self.assertEqual(trip.geometry.coords, ((14.3559, 46.2437), (14.5103, 46.0569)))
        self.assertEqual(list(trip.stoptimes.order_by('sequence_num').values_list('time_departure', flat=True)),
                         [time(23, 50), time(0, 40)])
        route = Route.objects.get(ijpp_id=700)
        self.assertEqual((route.first_stop.name, route.last_stop.name), ('Kranj AP', 'Ljubljana AP'))
        self.assertEqual(route.operator.ijpp_id, 1123)
        # Two poles named "Kranj AP" share one stop group.
        self.assertEqual(StopLocation.objects.get(ijpp_id=501).stop_id, StopLocation.objects.get(ijpp_id=502).stop_id)
        self.assertEqual(StopLocation.objects.get(ijpp_id=501).stop.location_count, 2)

    def test_service_dates_follow_gtfs_semantics(self):
        run_import(BASE)
        schedule = Trip.objects.get(ijpp_id=9001).schedule
        self.assertTrue(is_schedule_active(schedule, date(2026, 10, 9)))   # Friday
        self.assertTrue(is_schedule_active(schedule, date(2026, 10, 10)))  # added Saturday
        self.assertFalse(is_schedule_active(schedule, date(2026, 10, 11)))  # Sunday
        self.assertFalse(is_schedule_active(schedule, date(2026, 10, 12)))  # removed Monday
        self.assertFalse(is_schedule_active(schedule, date(2027, 10, 8)))   # outside the year range

    def test_reimport_is_idempotent_and_keeps_history(self):
        run_import(BASE)
        trip = Trip.objects.get(ijpp_id=9001)
        vehicle = Vehicle.objects.create(ijpp_id=1)
        VehicleLocation.objects.create(vehicle=vehicle, trip=trip, time=timezone.now(), location=Point(14.5, 46.0))
        stop_time_ids = set(StopTime.objects.values_list('id', flat=True))

        counts = run_import(BASE)

        self.assertEqual(counts['trips_with_new_stop_times'], 0)
        self.assertEqual(set(StopTime.objects.values_list('id', flat=True)), stop_time_ids)
        self.assertEqual(Trip.objects.count(), 2)
        self.assertEqual(Schedule.objects.count(), 1)
        self.assertEqual(Operator.objects.count(), 1)
        self.assertEqual(VehicleLocation.objects.get().trip_id, trip.id)

    def test_trips_leaving_the_feed_are_deactivated_not_deleted(self):
        run_import(BASE)
        changed = dict(BASE)
        changed['trips.txt'] = 'route_id,service_id,trip_id,trip_headsign,shape_id\n700,10,9001,Ljubljana,s1\n'
        changed['stop_times.txt'] = ('trip_id,arrival_time,departure_time,stop_id,stop_sequence\n'
                                     '9001,23:55:00,23:55:00,501,1\n9001,24:40:00,24:40:00,503,2\n')
        counts = run_import(changed)
        self.assertFalse(Trip.objects.get(ijpp_id=9002).active)
        self.assertEqual(counts['trips_with_new_stop_times'], 1)
        self.assertEqual(Trip.objects.get(ijpp_id=9001).stoptimes.get(sequence_num=1).time_departure, time(23, 55))

    def test_schedule_cache_sees_later_imports(self):
        from ojpp_common import util
        d = date(2026, 10, 9)
        self.assertEqual(util.get_schedules_for_date(d), [])
        run_import(BASE)
        GtfsImport.objects.create(feed='ijpp', source_url='http://x/', sha256='0', started=timezone.now(),
                                  finished=timezone.now(), succeeded=True)
        self.assertEqual(len(util.get_schedules_for_date(d)), 1)

    def test_adopts_rows_created_by_upstream_adapters(self):
        op = Operator.objects.create(name='Arriva d.o.o.', ijpp_avl_id='arriva')
        pole = StopLocation.objects.create(ijpp_id=501, name='old name')
        run_import(BASE)
        self.assertEqual(Operator.objects.get().pk, op.pk)
        self.assertEqual(StopLocation.objects.get(ijpp_id=501).pk, pole.pk)
        self.assertEqual(StopLocation.objects.get(ijpp_id=501).name, 'Kranj AP')

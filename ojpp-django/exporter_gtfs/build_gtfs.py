#!/usr/bin/env python
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import IntEnum
from typing import BinaryIO
from zipfile import ZipFile

import django
import pandas as pd
from django.contrib.gis.db.models.functions import AsGeoJSON
from django.db.models import QuerySet
from tqdm import tqdm

from ojpp_common.models import StopLocation, Schedule, Route, StopTime, Trip, Operator
from ojpp_common.util import is_schedule_active


@dataclass(slots=True)
class TripStruct:
    trip_id: str
    route_id: str
    service_id: str
    trip_headsign: str
    shape_id: str


@dataclass(slots=True)
class ShapeStruct:
    shape_id: str
    shape_pt_lat: float
    shape_pt_lon: float
    shape_pt_sequence: int


##############
#   DJANGO   #
##############
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")
django.setup()


##############
#   CONFIG   #
##############

dist_cache = {}

SZ_PP_IJPP_ID = '1161'
class RouteType(IntEnum):
    RAIL = 2
    BUS = 3

def calc_dist(p1, p2):
    # Radius of the Earth in kilometers
    global dist_cache
    key = f'{p1[0]}-{p1[1]}-{p2[0]}-{p2[1]}'

    if key in dist_cache:
        return dist_cache[key]

    R = 6371.0

    # Coordinates in decimal degrees
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])

    # Change in coordinates
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    # Haversine formula
    a = math.sin(delta_lat / 2)**2 + math.cos(lat1) * \
        math.cos(lat2) * math.sin(delta_lon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c

    dist_cache[key] = distance

    return distance


distcache = {}


def get_dates_list(start_date, end_date):
    dates = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date)
        current_date += timedelta(days=1)
    return dates


def calc_dist_traveled(trip, stoptime):
    if not hasattr(trip, 'shape'):
        return None
    if f'{trip.shape_id}-{stoptime.stop_location_id}' in distcache:
        return distcache[f'{trip.shape_id}-{stoptime.stop_location_id}']

    shape = trip.shape
    closest_i = 0
    closest_dist = (stoptime.stop_location.location.y - shape.points[0][0])**2 + (
        stoptime.stop_location.location.x - shape.points[0][1])**2
    for i in range(1, len(shape.points)):
        # find closest point
        new_dist = (stoptime.stop_location.location.y - shape.points[i][0])**2 + (
            stoptime.stop_location.location.x - shape.points[i][1])**2
        if new_dist < closest_dist:
            closest_dist = new_dist
            closest_i = i
    dist_traveled = shape.distance[closest_i]
    distcache[f'{trip.shape_id}-{stoptime.stop_location_id}'] = dist_traveled
    return dist_traveled


def gtfs_time(dt: time, actually_crosses_midnight: bool) -> str:
    """Format the given datetime according to the GTFS datetime spec. If the route has crossed midnight, the hour will be over 24."""
    if actually_crosses_midnight:
        # We need to add 24h to the string representation of the time
        hour = 24 + dt.hour
    else:
        hour = dt.hour
    return f'{hour:02}:{dt.minute:02}:{dt.second:02}'


def main(out_file: BinaryIO, args=None, opts=None):
    if opts is None:
        opts = {}

    USE_NATIVE_IDS = opts.get('native_ids') or False  # noqa: caps

    # Default date settings
    start_date = (datetime.now() - timedelta(days=1)).date()
    end_date = (datetime.now() + timedelta(days=365)).date()

    if 'start_date' in opts:
        start_date = datetime.strptime(opts['start_date'], '%Y-%m-%d').date()
    if 'end_date' in opts:
        end_date = datetime.strptime(opts['end_date'], '%Y-%m-%d').date()

    stops = StopLocation.objects.exclude(stop__ijpp_id__isnull=True).prefetch_related('stop')
    stops_df = pd.DataFrame(list([{
        'stop_id': stop.ijpp_id if not USE_NATIVE_IDS else stop.id,
        'stop_name': stop.stop.name,
        'stop_lat': stop.location.y,
        'stop_lon': stop.location.x
    } for stop in stops]))

    valid_stop_ids = set(stops_df['stop_id'])

    # Load active schedules and service IDs
    schedules: QuerySet[Schedule] = Schedule.objects.filter(ijpp_id__isnull=False).prefetch_related('periods', 'exceptions')
    calendar_df = pd.DataFrame(list([{
        'service_id': str(schedule.id) if USE_NATIVE_IDS else str(schedule.ijpp_id),
        'monday': 0,
        'tuesday': 0,
        'wednesday': 0,
        'thursday': 0,
        'friday': 0,
        'saturday': 0,
        'sunday': 0,
        'start_date': start_date.strftime('%Y%m%d'),
        'end_date': end_date.strftime('%Y%m%d')
    } for schedule in schedules]))

    # Precalculate active dates for each schedule in the interval [start_date, end_date]
    calendar_dates = []

    for schedule in tqdm(schedules, desc="Processing calendar dates"):
        for day in get_dates_list(start_date, end_date):
            calendar_dates.append({
                'service_id': str(schedule.id) if USE_NATIVE_IDS else str(schedule.ijpp_id),
                'date': day.strftime('%Y%m%d'),
                'exception_type': 1 if is_schedule_active(schedule, day) else 2
            })
    calendar_dates_df = pd.DataFrame(calendar_dates)

    # Insert active routes, trips, stop times, and shapes into GTFS

    print('Processing routes...', end='', flush=True)

    routes = (Route.objects
              .prefetch_related('operator', 'trips', 'trips__schedule', 'trips__stoptimes', 'trips__stoptimes__stop_location', 'trips__stoptimes__stop_location__stop')
              .filter(active=True, trips__active=True, ijpp_id__isnull=False)
              .order_by('id', 'trips__id', 'trips__stoptimes__sequence_num')
              .distinct('id'))

    print('fetched', len(routes), 'routes, making dataframe...', end='', flush=True)

    routes_df = pd.DataFrame([{
        'route_id': str(route.id) if USE_NATIVE_IDS else str(route.ijpp_id),
        'route_short_name': route.nvr_name,
        'route_long_name': route.name,
        'route_type': RouteType.BUS if route.operator.ijpp_id != SZ_PP_IJPP_ID else RouteType.RAIL,
        'agency_id': str(route.operator_id) if USE_NATIVE_IDS else str(route.operator.ijpp_id)
    } for route in routes])

    print('DONE')

    print('Processing agencies...', end='', flush=True)

    operators = Operator.objects.filter(id__in={r.operator_id for r in routes})
    agencies_df = pd.DataFrame([{
		'agency_id': str(operator.id) if USE_NATIVE_IDS else str(operator.ijpp_id),
		'agency_name': operator.name,
		'agency_url': operator.website or 'https://ijpp.si',
		'agency_timezone': 'Europe/Ljubljana'
	} for operator in operators])

    print('DONE')

    print('Processing trips...', end='', flush=True)
    trips = []
    shape_map = {}

    shapes = []

    def process_trip(route, trip, shape_map, trips, shape_ids):
        shape_id = hashlib.md5(trip.json.encode()).hexdigest() if trip.json else None
        # if the trip stop times are not valid, skip the trip
        mapped_stop_ids = {trip.stop_location.ijpp_id for trip in trip.stoptimes.all()}
        if not all(stop_id in valid_stop_ids for stop_id in mapped_stop_ids):
            return
        trips.append(TripStruct(
            trip_id=str(trip.id) if USE_NATIVE_IDS else str(trip.ijpp_id),
            route_id=str(route.id) if USE_NATIVE_IDS else str(route.ijpp_id),
            service_id=str(trip.schedule_id) if USE_NATIVE_IDS else str(trip.schedule.ijpp_id),
            trip_headsign=trip.name or trip.headsign or '',
            shape_id=shape_id
        ))
        if trip.geometry and shape_id not in shape_map:
            shape_map[shape_id] = trip.json
            shape_ids.add(shape_id)

    def process_shape(shape_id, shape, shapes):
        i = 1
        for point in shape['coordinates']:
            shapes.append(ShapeStruct(
                shape_id=shape_id,
                shape_pt_lat=point[1],
                shape_pt_lon=point[0],
                shape_pt_sequence=i
            ))
            i += 1


    print('Processing routes...', end='', flush=True)

    shape_ids = set()
    for route in tqdm(routes, desc="Processing trips"):
        # Convert geometry to GeoJSON since it's much faster for some reason
        for trip in Trip.objects.filter(route=route).annotate(json=AsGeoJSON('geometry')).prefetch_related('stoptimes', 'stoptimes__stop_location'):
            process_trip(route, trip, shape_map, trips, shape_ids)

    for shape_id, shape in tqdm(shape_map.items(), desc="Processing shapes"):
        shape = json.loads(shape)
        process_shape(shape_id, shape, shapes)

    print('making trip dataframe...', end='', flush=True)
    trips_df = pd.DataFrame(trips)

    print('making shapes dataframe...', end='', flush=True)
    shapes_df = pd.DataFrame(shapes)

    print('DONE')

    stop_times = []
    stop_ids = set()
    for route in tqdm(routes, desc="Processing stop times"):
        for trip in route.trips.all():

            # Check that all stop locations are valid
            mapped_stop_ids = set(trip.stoptimes.all().values_list('stop_location__ijpp_id', flat=True))
            if not mapped_stop_ids or not all(stop_id in valid_stop_ids for stop_id in mapped_stop_ids):
                continue

            stoptimes: list[StopTime] = sorted(trip.stoptimes.all(), key=lambda x: x.sequence_num)

            # If the first stop time is after the last stop time, the trip crosses midnight
            crosses_midnight = stoptimes[0].time_departure > stoptimes[-1].time_arrival

            for stoptime in stoptimes:
                # Skip stop times with missing times
                if not stoptime.time_arrival and not stoptime.time_departure:
                    continue

                # If one is missing, assume arrival == departure
                fixed_time_arrival = stoptime.time_arrival or stoptime.time_departure
                fixed_time_departure = stoptime.time_departure or stoptime.time_arrival

                # Convert to "GTFS time" (hours over 24 if going over midnight)
                arrival_str = gtfs_time(fixed_time_arrival, crosses_midnight and fixed_time_arrival < stoptimes[0].time_departure)
                departure_str = gtfs_time(fixed_time_departure, crosses_midnight and fixed_time_departure < stoptimes[0].time_departure)

                stop_times.append({
                    'trip_id': str(trip.id) if USE_NATIVE_IDS else str(trip.ijpp_id),
                    'stop_id': str(stoptime.stop_location.id) if USE_NATIVE_IDS else str(stoptime.stop_location.ijpp_id),
                    'arrival_time': arrival_str,
                    'departure_time': departure_str,
                    'stop_sequence': stoptime.sequence_num
                })
                stop_ids |= {stoptime.stop_location.ijpp_id if not USE_NATIVE_IDS else stoptime.stop_location.id}

    stop_times_df = pd.DataFrame(stop_times)

    # Remove stops that are not in the stop_times
    stops_df = stops_df[stops_df['stop_id'].isin(stop_ids)]

    # Write GTFS feed
    print('Writing GTFS feed...')
    print('Stats:')
    print('Stops:', len(stops_df))
    print('Routes:', len(routes_df))
    print('Trips:', len(trips_df))
    print('Stop times:', len(stop_times_df))
    print('Shapes:', len(shapes_df))
    print('Calendar:', len(calendar_df))
    print('Calendar dates:', len(calendar_dates_df))
    print('Agencies:', len(agencies_df))

    print('Writing to file...')
    with ZipFile(out_file, 'w') as zf:
        zf.writestr('stops.txt', stops_df.to_csv(index=False, float_format='%.6f', header=True))
        zf.writestr('calendar.txt', calendar_df.to_csv(index=False, header=True))
        zf.writestr('calendar_dates.txt', calendar_dates_df.to_csv(index=False, header=True))
        zf.writestr('agency.txt',  agencies_df.to_csv(index=False, header=True))
        zf.writestr('routes.txt', routes_df.to_csv(index=False, header=True))
        zf.writestr('trips.txt', trips_df.to_csv(index=False, header=True))
        zf.writestr('shapes.txt', shapes_df.to_csv(index=False, header=True, float_format='%.6f'))
        zf.writestr('stop_times.txt', stop_times_df.to_csv(index=False, header=True))

        print('DONE')

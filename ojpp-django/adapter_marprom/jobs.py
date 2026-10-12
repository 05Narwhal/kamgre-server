import io
import re
import zipfile
from collections import defaultdict
from datetime import date, time, datetime
from io import BytesIO

import aiohttp
import django
import os

import pytz
import requests
import transitfeed

from asgiref.sync import sync_to_async
from django.core.files import File
from django.db.models import Q
from django.utils import timezone
from psqlextra.types import ConflictAction

from adapter_marprom.marprom_api import MarpromAPI, GetLines, GetLineInfo
from ojpp_core.util import seconds_to_time

if __name__ == '__main__':
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")
    django.setup()

import asyncio

from ojpp_common.util import interpolate_bearing, deduplicate_locations
from ojpp_common.models import *

MARPROM_BASE = 'http://marprom.nas.frangez.me/'

last_coords = {}

api = MarpromAPI()


async def marprom_update_locations():
    async with aiohttp.request('GET', MARPROM_BASE + '/OBA/GetActiveDeviceDetails') as res:
        res.raise_for_status()
        data = await res.json()

    time = timezone.now()

    locations = {}

    operator = await Operator.objects.aget(
        name='Javno podjetje za mestni potniški promet Marprom, d.o.o.',
    )

    for loc in data.get('Vehicles', []):
        vehicle, _ = await Vehicle.objects.aget_or_create(
            operator_vehicle_id=loc['BusCode'],
            operator=operator,
        )
        # try:
        #    trip = await Trip.objects.aget(ijpp_id=loc.monitoredVehicleJourney.LineRef)
        #    trip_id = trip.id
        # except Trip.DoesNotExist:
        #    trip_id = None
        trip_id = None

        locations[loc['BusCode']] = dict(
            vehicle_id=vehicle.id,
            trip_id=trip_id,
            location=Point(
                loc['Lon'],
                loc['Lat'],
            ),
            time=time,
            bearing=None
        )

    locations = await interpolate_bearing(locations.values(), operator)

    locations = deduplicate_locations(locations)

    if locations:
        await sync_to_async(
            VehicleLocation.objects.on_conflict(['vehicle_id', 'time'], ConflictAction.UPDATE).bulk_insert)(locations)

    print('[Marprom] Loaded', len(locations), 'locations')

    pass


async def marprom_update_stops():
    async with aiohttp.request('GET', MARPROM_BASE + '/OBA/GetAllStops') as res:
        res.raise_for_status()
        data = await res.json()

    stops = data['Stops']
    for stop in stops:
        stop['_locations'] = []

    print('[Marprom] Loaded', len(stops), 'stops')

    async with aiohttp.request('GET', MARPROM_BASE + '/OBA/GetAllStopPoints') as res:
        res.raise_for_status()
        data = await res.json()

    stop_points = data['StopPoints']
    stop_map = {s['StopId']: s for s in stops}

    print('[Marprom] Loaded', len(stop_points), 'stop points')

    for stop_point in stop_points:
        try:
            stop = stop_map[stop_point['StopID']]
            stop['_locations'].append(stop_point)
        except IndexError:
            logging.exception(f'Error while processing stop point {stop_point}')
        except KeyError:
            # This most often happens due to test/temporary stops which do not have a "StopID"
            logging.exception(f'Error while processing stop point {stop_point}')

    for _stop in stops:
        if 'Lon' not in _stop:
            continue
        try:
            stop, _ = await Stop.objects.aget_or_create(
                marprom_id=_stop['StopId'],
                defaults=dict(
                    name=_stop['Name'],
                    location=Point(
                        _stop['Lon'],
                        _stop['Lat'],
                    ),
                ),
            )

            for _stop_location in _stop['_locations']:
                if 'Lon' not in _stop_location:
                    continue
                try:
                    stop_location, _ = await StopLocation.objects.aget_or_create(
                        marprom_id=_stop_location['StopPointId'],
                        defaults=dict(
                            stop_id=stop.id,
                            name=_stop_location['Name'],
                            location=Point(
                                _stop_location['Lon'],
                                _stop_location['Lat'],
                            ),
                        )
                    )
                except:
                    logging.exception(f'Error while processing stop location {_stop_location}')
        except:
            logging.exception(f'Error while processing stop {_stop}')


    stops_without_numbers = {s.marprom_id: s async for s in StopLocation.objects.filter(marprom_id__isnull=False).filter(Q(operator_stop_id__isnull=True) | Q(operator_stop_id=''))}
    if len(stops_without_numbers) > 0:
        print(f'[Marprom] Found {len(stops_without_numbers)} stops without numbers')

        RE_STOP = re.compile('href.+?stop=(\d+).+?paddingTd">(\d+)<', re.S | re.M)

        async with aiohttp.request('GET', MARPROM_BASE) as res:
            res.raise_for_status()
            data = await res.text()

        for stop_id, stop_number in RE_STOP.findall(data):
            stop_id = int(stop_id)
            if stop_id in stops_without_numbers:
                stop = stops_without_numbers[stop_id]
                stop.operator_stop_id = stop_number
                await stop.asave()

    print('[Marprom] Saved all')


async def marprom_update_routes():
    operator = await Operator.objects.aget(
        name='Javno podjetje za mestni potniški promet Marprom, d.o.o.',
    )

    stop_locations = StopLocation.objects.filter(marprom_id__isnull=False)
    stoploc_by_marprom_id = {s.marprom_id: s async for s in stop_locations}
    pytz_timezone = pytz.timezone('Europe/Ljubljana')

    async with aiohttp.request('GET', 'http://gtfs.derp.si/marprom_gtfs_official.zip') as res:
        res.raise_for_status()
        file = io.BytesIO(await res.read())
    with zipfile.ZipFile(file) as zip:
        loader = transitfeed.Loader(zip=zip)
        gtfs_schedule: transitfeed.Schedule = loader.Load()

    route_groups_by_marprom_id = {}
    for route in gtfs_schedule.routes.values():
        route: transitfeed.Route
        route_groups_by_marprom_id[route.route_id] = dict(
            operator=operator,
            marprom_id=route.route_id,
            name=route.route_long_name,
            number=route.route_short_name,
        )
    route_groups_by_marprom_id = await sync_to_async(RouteGroup.objects.on_conflict(['marprom_id'], ConflictAction.UPDATE).bulk_insert)(route_groups_by_marprom_id.values())
    route_groups_by_marprom_id = {r['marprom_id']: r for r in route_groups_by_marprom_id}

    print(f'[Marprom] Saved {len(route_groups_by_marprom_id)} route groups')

    routes_by_fakeid = {}
    gtfs_trips_by_route_fakeid = {}

    for trip in gtfs_schedule.trips.values():
        trip: transitfeed.Trip
        route_fakeid = trip.trip_short_name + ' ' + trip.trip_headsign
        if route_fakeid not in routes_by_fakeid:
            route_group = route_groups_by_marprom_id[trip.route_id]
            route = dict(
                operator=operator,
                marprom_id=trip.trip_id,
                route_group_id=route_group['id'],
                name=trip.trip_short_name + ' ' + trip.trip_headsign,
            )
            routes_by_fakeid[route_fakeid] = route
            gtfs_trips_by_route_fakeid[route_fakeid] = []

        gtfs_trips_by_route_fakeid[route_fakeid].append(trip)

    routes_by_fakeid = await sync_to_async(Route.objects.on_conflict(['marprom_id'], ConflictAction.UPDATE).bulk_insert)(routes_by_fakeid.values())
    routes_by_fakeid = {r['name']: r for r in routes_by_fakeid}

    print(f'[Marprom] Saved {len(routes_by_fakeid)} routes')

    schedules_by_marprom_id = {}
    for service_period in gtfs_schedule.service_periods.values():
        service_period: transitfeed.ServicePeriod
        schedules_by_marprom_id[service_period.service_id] = dict(
            marprom_id=service_period.service_id,
            name=f"MBSP-{service_period.service_id}"
        )

    schedules_by_marprom_id = await sync_to_async(Schedule.objects.on_conflict(['marprom_id'], ConflictAction.UPDATE).bulk_insert)(schedules_by_marprom_id.values())
    schedules_by_marprom_id = {r['marprom_id']: r for r in schedules_by_marprom_id}

    timetable_periods_by_marprom_id = {}
    timetable_exceptions_by_marprom_id = {}
    for service_period in gtfs_schedule.service_periods.values():
        service_period: transitfeed.ServicePeriod
        schedule = schedules_by_marprom_id[service_period.service_id]
        timetable_periods_by_marprom_id[schedule["id"]] = dict(
            schedule_id=schedule['id'],
            marprom_id=f"MBTP-{service_period.service_id}-{service_period.start_date}-{service_period.end_date}",
            action=True,
            day_from=int(service_period.start_date[6:8]),
            month_from=int(service_period.start_date[4:6]),
            year_from=int(service_period.start_date[0:4]),
            day_to=int(service_period.end_date[6:8]),
            month_to=int(service_period.end_date[4:6]),
            year_to=int(service_period.end_date[0:4]),
            monday=service_period.day_of_week[0],
            tuesday=service_period.day_of_week[1],
            wednesday=service_period.day_of_week[2],
            thursday=service_period.day_of_week[3],
            friday=service_period.day_of_week[4],
            saturday=service_period.day_of_week[5],
            sunday=service_period.day_of_week[6],
            holidays=service_period.day_of_week[6]
        )
        for date_as_key, date in service_period.date_exceptions.items():
            timestamp = datetime.strptime(date_as_key, '%Y%m%d')
            timestamp = pytz_timezone.localize(timestamp)
            timetable_exceptions_by_marprom_id[f"MBTE-{service_period.service_id}-{date_as_key}"] = dict(
                schedule_id=schedule['id'],
                marprom_id=f"MBTE-{service_period.service_id}-{date_as_key}",
                action=date[0] == '1',  # 1 = add, 2 = remove
                # load time from yyyyMMdd
                date=timestamp
            )

    timetable_exceptions_by_marprom_id = await sync_to_async(TimetableException.objects.on_conflict(['marprom_id'], ConflictAction.UPDATE).bulk_insert)(timetable_exceptions_by_marprom_id.values())
    timetable_exceptions_by_marprom_id = {r['marprom_id']: r for r in timetable_exceptions_by_marprom_id}

    timetable_periods_by_marprom_id = await sync_to_async(TimetablePeriod.objects.on_conflict(['marprom_id'], ConflictAction.UPDATE).bulk_insert)(timetable_periods_by_marprom_id.values())
    timetable_periods_by_marprom_id = {r['marprom_id']: r for r in timetable_periods_by_marprom_id}

    print(f'[Marprom] Saved {len(schedules_by_marprom_id)} schedules')



    trips_by_marprom_id = {}
    for route_fakeid, trips in gtfs_trips_by_route_fakeid.items():
        route = routes_by_fakeid[route_fakeid]
        for trip in trips:
            trip: transitfeed.Trip
            shape: transitfeed.Shape = gtfs_schedule.GetShape(trip.shape_id)
            coords = [(p[1], p[0]) for p in shape.points]

            trips_by_marprom_id[trip.trip_id] = dict(
                route_id=route['id'],
                marprom_id=trip.trip_id,
                schedule_id=schedules_by_marprom_id[trip.service_id]['id'],
                geometry=LineString(coords),
                geometry_is_final=True,
            )

    trips_by_marprom_id = await sync_to_async(Trip.objects.on_conflict(['marprom_id'], ConflictAction.UPDATE).bulk_insert)(trips_by_marprom_id.values())
    trips_by_marprom_id = {r['marprom_id']: r for r in trips_by_marprom_id}

    print(f'[Marprom] Saved {len(trips_by_marprom_id)} trips')

    deleted = await sync_to_async(StopTime.objects.filter(trip__marprom_id__isnull=False)._raw_delete)(using='default')
    print(f'[Marprom] Deleted {deleted} stoptimes')

    stop_times = []

    for route_fakeid, trips in gtfs_trips_by_route_fakeid.items():
        route = routes_by_fakeid.get(route_fakeid)

        for gtfs_trip in trips:
            gtfs_trip: transitfeed.Trip
            trip = trips_by_marprom_id[gtfs_trip.trip_id]

            gtfs_stoptimes = gtfs_trip.GetStopTimes()
            for i, stoptime in enumerate(gtfs_stoptimes):
                stoptime: transitfeed.StopTime
                stoploc = stoploc_by_marprom_id.get(int(stoptime.stop.stop_id))

                if not stoploc:
                    print(f'[Marprom] Missing stoploc for {stoptime.stop.stop_id}')
                    continue

                stop_times.append(dict(
                    trip_id=trip['id'],
                    stop_location=stoploc,
                    time_arrival=seconds_to_time(stoptime.arrival_secs) if i != 0 else None,
                    time_departure=seconds_to_time(stoptime.departure_secs) if i != len(gtfs_stoptimes) else None,
                    sequence_num=stoptime.stop_sequence,
                ))


    stop_times = await sync_to_async(StopTime.objects.bulk_insert)(stop_times)

    print(f'[Marprom] Saved {len(stop_times)} stop_times')


async def marprom_old_update_routes():
    operator = await Operator.objects.aget(
        name='Javno podjetje za mestni potniški promet Marprom, d.o.o.',
    )

    iso_date = date.today().strftime("%Y-%m-%d")

    mp_stop_location_cache: dict[int, StopLocation] = {
        s.marprom_id: s
        async for s in StopLocation.objects.filter(marprom_id__isnull=False)
    }

    lines = GetLines.Root.from_dict(await api.get('GetLines', Date=iso_date)).Lines

    for line in lines:
        group, _ = await RouteGroup.objects.aget_or_create(
            marprom_id=line.LineId,
            operator_id=operator.id,
            defaults=dict(
                number=line.Code,
                color=line.Color,
                name=line.Description,
            )
        )
        print(group)

        print("deleting ", await Route.objects.filter(marprom_id__isnull=False, route_group_id=group.id).adelete())

        line_info = GetLineInfo.Root.from_dict(await api.get('GetLineInfo', LineId=line.LineId, Date=iso_date)).Routes
        # line_schedules = GetStopPointSheduleForLine.Root.from_dict(await api.get('GetStopPointSheduleForLine', LineId=line.LineId, Date=iso_date)).Schedules
        # routes = GetRoutes.Root.from_dict(await api.get('GetRoutes', IncludeShape=True, LineId=line.LineId, Date=iso_date)).Routes

        mp_route_map: dict[str, GetLineInfo.Route] = {
            f'{line.LineId}_{r.HeadsignName}': r
            for r in line_info
        }

        mp_route_cahce: dict[str, Route] = {}

        route_stop_departures: dict[str, dict[int, list]] = defaultdict(dict)
        route_stop_seq: dict[str, dict[int, int]] = defaultdict(dict)

        for mp_route_id, _route in mp_route_map.items():
            shape = MultiLineString(LineString([
                (p.Lon, p.Lat)
                for p in _route.ListOfShapeNodes
            ]))
            route, _ = await Route.objects.aget_or_create(
                operator_id=operator.id,
                marprom_id=mp_route_id,
                defaults=dict(
                    route_group=group,
                    name=_route.HeadsignName,
                    geometry=shape,
                )
            )
            mp_route_cahce[mp_route_id] = route

            stop_seq = 1
            for node in _route.ListOfShapeNodes:
                if node.StopPointID is None:
                    continue

                route_stop_seq[mp_route_id][node.StopPointID] = stop_seq
                stop_seq += 1

                # stop_point = stop_location_cache[node.StopPointID]
                for stop_point_schedule in node.Shedules:
                    for mp_route_2 in stop_point_schedule.RouteAndSchedules:
                        mp_route_id = f'{stop_point_schedule.LineId}_{mp_route_2.Direction}'
                        route_stop_departures[mp_route_id][node.StopPointID] = mp_route_2.Departures

        for mp_route_id, stop_departures in route_stop_departures.items():
            first = next(stop_departures.values().__iter__())
            count = len(first)

            for trip_num in range(count):
                trip = await Trip.objects.acreate(
                    # marprom_id=f'{mp_route_id}_{trip_num}',
                    route=mp_route_cahce[mp_route_id],
                )
                for mp_stop_id, departures in stop_departures.items():
                    try:
                        await StopTime.objects.acreate(
                            trip=trip,
                            time_departure=time.fromisoformat(departures[trip_num]),
                            time_arrival=time.fromisoformat(departures[trip_num]),
                            stop_location=mp_stop_location_cache[mp_stop_id],
                            sequence_num=route_stop_seq[mp_route_id].get(mp_stop_id, 0),
                        )
                    except:
                        logging.exception(f'Error while processing stop time {mp_stop_id} {departures[trip_num]}')


def marprom_update_stop_location_photos():
    stop_locations = StopLocation.objects\
        .filter(marprom_id__isnull=False, operator_stop_id__isnull=False)\
        .filter(Q(photo__exact="") | Q(photo__isnull=True))

    print('Getting photos for', stop_locations.count(), 'stop locations')

    for stop_location in stop_locations:
        stop_location: StopLocation

        stop_id: int = int(stop_location.operator_stop_id)
        stop_location_photo_url = f"{MARPROM_BASE}/PostajaliscaImg/s{stop_id}.jpg"
        stop_location_photo_resp = requests.get(stop_location_photo_url)
        if stop_location_photo_resp.status_code != 200:
            continue

        stop_location.photo = File(BytesIO(stop_location_photo_resp.content), name=f"marprom-stop-{stop_id}.jpg")
        stop_location.save()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    # loop.run_until_complete(marprom_update_routes())
    loop.run_until_complete(marprom_update_routes())
    # loop.run_until_complete(marprom_update_routes())
    #marprom_update_stop_location_photos()

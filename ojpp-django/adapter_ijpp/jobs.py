import csv
import io
import json
import zipfile
from typing import TYPE_CHECKING

import aiohttp
import django
import os

import httpx
import pytz
import aiohttp
from aiohttp import BasicAuth
from asgiref.sync import sync_to_async
from django.conf import settings
from psqlextra.types import ConflictAction

from ojpp_core.util import seconds_to_time
from ojpp_common.metrics import G_LOC_IJPP, G_VALIDLOC_IJPP


if TYPE_CHECKING:
    from ijpp.ijpp.b2b_ijpp_ijppservice import VozniRedExt, GetVozniRediZaPrevoznikaResponse_1, VoznjaExt, GetPostajaliscaResponse_1, GetPostajneTockeResponse_1, GetRezimiResponse_1, GetLinijskiOdseki, GetLinijskiOdsekiResponse

if __name__ == '__main__':
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")
    django.setup()

import asyncio
import requests
from datetime import datetime
from datetime import timedelta

from ijpp_lib import IJPP
from ojpp_common import util, trip_instancing
from ojpp_common.models import *
from ojpp_common.trip_instancing import process_vehicle_location


class Config:
    USERNAME = settings.IJPP_USERNAME
    PASSWORD = settings.IJPP_PASSWORD
    WSDL = 'https://b2b.nap.si/data/b2b.ijpp.ijppservice.wsdl'
    AVL_WSDL = 'https://b2b.nap.si/data/b2b.ijpp.avlservice.wsdl'


ijpp = None
async def get_ijpp():
    global ijpp
    if not ijpp:
        ijpp = IJPP()
        await ijpp.init(Config)
    return ijpp


async def ijpp_update_locations():
    ijpp = await get_ijpp()
    SLO_TZ = pytz.timezone('Europe/Ljubljana')

    locations = {}
    resp = await ijpp.get_vehicle_locations_raw()

    G_LOC_IJPP.set(len(resp))

    for loc in resp:
        if loc.monitoredVehicleJourney.vehicleLocation.Longitude is None or loc.monitoredVehicleJourney.vehicleLocation.Latitude is None:
            continue
        # Y-2038 problem
        if loc.RecordedAtTime.year == 2038:
            continue
        # Future dates???
        elif (loc.RecordedAtTime - datetime.now()).total_seconds() > 10_800:
            continue

        operator, _ = await Operator.objects.aget_or_create(
            name=loc.monitoredVehicleJourney.OperatorRef,
            ijpp_avl_id=loc.monitoredVehicleJourney.OperatorRef,
        )

        # Get or create vehicle
        try:
            vehicle = await Vehicle.objects.aget(ijpp_id=loc.monitoredVehicleJourney.VehicleRef)

            # Vehicle changed operators
            if vehicle.operator is None or vehicle.operator_id != operator.id:
                vehicle.operator_id = operator.id
                await vehicle.asave()

        except Vehicle.DoesNotExist:
            vehicle = await Vehicle.objects.acreate(
                ijpp_id=loc.monitoredVehicleJourney.VehicleRef,
                operator_id=operator.id,
            )

        # Find trip
        try:
            trip = await Trip.objects.aget(ijpp_id=loc.monitoredVehicleJourney.LineRef)
            trip_id = trip.id
        except Trip.DoesNotExist:
            trip_id = None

        locations[loc.monitoredVehicleJourney.LineRef] = dict(
            vehicle_id=vehicle.id,
            trip_id=trip_id,
            bearing=loc.monitoredVehicleJourney.Bearing,
            location=Point(
                loc.monitoredVehicleJourney.vehicleLocation.Longitude,
                loc.monitoredVehicleJourney.vehicleLocation.Latitude,
            ),
            time=SLO_TZ.localize(loc.RecordedAtTime),
        )

    print('[IJPP] Downloaded', len(resp), 'locations')

    location_list = util.deduplicate_locations(locations.values())
    G_VALIDLOC_IJPP.set(len(location_list))

    if not location_list:
        return

    real_locations = await sync_to_async(VehicleLocation.objects.on_conflict(['vehicle_id', 'time'], ConflictAction.UPDATE).bulk_insert)(list(location_list))

    for location_dict in real_locations:
        vl = VehicleLocation(**location_dict)
        try:
            await sync_to_async(process_vehicle_location)(vl)
        except:
            logging.exception(f'Exception for VehicleLocation {vl.id}')


    print('[IJPP] Saved', len(real_locations), 'locations')

    pass


async def ijpp_update_prevozniki():
    ijpp = await get_ijpp()

    prevozniki = await ijpp.call_by_dict('GetPrevozniki')
    await asyncio.sleep(.5)

    for prevoznik in prevozniki.prevozniki.Prevoznik:
        logging.info(f'Updating prevoznik {prevoznik.ime}')
        try:
            await sync_to_async(Operator.objects.on_conflict(('ijpp_avl_id',), ConflictAction.UPDATE).insert)(
                name=prevoznik.ime,
                ijpp_avl_id=prevoznik.ime,
                ijpp_id=prevoznik.idPrevoznik,
                tax_id=prevoznik.davcnaStevilka,
                website=prevoznik.URL,
            )
        except:
            logging.exception(f'Exception for Prevoznik {prevoznik.idPrevoznik} {prevoznik.ime}')


async def ijpp_update_vozni_redi(only_active_operators=True):
    operators_qs = Operator.objects.filter(ijpp_id__isnull=False)
    if only_active_operators:
        operators_qs = operators_qs.filter(active=True)
    async for operator in operators_qs:
        try:
            logging.info(f'Updating vozni redi for {operator.name}')
            vozni_redi = await update_vozni_redi_prevoznik(ijpp_id=operator.ijpp_id, operator_id=operator.id)

            if vozni_redi.iResultCode != 0:
                logging.warning(f'Error {vozni_redi.iResultCode}: {vozni_redi.sResultDescription} for Prevoznik {operator}')
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(5)

        except:
            logging.exception(f'Exception for {operator} ({operator.ijpp_id}')


_loc_map_cache = None
async def get_loc_map():
    global _loc_map_cache
    if _loc_map_cache:
        return _loc_map_cache
    loc_map = {}
    async for loc in StopLocation.objects.only('ijpp_id', 'id').filter(ijpp_id__isnull=False):
        loc_map[loc.ijpp_id] = loc.id
    _loc_map_cache = loc_map
    return loc_map

_loc_locations_cache = None
async def get_loc_locations():
    global _loc_locations_cache
    if _loc_locations_cache:
        return _loc_locations_cache
    loc_map = {}
    async for loc in StopLocation.objects.only('ijpp_id', 'location').filter(ijpp_id__isnull=False):
        loc_map[loc.ijpp_id] = loc.location
    _loc_locations_cache = loc_map
    return loc_map

async def update_vozni_redi_prevoznik(ijpp_id, operator_id):
    ijpp = await get_ijpp()
    loc_map = await get_loc_map()

    print('Downloading...', end="")

    vozni_redi: GetVozniRediZaPrevoznikaResponse_1 = await ijpp.call_by_dict('GetVozniRediZaPrevoznika', dict(
        idPrevoznik=ijpp_id,
        isExtStructure=True,
    ))
# with open('/tmp/cache.pickle', 'rb') as f:
#     import pickle
#     vozni_redi = pickle.load(f)

    print('DONE')

    schedules_by_ijpp_id = {
        schedule.ijpp_id: schedule
        async for schedule in Schedule.objects.filter(ijpp_id__isnull=False).only('id', 'ijpp_id')
    }

    # TODO: this should be a transaction, but transaction.atomic() doesn't work in async

    # Mark all as inactive
    await StopTime.objects.filter(trip__route__operator_id=operator_id).aupdate(active=False)
    await Trip.objects.filter(route__operator_id=operator_id).aupdate(active=False)
    await Route.objects.filter(operator_id=operator_id).aupdate(active=False)

    # Import new (will be set to active)

    routes = []
    for vozni_red in vozni_redi.vozniRedi.VozniRed:
        # Route
        vozni_red: VozniRedExt
        route = dict(
            active=True,
            ijpp_id=vozni_red.idVozniRed,
            name_via=vozni_red.postajalisceVia,
            operator_id=operator_id,
            route_type=vozni_red.idTipPrevoza,
            nvr_number=vozni_red.stevilka,
            nvr_version=vozni_red.verzija,
            nvr_name=f'{vozni_red.stevilka} {vozni_red.verzija}',
            note=vozni_red.opomba,
        )
        routes.append(route)
    if not routes:
        return vozni_redi
    print(f"Sending {len(routes)} routes to db...", end="")
    routes = await sync_to_async(Route.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(routes)
    print("DONE")

    trips = []
    for vozni_red, route in zip(vozni_redi.vozniRedi.VozniRed, routes):
        # Route
        for voznja in vozni_red.voznje.VoznjaExt:
            # Trip
            trip = dict(
                active=True,
                ijpp_id=voznja.idVoznja,
                route_id=route['id'],
                schedule=schedules_by_ijpp_id.get(voznja.idRezim, None),
                headsign=voznja.oznakaPoti,
            )
            trips.append(trip)

    if not trips:
        return vozni_redi
    print(f"Sending {len(trips)} trips to db...", end="")
    trips = await sync_to_async(Trip.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(trips)
    print("DONE")

    stoptimes = []
    i = 0
    for vozni_red, route in zip(vozni_redi.vozniRedi.VozniRed, routes):
        # Route
        for voznja in vozni_red.voznje.VoznjaExt:
            trip = trips[i]
            i += 1
            rezim = voznja.idRezim
            # Trip
            counter = 1
            for opis in voznja.voznjeOpisi.VoznjaOpisExt:
                stop_loc_id = loc_map.get(opis.idPostajnaTocka)
                if stop_loc_id is None:
                    # TODO: what if the stoplocation is not in the db?
                    stop_loc_id = (await StopLocation.objects.acreate(ijpp_id=opis.idPostajnaTocka, name=opis.imePostajneTocke)).id
                    loc_map[opis.idPostajnaTocka] = stop_loc_id
                if not opis.postanek:
                    continue
                stoptime = dict(
                    active=True,
                    time_arrival=seconds_to_time(opis.casPrihoda) if opis.casPrihoda else None,
                    time_departure=seconds_to_time(opis.casOdhoda) if opis.casOdhoda else None,
                    #route_id=route['id'],
                    trip_id=trip['id'],
                    ijpp_id=opis.idVoznjaOpis,
                    stop_location_id=stop_loc_id,
                    sequence_num=counter
                )
                counter += 1
                stoptimes.append(stoptime)

    if not stoptimes:
        return vozni_redi
    print(f"Sending {len(stoptimes)} stoptimes to db...", end="")
    stoptimes = await sync_to_async(StopTime.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(stoptimes)
    print("DONE")

    return vozni_redi


async def ijpp_update_stops(**kwargs):
    ijpp = await get_ijpp()

    postaje: GetPostajaliscaResponse_1 = await ijpp.call_by_dict('GetPostajalisca')

    stops = []
    for postaja in postaje.postajalisca.Postajalisce:
        stop = dict(
            ijpp_id=postaja.idPostajalisce,
            name=postaja.ime,
            location=Point(postaja.geometrija.X, postaja.geometrija.Y),
        )
        stops.append(stop)
    stops = await sync_to_async(Stop.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(stops)

    stop_map = {stop['ijpp_id']: stop for stop in stops}

    postajne_tocke: GetPostajneTockeResponse_1 = await ijpp.call_by_dict('GetPostajneTocke')

    stop_locations = []
    for postaja in postajne_tocke.postajneTocke.PostajnaTocka:
        try:
            stop_location = dict(
                stop_id=stop_map[postaja.idPostajalisce]['id'],
                ijpp_id=postaja.idPostajnaTocka,
                location=Point(postaja.geometrija.X, postaja.geometrija.Y),

            )
            stop_locations.append(stop_location)
        except:
            logging.exception(f'Error at PostajnaTocka {postaja.idPostajalisce}')
    if not stop_locations:
        return
    stop_locations = await sync_to_async(StopLocation.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(stop_locations)

    pass


async def update_rezimi():
    ijpp = await get_ijpp()
    rezimi: GetRezimiResponse_1 = await ijpp.call_by_dict('GetRezimi')

    action_map = {
        0: False,
        1: True,
        None: True,
    }

    schedules = []
    for rezim in rezimi.rezimi.Rezim:
        schedule = dict(
            ijpp_id=rezim.idRezim,
            description=rezim.opis,
            ijpp_tag=rezim.oznaka,
            default_state=action_map[rezim.privzetiDelovniVektor],
        )
        schedules.append(schedule)

    schedules = await sync_to_async(Schedule.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(schedules)

    timetable_periods = []

    for i, rezim in enumerate(rezimi.rezimi.Rezim):
        schedule = schedules[i]
        for rezim_interval in rezim.interval.RezimInterval if rezim.interval else []:
            timetable_period = dict(
                action=action_map[rezim_interval.akcija],
                schedule_id=schedule['id'],
                ijpp_id=rezim_interval.idRezimInterval,
                day_from=rezim_interval.danOd,
                day_to=rezim_interval.danDo,
                month_from=rezim_interval.mesecOd,
                month_to=rezim_interval.mesecDo,
                monday=rezim_interval.ponedeljek,
                tuesday=rezim_interval.torek,
                wednesday=rezim_interval.sreda,
                thursday=rezim_interval.cetrtek,
                friday=rezim_interval.petek,
                saturday=rezim_interval.sobota,
                sunday=rezim_interval.nedelja,
                holidays=rezim_interval.praznik,
            )
            timetable_periods.append(timetable_period)

    timetable_periods = await sync_to_async(TimetablePeriod.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(timetable_periods)

    timetable_exceptions = []
    for i, rezim in enumerate(rezimi.rezimi.Rezim):
        schedule = schedules[i]
        for rezim_termin in rezim.termini.RezimTermin if rezim.termini else []:
            exception = dict(
                schedule_id=schedule['id'],
                ijpp_id=rezim_termin.idRezimTermin,
                date=rezim_termin.termin,
                action=action_map[rezim_termin.akcija],
            )
            timetable_exceptions.append(exception)

    timetable_exceptions = await sync_to_async(TimetableException.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(timetable_exceptions)

    return rezimi


async def get_polylines():
    """Download polylines from IJPP SVC and update the database."""

    # Purely for the first run - set all the trip geometries to non-final
    odseki_count = await sync_to_async(RouteSegment.objects.filter(ijpp_id__isnull=False).count)()
    if odseki_count == 0:
        await sync_to_async(Trip.objects.filter(ijpp_id__isnull=False).update)(geometry_is_final=False)

    print('Downloading polyline indexes from IJPP SVC...', end="")
    ijpp = await get_ijpp()

    loc_map = await get_loc_map()

    loc_locations = await get_loc_locations()

    active_map = {
        4: True,
        13: False,
    }

    linijski_odseki: GetLinijskiOdsekiResponse = await ijpp.call_by_dict('GetLinijskiOdseki')
    print(f'DONE ({len(linijski_odseki.linijskiOdseki.LinijskiOdsek)} segments)')
    print('Setting inactive for all that are not in IJPP SVC...', end="")

    # Get all ijpp_ids of our routesegments from the database
    existing_ijpp_ids = await sync_to_async(list)(RouteSegment.objects.values_list('ijpp_id', flat=True))
    
    # Extract ids from response
    response_ids = [odsek.idLinijskiOdsek for odsek in linijski_odseki.linijskiOdseki.LinijskiOdsek]

    # Set inactive where not in new IJPP SVC ids
    ids_to_deactivate = set(existing_ijpp_ids) - set(response_ids)
    if ids_to_deactivate:
        await sync_to_async(RouteSegment.objects.filter(ijpp_id__in=ids_to_deactivate).update)(active=False)
    
    print('DONE')
    print(f'Downloading missing odseki from IJPP SVC ({len(set(response_ids) - set(existing_ijpp_ids))})...', end="")

    # Get IDs that need to be added
    ids_to_add = set(response_ids) - set(existing_ijpp_ids)

    if ids_to_add:
        # Split into batches of 500
        ids_to_add = list(ids_to_add)
        predhodniki = []
        # TODO: look into why we can't fetch more than 1 odsek at a time
        for i in range(0, len(ids_to_add), 1):
            print(f'Batch {i} of {len(ids_to_add)}...', end="")
            to_upsert = []
            batch = ids_to_add[i:i + 1]
            lacking_odseki: GetLinijskiOdsekiResponse = await ijpp.call_by_dict('GetLinijskiOdseki', {'idLinijskiOdseki':  list(batch)}) # I don't know why it doesn't consume the list
            print('Received', len(lacking_odseki.linijskiOdseki.LinijskiOdsek), 'odseki...', end="")
            for odsek in lacking_odseki.linijskiOdseki.LinijskiOdsek:
                predhodniki.append(odsek.idPredhodnik if odsek.idStatus == 4 else None)
                ijpp_geometry = {
                    'type': 'LineString',
                    'coordinates': [[geo.X, geo.Y] for geo in odsek.geometrija.Geometrija]
                }
                osm_geometry = None
                if len(ijpp_geometry['coordinates']) < 2:
                    print(f'Invalid geometry for odsek {odsek.idLinijskiOdsek}, fetching OSM geometry...')
                    # Get OSM geometry between the two stops
                    coordinates = f'{loc_locations[odsek.idPostajnaTockaOd].x},{loc_locations[odsek.idPostajnaTockaOd].y};{loc_locations[odsek.idPostajnaTockaDo].x},{loc_locations[odsek.idPostajnaTockaDo].y}'
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f'https://router.project-osrm.org/route/v1/driving/{coordinates}?overview=full&geometries=geojson') as resp:
                            resp.raise_for_status()
                            osm_geometry = await resp.json()
                            osm_geometry = osm_geometry['routes'][0]['geometry']
                try:
                    odsek = dict(
                        ijpp_id=odsek.idLinijskiOdsek,
                        start_stop_id=loc_map[odsek.idPostajnaTockaOd],
                        end_stop_id=loc_map[odsek.idPostajnaTockaDo],
                        # DurationField
                        time=timedelta(minutes=odsek.casVoznje if odsek.casVoznje else 0),
                        length=odsek.dolzina,
                        active=active_map[odsek.idStatus],
                        ijpp_geometry=(LineString(ijpp_geometry['coordinates']) if len(ijpp_geometry['coordinates']) > 2 else None),
                        osm_geometry=(LineString(osm_geometry['coordinates']) if osm_geometry else None),
                    )
                    to_upsert.append(odsek)
                except:
                    logging.exception(f'Error at odsek {odsek.idLinijskiOdsek} ({odsek.idPostajnaTockaOd} -> {odsek.idPostajnaTockaDo})')
            await sync_to_async(RouteSegment.objects.on_conflict(['ijpp_id'], ConflictAction.UPDATE).bulk_insert)(to_upsert)

        # Update predhodniki
        # Remove None values
        predhodniki = [p for p in predhodniki if p is not None]
        # Set all to inactive
        await sync_to_async(RouteSegment.objects.filter(ijpp_id__in=predhodniki).update)(active=False)
    else:
        # Check if any of the existing segments have been updated in IJPP SVC
        for odsek in linijski_odseki.linijskiOdseki.LinijskiOdsek:
            rs = await RouteSegment.objects.aget(ijpp_id=odsek.idLinijskiOdsek)
            if rs.active != active_map[odsek.idStatus]:
                rs.active = active_map[odsek.idStatus]
                await rs.asave()

    # Wait for all the updates to finish
    print('DONE')

    
    # Update all the geometries
    # Get all active trips

    trips = await sync_to_async(list)(Trip.objects.filter(active=True, ijpp_id__isnull=False))
    for trip in trips:
        try:
            if trip.geometry_is_final:
                continue
            await calculate_geometry_for_trip(trip)
        except Exception as e:
            logging.exception(f'Error at trip {trip.id}, {e}')

    print('DONE')

async def calculate_geometry_for_trip(trip: Trip):
    print(f'Processing trip {trip.id}')

    # Asynchronously get all stoptimes for the trip
    stoptimes = await sync_to_async(list)(StopTime.objects.filter(trip=trip).order_by('sequence_num').select_related('stop_location', 'stop_location__stop'))

    # Prepare for fetching route segments
    stop_pairs = [(stoptimes[i-1].stop_location, stoptimes[i].stop_location) for i in range(1, len(stoptimes))]
    stops_ids = [stop.id for pair in stop_pairs for stop in pair]

    # Define a function to execute the route segment fetch
    def fetch_route_segments():
        return {
            (rs.start_stop_id, rs.end_stop_id): rs
            for rs in RouteSegment.objects.filter(
                start_stop_id__in=stops_ids,
                end_stop_id__in=stops_ids,
                active=True
            )
        }

    # Fetch route segments using the defined function wrapped by sync_to_async
    route_segments = await sync_to_async(fetch_route_segments)()

    polyline = []
    async with aiohttp.ClientSession() as session:
        for start_stop, end_stop in stop_pairs:
            rs = route_segments.get((start_stop.id, end_stop.id))
            if not rs:
                polyline.extend(await fetch_osm_geometry(start_stop, end_stop, session))
                continue
            
            if rs.osm_geometry:
                polyline.extend(rs.osm_geometry.coords)
            elif rs.ijpp_geometry:
                polyline.extend(rs.ijpp_geometry.coords)
            else:
                print(f'No geometry for route segment {rs.id}')
                polyline.extend(await fetch_osm_geometry(start_stop, end_stop, session))

    if polyline:
        trip.geometry = LineString(polyline)
        trip.geometry_is_final = True
        await sync_to_async(trip.save)()

async def fetch_osm_geometry(start_stop, end_stop, session):
    coordinates = f'{start_stop.location.x},{start_stop.location.y};{end_stop.location.x},{end_stop.location.y}'
    url = f'https://router.project-osrm.org/route/v1/driving/{coordinates}?overview=full&geometries=geojson'
    async with session.get(url) as response:
        response.raise_for_status()
        osm_geometry = await response.json()
        return LineString(osm_geometry['routes'][0]['geometry']['coordinates']).coords


def proski_test():
    # get all trips from ijpp
    ijpp_trips = Trip.objects.filter(ijpp_id__isnull=False).values_list('ijpp_id', flat=True)
    dict = {}
    for trip in ijpp_trips:
        # get all associated stoptimes
        stoptimes = StopTime.objects.filter(trip__ijpp_id=trip).order_by('sequence_num')
        concated_string = ""
        for stoptime in stoptimes:
            concated_string += f"{stoptime.stop_location.ijpp_id},{stoptime.time_arrival.strftime('%H:%M:%S') if stoptime.time_arrival is not None and stoptime.sequence_num != 1 else 'None'},{stoptime.time_departure.strftime('%H:%M:%S') if stoptime.time_departure is not None else 'None'};"

        dict[str(trip)] = concated_string
        print('Done', trip)
        c = 0

    # write out to file
    with open('ijpp_stoptimes.json', 'w') as f:
        json.dump(dict, f)


def proski_test_2():
    import transitfeed
    schedule = transitfeed.Schedule()
    schedule.Load('b2b.gtfs.zip')
    trips = schedule.GetTripList()
    dict = {}
    for trip in trips:
        concated_string = ""
        for stoptime in trip.GetStopTimes():
            concated_string += f"{stoptime.stop.stop_id},{stoptime.arrival_time},{stoptime.departure_time};"

        dict[str(trip.trip_id)] = concated_string
        print('Done', trip.trip_id)
        c = 0

    # write out to file
    with open('gtfs_stoptimes.json', 'w') as f:
        json.dump(dict, f)


async def ijpp_update_nvr_names():
    async with aiohttp.request('GET', 'https://b2b.nap.si/data/b2b.gtfs', auth=BasicAuth(settings.IJPP_USERNAME, settings.IJPP_PASSWORD)) as resp:
        resp.raise_for_status()
        data = await resp.read()

    print('Done downloading GTFS file')

    with zipfile.ZipFile(io.BytesIO(data)) as zip_file:
        with zip_file.open('routes.txt') as f:
            routes = csv.DictReader(io.TextIOWrapper(f))
            gtfs_routes = {r['route_id']: r['route_long_name'] for r in routes}

        with zip_file.open('trips.txt') as f:
            trips = csv.DictReader(io.TextIOWrapper(f))
            gtfs_trips = {t['trip_id']: t['route_id'] for t in trips}

    print('Done parsing GTFS file')

    our_trips = Trip.objects.filter(ijpp_id__isnull=False, route__nvr_name__isnull=True).select_related('route')

    to_update = []
    async for trip in our_trips:
        gtfs_route = gtfs_routes.get(gtfs_trips.get(str(trip.ijpp_id)))
        if gtfs_route:
            trip.route.nvr_name = gtfs_route
            to_update.append(trip.route)
        else:
            print(f'No GTFS route found for {trip.ijpp_id}')

    await Route.objects.abulk_update(to_update, ['nvr_name'])

    print('Done updating NVR names')


if __name__ == '__main__':
    trip_instancing.logger.setLevel(logging.DEBUG)
    loop = asyncio.get_event_loop()
    # get_polylines()
    # loop = asyncio.get_event_loop()
    #proski_test()
    #proski_test_2()
    # loop.run_until_complete(update_vozni_redi_prevoznik(ijpp_id=1130, operator_id=4))  # MPOV
    loop.run_until_complete(update_vozni_redi_prevoznik(ijpp_id=1121, operator_id=6))  # AP MS
    # loop.run_until_complete(ijpp_update_prevozniki())
    # loop.run_until_complete(update_rezimi())
    # loop.run_until_complete(ijpp_update_locations())

import asyncio
import os
from datetime import datetime
from typing import Optional, Type

import django
import pytz
from asgiref.sync import sync_to_async
from async_lru import alru_cache
from django.db.models import Model
from psqlextra.types import ConflictAction

from adapter_nap.ijpp_mapping import realis_to_ijpp
from adapter_nap.nap_siri import get_vehicle_activity

if __name__ == '__main__':
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")
    django.setup()

from ojpp_common.models import *
from ojpp_common.trip_instancing import process_vehicle_location
from ojpp_common.util import deduplicate_locations


async def get_or_remap_realis(Type: Type[Model], nap_id: str) -> Optional[int]:
    ijpp_id, _ = realis_to_ijpp(nap_id)
    try:
        return await Type.objects.aget(ijpp_id=ijpp_id)
    except Type.DoesNotExist:
        return None

    # TODO: automatic IJPP-NAP mapping
    # try:
    #     obj = await Type.objects.aget(nap_id=nap_id)
    # except Type.DoesNotExist:
    #     ijpp_id, _ = realis_to_ijpp(nap_id)
    #     try:
    #         obj = await Type.objects.aget(ijpp_id=ijpp_id)
    #     except Type.DoesNotExist:
    #         obj = await Type.objects.acreate(nap_id=nap_id, ijpp_id=ijpp_id)
    #     obj.nap_id = nap_id
    #     await obj.asave()
    # return obj.id

@alru_cache
async def lookup_trip(nap_id: str) -> Optional[Trip]:
    return await get_or_remap_realis(Trip, nap_id)

@alru_cache
async def lookup_operator(nap_id: str) -> Optional[Operator]:
    op = await get_or_remap_realis(Operator, nap_id)
    if op is None:
        ijpp_id, _ = realis_to_ijpp(nap_id)
        return Operator.objects.acreate(nap_id=nap_id, ijpp_id=ijpp_id)
    return op


async def nap_update_locations():
    SLO_TZ = pytz.timezone('Europe/Ljubljana')

    locations = {}
    resp = await get_vehicle_activity()

    null_operators = 0

    for loc in resp:
        if loc.monitoredVehicleJourney.vehicleLocation.longitude is None or loc.monitoredVehicleJourney.vehicleLocation.latitude is None:
            continue
        # Y-2038 problem
        if loc.recordedAtTime.year == 2038:
            continue
        # Future dates???
        elif (loc.recordedAtTime.to_datetime() - datetime.now()).total_seconds() > 10_800:
            continue
        # "todo" ?????
        elif loc.monitoredVehicleJourney.operatorRef == 'todo':
            continue
        elif loc.monitoredVehicleJourney.operatorRef is None:
            null_operators += 1
            continue

        operator = await lookup_operator(loc.monitoredVehicleJourney.operatorRef)

        # Get or create vehicle
        try:
            vehicle = await Vehicle.objects.aget(ijpp_id=loc.monitoredVehicleJourney.vehicleRef)
        except Vehicle.DoesNotExist:
            vehicle = await Vehicle.objects.acreate(
                ijpp_id=loc.monitoredVehicleJourney.vehicleRef,
                operator=operator,
            )
        # Vehicle changed operators
        if vehicle.operator != operator and operator is not None:
            print(f'[NAP SIRI] Vehicle {vehicle.id} changed operators from {vehicle.operator} to {operator}')
            vehicle.operator = operator
            await vehicle.asave()

        # Find trip
        trip = await lookup_trip(loc.monitoredVehicleJourney.vehicleJourneyRef)

        locations[loc.monitoredVehicleJourney.vehicleJourneyRef] = dict(
            vehicle_id=vehicle.id,
            trip_id=trip.id if trip else None,
            bearing=loc.monitoredVehicleJourney.bearing,
            location=Point(
                float(loc.monitoredVehicleJourney.vehicleLocation.longitude),
                float(loc.monitoredVehicleJourney.vehicleLocation.latitude),
            ),
            time=SLO_TZ.localize(loc.recordedAtTime.to_datetime())
        )

    print('[NAP SIRI] Downloaded', len(resp), 'locations')
    print('[NAP SIRI] Null operators:', null_operators)

    location_list = deduplicate_locations(locations.values())

    if not location_list:
        return

    real_locations = await sync_to_async(VehicleLocation.objects.on_conflict(['vehicle_id', 'time'], ConflictAction.UPDATE).bulk_insert)(list(location_list))

    for location_dict in real_locations:
        vl = VehicleLocation(**location_dict)
        try:
            await sync_to_async(process_vehicle_location)(vl)
        except:
            logging.exception(f'Exception for vehicleLocation {vl.id}')


    print('[NAP SIRI] Saved', len(real_locations), 'locations')

    pass

if __name__ == '__main__':
    async def main():
        await nap_update_locations()
        await asyncio.sleep(10)
        await nap_update_locations()

    asyncio.run(main())

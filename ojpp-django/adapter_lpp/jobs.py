from io import BytesIO
from typing import TYPE_CHECKING

import django
import os

if __name__ == '__main__':
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")
    django.setup()

import httpx
import requests
from asgiref.sync import sync_to_async
from dateutil.parser import isoparse
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.files import File
from galleryfield.models import BuiltInGalleryImage
from psqlextra.types import ConflictAction

if TYPE_CHECKING:
    from ijpp.ijpp.b2b_ijpp_ijppservice import VozniRedExt, GetVozniRediIndexZaPrevoznikaResponse, GetVozniRediZaPrevoznikaResponse_1, VoznjaExt, GetPostajaliscaResponse_1, GetPostajneTockeResponse_1


import asyncio
import logging
from datetime import datetime, time, timedelta

from ojpp_common.models import *


async def lpp_request(path, params=None):
    resp = requests.get(f'https://lpp.ojpp.derp.si/api/{path}', params=params)
    resp.raise_for_status()
    return resp.json()


def guess_trip_id(bus):
    return None


async def lpp_update_locations():
    operator, _ = await Operator.objects.aget_or_create(
        name='Javno podjetje Ljubljanski potniški promet d.o.o.'
    )

    buses = await lpp_request('bus/bus-details?trip-info=1')

    locations = []
    for bus in buses['data']:
        # TODO: skip inactive buses
        vehicle, _ = await Vehicle.objects.aget_or_create(
            lpp_id=bus['bus_unit_id'],
            defaults=dict(
                operator=operator,
                plate=bus['name'],
                vin=bus['vin'],
            )
        )
        #trip, _ = await Trip.objects.aget_or_create(
        #    lpp_id=bus['trip_id'],
        #    operator=operator,
        #)
        locations.append(dict(
            vehicle_id=vehicle.id,
            trip_id=guess_trip_id(bus),
            bearing=bus['cardinal_direction'],
            location=Point(
                bus['coordinate_x'],
                bus['coordinate_y'],
            ),
            time=isoparse(bus['timestamp']),
        ))
    await sync_to_async(VehicleLocation.objects.on_conflict(['vehicle_id', 'time'], ConflictAction.UPDATE).bulk_insert)(locations)

    pass


async def update_routes():
    operator, _ = await Operator.objects.aget_or_create(
        name='Javno podjetje Ljubljanski potniški promet d.o.o.'
    )

    routes = await lpp_request('route/routes?shape=1')
    for lpp_route in routes['data']:
        # Sample:
        # "route_id": "A48D5D5E-1A10-4616-86BE-65B059E0A371",
        # "trip_id": "0210087E-3092-4B0D-8D37-8983095C7808",
        # "route_number": "3G",
        # "route_name": "BEŽIGRAD - GROSUPLJE",
        # "short_route_name": "GROSUPLJE",
        # "trip_int_id": 3613
        route_group, _ = RouteGroup.aget_or_create(
            operator=operator,
            number=lpp_route['route_number'],
        )

        route, _ = await Route.objects.aget_or_create(
            lpp_id=lpp_route['route_id'],
            defaults=dict(
                name=lpp_route['route_name'],
                route_group=route_group,
            )
        )




async def update_stops():
    postaje = await lpp_request('/station/station-details')

    stop_locations = []
    for postaja in postaje['data']:
        stop_location = dict(
            lpp_id=postaja['ref_id'],
            name=postaja['Name'],
            location=Point(postaja['longitude'], postaja['latitude']),
        )

        stop_locations.append(stop_location)
    stop_locations = await sync_to_async(StopLocation.objects.on_conflict(['lpp_id'], ConflictAction.UPDATE).bulk_insert)(stop_locations)

    stop_location_map = {stop_location['lpp_id']: stop_location for stop_location in stop_locations}

    pass


async def lpp_update_mestnipromet():
    operator, _ = await Operator.objects.aget_or_create(
        name='Javno podjetje Ljubljanski potniški promet d.o.o.'
    )
    data = { d.get('no'): d for d in requests.get('https://mestnipromet.cyou/tracker/js/json/images.json').json() }

    async for vehicle in operator.vehicles.all():
        num = (vehicle.plate or '').split('-')[-1]
        if num not in data:
            continue
        mp = data[num]
        if not vehicle.photos and mp.get('hasImage'):
            resp = requests.get(f'https://mestnipromet.cyou/tracker/img/avtobusi/{num}.jpg')
            img = await BuiltInGalleryImage.objects.acreate(
                creator_id=1,
                image=File(BytesIO(resp.content), name=num + '.jpg')
            )
            vehicle.photos.append(img.id)
        if not await sync_to_async(lambda: vehicle.model)():
            model, _ = await VehicleModel.objects.aget_or_create(name=mp['model'])
            vehicle.model = model
        await sync_to_async(vehicle.save)()



if __name__ == '__main__':
    lpp_update_mestnipromet()
    loop = asyncio.get_event_loop()
    #update_plates()
    loop.run_until_complete(lpp_update_locations())
    #loop.run_until_complete(update_stops())
    #loop.run_until_complete(update_vozni_redit_prevoznik(1121, 6))

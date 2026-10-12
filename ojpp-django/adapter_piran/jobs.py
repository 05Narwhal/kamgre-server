import logging

import django
import os

import pytz
from asgiref.sync import sync_to_async
from dateutil.parser import isoparse
from django.conf import settings
from psqlextra.types import ConflictAction

from ojpp_common.util import interpolate_bearing, deduplicate_locations
from slo_scrap.slo_scrap_lib.sites.margento import arriva as arriva_piran

if __name__ == '__main__':
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")
    django.setup()

import asyncio

from ojpp_common.models import *


class ArrivaPiranClient(arriva_piran.ArrivaClient):
    DATA_DIR = settings.DATA_DIR / 'arriva_piran'


api = ArrivaPiranClient()


async def piran_update_locations():
    CET = pytz.timezone("CET")

    await api.init()

    resp = await api.get_buses()

    operator = await Operator.objects.aget(
        name='Arriva d.o.o.',
    )

    SLO_TZ = pytz.timezone('Europe/Ljubljana')

    locations = {}
    for loc in resp['busses']:
        try:
            code = int(loc['name'].split(' ')[-1])
        except:
            continue
        vehicle, _ = await Vehicle.objects.aget_or_create(
            operator_vehicle_id=code,
            operator=operator,
        )

        try:
            trip, _ = await Trip.objects.aget_or_create(piran_id=int(loc['trip_info']))
            trip_id = trip.id
        except:
            logging.exception('Failed to get trip')
            trip_id = None

        locations[code] = dict(
            vehicle_id=vehicle.id,
            trip_id=trip_id,
            location=Point(
                loc['lon'],
                loc['lat'],
            ),
            time=SLO_TZ.localize(isoparse(loc['timestamp'])),
            bearing=None,
        )

    locations = await interpolate_bearing(locations.values(), operator)
    locations = deduplicate_locations(locations)

    if locations:
        await sync_to_async(VehicleLocation.objects.on_conflict(['vehicle_id', 'time'], ConflictAction.UPDATE).bulk_insert)(locations)

    print('[Piran] Saved', len(locations), 'locations')


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(piran_update_locations())

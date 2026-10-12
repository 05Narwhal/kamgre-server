import asyncio
import os

import django

if __name__ == '__main__':
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")
    django.setup()

from adapter_ijpp.jobs import get_ijpp
from adapter_nap.ijpp_mapping import realis_to_ijpp
from adapter_nap.nap_siri import get_vehicle_activity


async def main():
    ijpp = await get_ijpp()

    ijpp_data = await ijpp.get_vehicle_locations_raw()
    nap_data = await get_vehicle_activity()

    print('[IJPP] Vehicle Count:', len(ijpp_data))
    print('[NAP] Vehicle Count:', len(nap_data))

    ijpp_ids_notnull = [x.monitoredVehicleJourney.VehicleRef for x in ijpp_data if x.monitoredVehicleJourney.VehicleRef]
    nap_ids_notnull = [x.monitoredVehicleJourney.vehicleRef for x in nap_data if x.monitoredVehicleJourney.vehicleRef]

    print('[IJPP] Vehicle NULL:', len(ijpp_data) - len(ijpp_ids_notnull))
    print('[NAP] Vehicle NULL:', len(nap_data) - len(nap_ids_notnull))

    ijpp_ids = set(ijpp_ids_notnull)
    nap_ids = set(nap_ids_notnull)

    print('[IJPP] Vehicle Unique:', len(ijpp_ids))
    print('[NAP] Vehicle Unique:', len(nap_ids))

    ijpp_operator_ids = [x.monitoredVehicleJourney.OperatorRef for x in ijpp_data if x.monitoredVehicleJourney.OperatorRef]
    nap_operator_ids = [x.monitoredVehicleJourney.operatorRef for x in nap_data if x.monitoredVehicleJourney.operatorRef]

    print('[IJPP] Operator Unique:', len(set(ijpp_operator_ids)))
    print('[NAP] Operator Unique:', len(set(nap_operator_ids)))

    ijpp_operators_null = len([x for x in ijpp_data if x.monitoredVehicleJourney.OperatorRef is None])
    nap_operators_null = len([x for x in nap_data if x.monitoredVehicleJourney.operatorRef is None])

    print('[IJPP] Operator NULL:', ijpp_operators_null)
    print('[NAP] Operator NULL:', nap_operators_null)

    nap_unmapped = []
    nap_mapped = []
    for nap_id in nap_ids:
        try:
            ijpp_id, _ = realis_to_ijpp(nap_id)
            nap_mapped.append(ijpp_id)
        except ValueError:
            nap_unmapped.append(nap_id)

    print('[NAP] Mapped:', len(nap_mapped))

    matching_mapped = 0
    for nap_id in nap_mapped:
        if nap_id in ijpp_ids:
            matching_mapped += 1

    print('[NAP] Mapped present in IJPP:', matching_mapped)




if __name__ == '__main__':
    asyncio.run(main())
import logging

import requests
from tqdm import tqdm

from ojpp_common.models import Vehicle, Operator

MATCHER_URL = 'https://pastebin.com/raw/eLzxLSMW'


def arriva_update_matcher_data():
    arriva, _ = Operator.objects.get_or_create(name='Arriva d.o.o.')

    resp = requests.get(MATCHER_URL).json()

    for arriva_bus in tqdm(resp):
        try:
            ijpp_id = arriva_bus['vehicleRef']
            arriva_id = arriva_bus['vehicleId']
            plate = arriva_bus['vehicleRegistration']

            bus, created = Vehicle.objects.update_or_create(
                ijpp_id=ijpp_id,
                defaults=dict(
                    ijpp_id=ijpp_id,
                    operator=arriva,
                    operator_vehicle_id=arriva_id,
                    plate=plate,
                )
            )
        except:
            logging.exception('Exception at ' + str(arriva_bus))


if __name__ == '__main__':
    arriva_update_matcher_data()

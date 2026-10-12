import csv
import json
import os
import traceback
from io import BytesIO

import requests as _requests
import dataset
from tqdm import tqdm

operator_name = 'Javno podjetje za mestni potniški promet Marprom, d.o.o.'

TOKEN = os.environ.get('API_TOKEN')
CATCH = Exception
BASE = 'http://dev.vlak.si/api/'

if False:
    CATCH = ZeroDivisionError
    TOKEN = 'a603f28f830a6c62f10d009a760002dc4a7f8169'
    BASE = 'http://127.0.0.1:8000/api/'

requests = _requests.session()
requests.headers = {
    'Authorization': 'Token ' + TOKEN
}

requests.hooks = {
   'response': lambda r, *args, **kwargs: r.raise_for_status()
}

db = dataset.connect('sqlite:///:memory:')
operators = db['operators']
models = db['models']
vehicles = db['vehicles']

for operator in requests.get(BASE + 'operators/').json():
    operators.insert(operator)

operator_id = operators.find_one(name=operator_name)['id']

for model in requests.get(BASE + 'vehicle-models/').json():
    models.insert(model)

for vehicle in requests.get(BASE + 'vehicles/?operator=' + str(operator_id)).json():
    vehicle['photos'] = json.dumps(vehicle['photos'])
    vehicles.insert(vehicle)


def download_image(image_url):
    headers = {}
    if 'photobucket' in image_url:
        # download from photobucket
        headers['Referer'] = image_url
    resp = requests.get(image_url, headers=headers)
    name = resp.headers.get('content-disposition', '').split('filename=', maxsplit=1)[-1].strip('"')
    name = name.replace('_thumb', '')  # Workaround for SMF filename .jpg_thumb
    if not name:
        name = image_url.rsplit('/', maxsplit=1)[-1]
    return name, resp.content


with open('marprom.csv', 'r') as f:
    reader = csv.DictReader(f)

    for row in tqdm(list(reader)):
        try:
            model = models.find_one(name=row['model_name'])
            if not model and row['model_name']:
                model = requests.post(BASE + 'vehicle-models/', data={'name': row['model_name']}).json()
                models.insert(model)

            vehicle = vehicles.find_one(operator_vehicle_id=row['operator_vehicle_id']) or vehicles.find_one(plate=row['plate'])
            if not vehicle:
                vehicle = requests.post(BASE + 'vehicles/', json={
                    'plate': row['plate'] or None,
                    'operator_vehicle_id': row['operator_vehicle_id'],
                    'model': f"{BASE}vehicle-models/{model['id']}/" if model else None,
                    'operator': f"{BASE}operators/{operator_id}/",
                }).json()
                vehicle['photos'] = json.dumps(vehicle['photos'])
                vehicles.insert(vehicle)

            photos = json.loads(vehicle['photos'])
            for image_url in row['image_urls'].split(' '):
                if not image_url.startswith('http'):
                    continue
                try:
                    name, data = download_image(image_url)

                    photo = requests.post(
                        BASE + 'photos/',
                        data={'creator': 1},
                        files={
                            'image': (name, BytesIO(data))
                        }
                    ).json()
                    photos.append(photo['id'])
                except CATCH:
                    traceback.print_exc()

            vehicle = requests.patch(BASE + f"vehicles/{vehicle['id']}/", json={'photos': photos}).json()

        except CATCH:
            traceback.print_exc()

if __name__ == '__main__':
    pass
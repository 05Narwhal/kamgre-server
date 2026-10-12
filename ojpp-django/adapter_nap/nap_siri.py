from datetime import datetime, timedelta
from functools import lru_cache
from io import BytesIO
from typing import Optional, List

from authlib.integrations.httpx_client import AsyncOAuth2Client
from httpx import Response
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig

from generated.siri import VehicleMonitoringDeliveriesStructure, VehicleActivityStructure

from ojpp_core import settings

NAP_SIRI_URL = 'https://b2b.nap.si/data/b2b.siri.api/ServiceRequest'

class NAPClient(AsyncOAuth2Client):
    pass

client = NAPClient()

_token = None
async def ensure_token():
    if client.token and not client.token.is_expired():
        return
    global _token
    _token = await client.fetch_token(
        url='https://b2b.nap.si/uc/user/token',
        grant_type='password',
        username=settings.IJPP_USERNAME,
        password=settings.IJPP_PASSWORD,
    )


async def get_vehicle_activity() -> List[VehicleActivityStructure]:

    ts = (datetime.now() - timedelta(hours=1, minutes=5)).isoformat()
    xml = f'''\
<?xml version="1.0" encoding="utf-8"?>
<ServiceRequest xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="http://www.siri.org.uk/siri">
	<RequestTimestamp>{ts}</RequestTimestamp>
	<VehicleMonitoringRequest>
		<RequestTimestamp>{ts}</RequestTimestamp>
	</VehicleMonitoringRequest>
</ServiceRequest>
'''

    await ensure_token()

    resp: Response = await client.request(
        'POST',
        NAP_SIRI_URL,
        headers={
            'Content-Type': 'application/xml',
        },
        content=xml,
    )
    resp.raise_for_status()

    parser = XmlParser(context=XmlContext(), config=ParserConfig(fail_on_unknown_properties=False))

    root = parser.parse(BytesIO(resp.text.encode()), VehicleMonitoringDeliveriesStructure)
    vmd = root.vehicleMonitoringDelivery[0]

    return vmd.vehicleActivity


if __name__ == '__main__':
    import asyncio
    locs = asyncio.run(get_vehicle_activity())
    pass
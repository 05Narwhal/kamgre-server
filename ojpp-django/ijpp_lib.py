import asyncio
from datetime import datetime, timedelta

import httpx
from httpx import Timeout
from zeep import AsyncClient
from zeep.cache import SqliteCache
from zeep.transports import AsyncTransport


class IJPP:
    client: AsyncClient
    avl_client: AsyncClient

    async def init(self, cfg):
        cache = SqliteCache(path='/tmp/zepp_ijpp.db', timeout=60)
        httpx_client = httpx.AsyncClient(auth=(cfg.USERNAME, cfg.PASSWORD), timeout=Timeout(timeout=30))
        httpx_sync_client = httpx.Client(auth=(cfg.USERNAME, cfg.PASSWORD), timeout=Timeout(timeout=30))
        trans = AsyncTransport(client=httpx_client, wsdl_client=httpx_sync_client, cache=cache)
        self.client = AsyncClient(
            cfg.WSDL,
            transport=trans,
        )
        self.avl_client = AsyncClient(
            cfg.AVL_WSDL,
            transport=trans,
        )

    async def call_by_dict(self, method_name, request=dict(), avl=False):
        method = getattr((self.avl_client if avl else self.client).service, method_name)
        payload = dict(
            messageContext=dict(
                lRequestId=123,
            ),
            request=request,
        )
        # print(f'Calling {method_name} with {payload}')
        resp = await method(**payload)
        return resp

    async def get_vehicle_locations_raw(self):
        now = datetime.now() - timedelta(minutes=1)
        resp = await self.call_by_dict('GetVehicleMonitoring', dict(
                RequestTimestamp=now.isoformat(),
                vehicleMonitoringRequest=dict(
                    version="2.0",
                    RequestTimestamp=now.isoformat(),
                )
            ),
           avl=True,
        )
        assert resp.Result == 0, resp.ResultDescription
        return resp.serviceDelivery.vehicleMonitoringDelivery.vehicleActivity.VehicleActivity

    async def get_stations(self):
        resp = await self.call_by_dict('GetPostajalisca')
        for p in resp.postajalisca.Postajalisce:
            if p.jeAktivno != 0:
                op = oJPP_Postaja(
                    id=p.idPostajalisce,
                    naziv=p.ime,
                    lat=p.geometrija.X,
                    lng=p.geometrija.Y,
                )
                yield op

    async def vozni_red(self, vstop_id, izstop_id, iso_datum):
        r1 = await self.call_by_dict('GetRelation', dict(
            iStartStationId=vstop_id,
            iEndStationId=izstop_id,
        ))
        ids = [r.idRelacija for r in r1.relacije.Relacija]
        r2 = await self.call_by_dict('GetRelacije', dict(
            idRelacije=ids
        ))
        return r2



if __name__ == '__main__':
    async def main():
        ijpp = IJPP()
        await ijpp.init()

        #r1 = await ijpp.vozni_red(139129, 138922, None)

        #r1 = await ijpp.call_by_dict('GetPrevozniki')

        r2 = await ijpp.call_by_dict('GetVozniRediZaPrevoznika', dict(
            idPrevoznik=1109
        ))


        pass


    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

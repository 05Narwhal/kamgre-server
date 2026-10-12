import aiohttp


class MarpromAPI:

    class APIError(Exception):
        pass

    async def _request(self, method, path, error=False, **kwargs):
        async with aiohttp.request(method, 'https://vozniredi.marprom.si/OBA/' + path, **kwargs) as r:
            r.raise_for_status()
            data = await r.json()
            if error and data['Response']['Status'] != 1:
                raise MarpromAPI.APIError('API error: ' + data['Response']['Message'])
            return data

    async def get(self, path, error=False, **params):
        return await self._request('GET', path, error=error, params=params)

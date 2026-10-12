import asyncio

from django.core.management import BaseCommand

from adapter_ijpp.jobs import ijpp_update_prevozniki, ijpp_update_locations, Config
from ijpp_lib import IJPP


async def run():
    while True:
        await ijpp_update_locations()
        await asyncio.sleep(10)


class Command(BaseCommand):

    def handle(self, *args, **options):
        loop = asyncio.get_event_loop()
        # update_plates()
        loop.run_until_complete(run())
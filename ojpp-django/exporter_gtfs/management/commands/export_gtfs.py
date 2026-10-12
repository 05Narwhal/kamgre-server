import asyncio
from pathlib import Path

from django.core.management import BaseCommand

from exporter_gtfs.build_gtfs import main as build_gtfs


class Command(BaseCommand):

    def handle(self, *args, **options):
        # TODO: parameter for this
        OUTPUT = Path('ijpp_gtfs.zip')
        with OUTPUT.open('wb') as f:
            build_gtfs(f, args, options)
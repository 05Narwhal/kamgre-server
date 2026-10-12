from pathlib import Path
import requests
from django.conf import settings
from django.core.management import call_command


def export_gtfs():
    from exporter_gtfs.build_gtfs import main as build_gtfs
    OUTPUT = Path(settings.MEDIA_ROOT) / 'ijpp_gtfs.zip'
    with OUTPUT.open('wb') as f:
        build_gtfs(f)
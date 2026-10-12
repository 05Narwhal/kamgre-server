from django.core.management import BaseCommand, CommandError

from prestop_data.gtfs_import import FEEDS
from prestop_data.jobs import import_feed


class Command(BaseCommand):
    help = "Import public GTFS feeds (gtfs.derp.si mirror) into the OJPP tables."

    def add_arguments(self, parser):
        parser.add_argument('feeds', nargs='*', help=f'Feeds to import: {", ".join(FEEDS)} (default: all)')
        parser.add_argument('--no-download', action='store_true', help='Use the zip already in data/gtfs')
        parser.add_argument('--force', action='store_true', help='Import even if the file is unchanged')
        parser.add_argument('--no-shapes', action='store_true', help='Skip trip geometries (faster)')

    def handle(self, feeds, no_download, force, no_shapes, **options):
        unknown = set(feeds) - set(FEEDS)
        if unknown:
            raise CommandError(f'Unknown feeds: {", ".join(sorted(unknown))}')
        for feed in feeds or FEEDS:
            import_feed(feed, download=not no_download, force=force, shapes=not no_shapes,
                        log=lambda msg: self.stdout.write(msg))

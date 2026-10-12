from django.db import models


class GtfsRef(models.Model):
    """Maps a feed-qualified GTFS identifier to the OJPP row it was imported into.

    Lets re-imports update rows in place, so vehicle history attached to trips
    and stop times survives timetable refreshes.
    """

    class Kind(models.TextChoices):
        AGENCY = 'agency'
        SERVICE = 'service'
        STOP = 'stop'
        STOP_GROUP = 'stopgroup'
        ROUTE = 'route'
        ROUTE_GROUP = 'routegroup'
        TRIP = 'trip'

    feed = models.CharField(max_length=32)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    gtfs_id = models.CharField(max_length=255)
    object_id = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['feed', 'kind', 'gtfs_id'], name='prestop_gtfsref_unique'),
        ]
        indexes = [models.Index(fields=['feed', 'kind', 'object_id'])]

    def __str__(self):
        return f'{self.feed}:{self.kind}:{self.gtfs_id} -> {self.object_id}'


class GtfsImport(models.Model):
    feed = models.CharField(max_length=32, db_index=True)
    source_url = models.URLField(max_length=500)
    sha256 = models.CharField(max_length=64)
    last_modified = models.CharField(max_length=64, blank=True)
    started = models.DateTimeField()
    finished = models.DateTimeField(null=True, blank=True)
    succeeded = models.BooleanField(default=False)
    counts = models.JSONField(default=dict)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ('-started',)

    def __str__(self):
        return f'{self.feed} @ {self.started:%Y-%m-%d %H:%M} ({"ok" if self.succeeded else "failed"})'

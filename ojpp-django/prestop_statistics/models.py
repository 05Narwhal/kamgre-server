from django.db import models


class TripDelay(models.Model):
    """Reported delays of one trip on one service day, one value per stop already passed.

    Re-polling overwrites a stop's value instead of adding a sample, so frequent feeds
    do not gain weight. Delays come from the provider's GTFS-RT trip updates once the
    stop's event time has passed (quality "observed").
    """
    service_date = models.DateField()
    trip_id = models.CharField(max_length=200)
    route_id = models.CharField(max_length=200)
    operator_id = models.CharField(max_length=100)
    direction = models.CharField(max_length=8)
    stop_delays = models.JSONField(default=dict)  # {"<stopSequence>": delaySeconds}
    # Observed running time between consecutive stops, arrival to arrival:
    # {"<fromStopId>><toStopId>": seconds}. Averaged per route into typical travel times.
    segments = models.JSONField(default=dict)
    canceled = models.BooleanField(default=False)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['service_date', 'trip_id'], name='prestop_trip_delay_unique')]
        indexes = [models.Index(fields=['route_id', 'service_date'])]


class CollectorState(models.Model):
    """Last run of a collector, for health and freshness reporting."""
    source = models.CharField(max_length=64, primary_key=True)
    last_success = models.DateTimeField(null=True)
    last_error = models.TextField(blank=True)
    last_attempt = models.DateTimeField(null=True)
    counts = models.JSONField(default=dict)


class VehicleTrip(models.Model):
    """Which vehicle served a trip on a service day, from the vehicle positions feed (see blocks.py).

    `start`/`end` are the scheduled first departure and last arrival in seconds after the service day's
    midnight; `end_delay` is the trip's delay when the vehicle was last seen on it (its delay at the end
    once the trip is over). Kept for KEEP_DAYS days, pruned daily."""
    service_date = models.DateField()
    trip_id = models.CharField(max_length=200)
    vehicle_id = models.CharField(max_length=200)
    route_id = models.CharField(max_length=200)
    block_id = models.CharField(max_length=200, blank=True, default='')
    start = models.IntegerField()
    end = models.IntegerField()
    end_delay = models.IntegerField(null=True)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['service_date', 'trip_id'], name='prestop_vehicle_trip_unique')]
        indexes = [models.Index(fields=['route_id', 'service_date'], name='prestop_sta_route_i_7c1f2a_idx'),
                   models.Index(fields=['vehicle_id', 'service_date'], name='prestop_sta_vehicle_3b9e4d_idx')]

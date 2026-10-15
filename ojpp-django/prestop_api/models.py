from django.db import models


class RoadLeg(models.Model):
    """A road route between two consecutive stops, for bus patterns whose feed shape is
    missing or wrong there (see roads.py). Stops are keyed by position, not id, so a
    stop that moves gets a new route."""
    key = models.CharField(max_length=64, primary_key=True)  # "lat,lon;lat,lon", 5 decimals
    geometry = models.JSONField(default=list)  # [[lon, lat], ...]; empty when there is no road route
    created = models.DateTimeField(auto_now_add=True)


class PlatformSeen(models.Model):
    """A departure seen on a bus station's departure board, with its bay (see platforms.py).
    Keyed by station, time of day and destination, so the same departure on later days finds it."""
    key = models.CharField(max_length=200, primary_key=True)  # "IJPP:1126954|13:00|koper"
    platform = models.CharField(max_length=16)                 # as the board writes it: "13", "27-29"
    destination = models.CharField(max_length=120, default='')
    operator = models.CharField(max_length=80, default='')
    updated = models.DateTimeField(auto_now=True)



class VehicleHalt(models.Model):
    """A vehicle that stood more than detected.HALT_SECONDS at a stop that is not where its trip ends or waits
    (see detected.py): shown as a `vehicle-stopped` alert until it moves on (`cleared`). Kept 8 weeks."""
    vehicle_id = models.CharField(max_length=200)
    trip_id = models.CharField(max_length=200)
    route_id = models.CharField(max_length=200)
    stop_id = models.CharField(max_length=200)
    latitude = models.FloatField()
    longitude = models.FloatField()
    since = models.DateTimeField()
    last_seen = models.DateTimeField()
    cleared = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=['cleared', 'last_seen'], name='prestop_api_halt_open_idx')]


class AlertVote(models.Model):
    """"Is this right?" on a detected alert: one per alert and device (salted hashes, never the id or IP). Kept 8 weeks."""
    alert_id = models.CharField(max_length=120)
    device = models.CharField(max_length=64)   # salted hash of the app's random device id (or of the IP without one)
    ip = models.CharField(max_length=64)       # salted hash of the IP, for the rate limit
    vote = models.BooleanField()               # True: yes, it is right
    created = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['alert_id', 'device'], name='prestop_alert_vote_unique')]
        indexes = [models.Index(fields=['ip', 'created'], name='prestop_api_vote_ip_idx')]


class AnalyticsHour(models.Model):
    """Requests in one hour to one route (its URL pattern, never a path with ids) by status class (analytics.py).
    `buckets` counts requests by time taken (analytics.BUCKETS_MS), for a rough p95. Kept 400 days."""
    hour = models.DateTimeField()                   # start of the hour (UTC)
    route = models.CharField(max_length=64)         # "stops/*/board"
    status = models.CharField(max_length=3)         # "2xx", "4xx", ...
    count = models.PositiveIntegerField(default=0)
    ms = models.BigIntegerField(default=0)          # summed time taken
    buckets = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['hour', 'route', 'status'], name='prestop_analytics_hour_unique')]


class AnalyticsDay(models.Model):
    """One day's unique visitors (analytics.py): HyperLogLogs of salted hashes whose salt was deleted when the day
    ended, kept as bytes so any period can be merged. No IP, hash or id is stored. Kept forever."""
    day = models.DateField(primary_key=True)        # Europe/Ljubljana
    visitors = models.PositiveIntegerField(default=0)
    visitors_hll = models.BinaryField(default=bytes)
    new_users = models.PositiveIntegerField(default=0)  # onboarding finished (POST /stats/hello)
    platforms = models.JSONField(default=dict)      # {"ios": visitors, "android": ..., "desktop": ..., "app": ..., "browser": ...}
    platform_hll = models.JSONField(default=dict)   # the same as base64 HyperLogLogs

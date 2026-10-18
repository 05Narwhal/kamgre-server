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
    # Recorder version 2 (blocks.py): the stop pattern (a timetable change makes a new departure), the delay as
    # the trip set off, and where the vehicle ended and started.
    version = models.SmallIntegerField(default=1)
    pattern = models.CharField(max_length=16, blank=True, default='')
    start_delay = models.IntegerField(null=True)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    # How long it stood at each stop, {stopId: seconds}; 0: it drove through (dwell.py, spec 2026-10-18 A5).
    dwell = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['service_date', 'trip_id'], name='prestop_vehicle_trip_unique')]
        indexes = [models.Index(fields=['route_id', 'service_date'], name='prestop_sta_route_i_7c1f2a_idx'),
                   models.Index(fields=['vehicle_id', 'service_date'], name='prestop_sta_vehicle_3b9e4d_idx')]


class VehicleGap(models.Model):
    """What a vehicle did between two trips (blocks.GapTracker): a small summary, not its track. The trip before
    and after are blank where unknown (its first trip of the day, the collector restarted). `idle`: the spots it
    stood still at least blocks.IDLE_SECONDS, [[lat, lon, seconds], ...], from which depots are learned. Kept
    KEEP_DAYS days, like VehicleTrip."""
    service_date = models.DateField()  # the service day of the trip before (else of the trip after)
    vehicle_id = models.CharField(max_length=200)
    after_trip_id = models.CharField(max_length=200, blank=True, default='')
    before_trip_id = models.CharField(max_length=200, blank=True, default='')
    ended = models.DateTimeField()               # last seen on the trip before (or first seen without a trip)
    started = models.DateTimeField(null=True)    # first seen on the trip after; null when the gap expired
    terminus_wait = models.IntegerField(default=0)  # s stood within blocks.TERMINUS_METERS of the trip before's last stop
    max_distance = models.IntegerField(default=0)   # m: farthest from that stop
    seen_polls = models.IntegerField(default=0)     # polls the vehicle was in the feed without a trip
    unseen_polls = models.IntegerField(default=0)   # polls it was missing from the feed
    idle = models.JSONField(default=list)

    class Meta:
        indexes = [models.Index(fields=['vehicle_id', 'service_date'], name='prestop_sta_gap_vehicle_idx'),
                   models.Index(fields=['service_date'], name='prestop_sta_gap_day_idx')]


class RecorderDay(models.Model):
    """How much of a calendar day the vehicle recorder ran (blocks.record): `seconds` covered by polls a minute or
    so apart. Feed '*' is the collector itself; each feed also gets the seconds it had vehicles in the feed. The
    stay-on-the-same-vehicle learning opens only after 7 full days (blocks.gate)."""
    day = models.DateField()
    feed = models.CharField(max_length=64)
    version = models.SmallIntegerField(default=2)
    seconds = models.IntegerField(default=0)
    polls = models.IntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['day', 'feed'], name='prestop_recorder_day_unique')]


class StayDeparture(models.Model):
    """What stays.py learned, each night, about one departure (route + scheduled start + stop pattern) on one kind of
    day: where its vehicle comes from (`origin`: continues after `prev_*`, depot, unknown) and how sure staying on is
    (`level`). Only departures of feeds whose 7-full-days gate is open are written."""
    kind = models.CharField(max_length=8)
    feed = models.CharField(max_length=64)
    route_id = models.CharField(max_length=200)
    start = models.IntegerField()
    pattern = models.CharField(max_length=16)
    origin = models.CharField(max_length=10)
    level = models.CharField(max_length=6, blank=True, default='')  # 'sure', 'likely' or ''
    prev_route_id = models.CharField(max_length=200, blank=True, default='')
    prev_start = models.IntegerField(null=True)
    prev_pattern = models.CharField(max_length=16, blank=True, default='')
    prev_end = models.IntegerField(null=True)
    days = models.SmallIntegerField(default=0)    # observed days with a known origin
    share = models.FloatField(default=0)          # of them, the share with the top origin
    absorb = models.IntegerField(null=True)       # s of the previous trip's delay the layover takes up (median)
    depot_delay = models.IntegerField(null=True)  # s: the usual start delay on days it came from the depot
    learned_on = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'route_id', 'start'], name='prestop_stay_departure_unique')]


class StayCheck(models.Model):
    """The live check (stays.check): yesterday's `sure`/`likely` stays against what the vehicles did, per feed."""
    day = models.DateField()
    feed = models.CharField(max_length=64)
    level = models.CharField(max_length=6)
    hits = models.IntegerField(default=0)
    misses = models.IntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['day', 'feed', 'level'], name='prestop_stay_check_unique')]


class LearnedTime(models.Model):
    """What learned.py learned each night for one route on one kind of day ('workday', 'saturday', 'sunday', or '*'
    for all) in one hour band ('night', 'am', 'day', 'pm', 'eve', or '*'): running times between consecutive stops,
    `segments` {"from>to": [median, q25, q75, samples]}, and dwells, `dwells` {stopId: [mean s (0 s for trips that drove through included), share of trips
    that stood there, samples]}. Only keys with enough samples (learned.MIN_SAMPLES, MIN_FINE_SAMPLES for a kind of
    day or band); the table is rewritten each night."""
    route_id = models.CharField(max_length=200)
    kind = models.CharField(max_length=8)
    band = models.CharField(max_length=5)
    segments = models.JSONField(default=dict)
    dwells = models.JSONField(default=dict)
    learned_on = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['route_id', 'kind', 'band'], name='prestop_learned_time_unique')]

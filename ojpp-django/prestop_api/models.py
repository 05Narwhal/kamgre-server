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


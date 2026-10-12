from django.db import models

from ojpp_common.models import *

class BeaconType(models.TextChoices):
    WIFI = "wifi"
    BLE = "ble"

class VehicleBeacon(models.Model):
    type = models.CharField(max_length=4, choices=BeaconType.choices)
    identifier = models.CharField(max_length=17)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True)
    submitted_by = models.CharField(max_length=100)

    class Meta:
        unique_together = [
            ('type', 'identifier'),
        ]

class BeaconObservation(models.Model):
    beacon = models.ForeignKey(VehicleBeacon, on_delete=models.CASCADE, related_name='observations')
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True, editable=False)
    submitted_by = models.CharField(max_length=100)

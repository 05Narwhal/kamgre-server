from dataclasses import Field

from galleryfield.models import BuiltInGalleryImage
from rest_framework import serializers, fields

from ojpp_beacons.models import *


class BeaconSerializer(serializers.HyperlinkedModelSerializer):
    submitted_by = fields.CharField(write_only=True, required=True)
    class Meta:
        model = VehicleBeacon
        fields = ['id', 'identifier', 'type', 'vehicle', 'submitted_by']

class BeaconObservationSerializer(serializers.HyperlinkedModelSerializer):
    submitted_by = fields.CharField(write_only=True, required=True)
    class Meta:
        model = BeaconObservation
        fields = ['id', 'beacon', 'vehicle', 'timestamp', 'submitted_by']

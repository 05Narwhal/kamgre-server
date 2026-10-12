from dataclasses import Field

from galleryfield.models import BuiltInGalleryImage
from rest_framework import serializers

from ojpp_common.models import *


class VehicleSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Vehicle
        fields = ['id', 'ijpp_id', 'plate', 'vin', 'photos', 'model', 'operator', 'operator_vehicle_id']

class RouteSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Route
        fields = ['name', 'operator', 'route_group', 'ijpp_id', 'marprom_id', 'nvr_name', 'active']

class TripSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Trip
        fields = ['id', 'ijpp_id', 'piran_id', 'seq_number', 'route_id', 'name', 'geometry', 'geometry_is_final', 'active']


class OperatorSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = Operator
        fields = ['id', 'ijpp_id', 'name']


class BuiltInGalleryImageSerializer(serializers.ModelSerializer):

    class Meta:
        model = BuiltInGalleryImage
        fields = ['id', 'image', 'creator',]


class VehicleModelSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = VehicleModel
        fields = ['id', 'name', 'low_floor']


class StopSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = Stop
        fields = ['id', 'name', 'location', 'ijpp_id', 'marprom_id', 'lpp_id']


class StopLocationSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = StopLocation
        fields = ['id', 'name', 'location', 'ijpp_id', 'marprom_id', 'lpp_id', 'stop']

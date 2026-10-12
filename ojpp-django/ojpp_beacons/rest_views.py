import io
from dateutil.parser import isoparse
from django.http import Http404, HttpResponse, StreamingHttpResponse
from rest_framework import viewsets, permissions, routers
from rest_framework.decorators import action
from rest_framework.response import Response

from ojpp_beacons.serializers import *

class SubmitOnly(permissions.IsAuthenticatedOrReadOnly):
    def has_permission(self, request, view):
        if request.method == 'POST':
            return True
        return super().has_permission(request, view)


class VehicleBeaconViewSet(viewsets.ModelViewSet):
    queryset = VehicleBeacon.objects.all()
    serializer_class = BeaconSerializer
    permission_classes = [SubmitOnly]
    filterset_fields = ['submitted_by', 'vehicle', 'vehicle__operator', 'vehicle__plate',]


class BeaconObservationViewSet(viewsets.ModelViewSet):
    queryset = BeaconObservation.objects.all()
    serializer_class = BeaconObservationSerializer
    permission_classes = [SubmitOnly]
    filterset_fields = ['submitted_by', 'beacon__vehicle', 'beacon__vehicle__operator', 'beacon__vehicle__plate',]


router = routers.DefaultRouter()
router.register('beacons', VehicleBeaconViewSet)
router.register('beacon_observations', BeaconObservationViewSet)

import io
from base64 import b64encode

from PIL import Image
from dateutil.parser import isoparse
from django.http import Http404, HttpResponse, StreamingHttpResponse
from rest_framework import viewsets, permissions, routers
from rest_framework.decorators import action
from rest_framework.response import Response

from ojpp_common.serializers import *


class UpsertViewsetMixin(viewsets.ModelViewSet):
    update_data_pk_field = 'id'

    def create(self, request, *args, **kwargs):
        if request.data.get('upsert') != 'true':
            return super().create(request, *args, **kwargs)

        kwarg_field: str = self.lookup_url_kwarg or self.lookup_field
        self.kwargs[kwarg_field] = request.data[self.update_data_pk_field]

        try:
            return self.update(request, *args, **kwargs)
        except Http404:
            return super().create(request, *args, **kwargs)


class VehicleViewSet(UpsertViewsetMixin, viewsets.ModelViewSet):
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filterset_fields = ['ijpp_id', 'plate', 'operator', 'operator_vehicle_id', 'model',]

    class Meta:
        lookup_field = 'id'

    @action(methods=['get'], detail=True, description='Get location history for a vehicle on a specific day.')
    def locations_geojson(self, request, *args, **kwargs):
        vehicle_id = kwargs['pk']
        day = isoparse(request.query_params['date'])
        locations = VehicleLocation.objects.filter(vehicle_id=vehicle_id, time__date=day).select_related('trip')
        geojson = {
            'type': 'FeatureCollection',
            'features': [
                {
                    'type': 'Feature',
                    'properties': {
                        'time': loc.time.isoformat(),
                        'bearing': loc.bearing,
                        'trip_id': loc.trip_id,
                        'ijpp_trip_id': loc.trip.ijpp_id if loc.trip else None,
                        'route_id': loc.trip.route_id if loc.trip else None,
                    },
                    'geometry': {
                        'type': 'Point',
                        "coordinates": [loc.location.x, loc.location.y]

                    },
                }
                for loc in locations.all()
            ]
        }
        return Response(geojson)

    @action(methods=['get'], detail=True)
    def details(self, request, *args, **kwargs):
        vehicle = self.get_object()
        return Response(vehicle.details_dict())



class TripViewSet(UpsertViewsetMixin, viewsets.ModelViewSet):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filterset_fields = ['id', 'ijpp_id', 'piran_id', 'seq_number', 'active']

    class Meta:
        lookup_field = ['id', 'ijpp_id', 'piran_id']
    # get list of all trips
    @action(methods=['get'], detail=False)
    def all(self, request, *args, **kwargs):
        trips = Trip.objects.all()
        serializer = TripSerializer(trips, many=True)
        return Response(serializer.data)

    @action(methods=['get'], detail=True)
    def details(self, request, *args, **kwargs):
        trip = self.get_object()
        return Response(trip.details_dict())

    @action(methods=['get'], detail=True)
    def geometry(self, request, *args, **kwargs):
        trip = self.get_object()
        if not trip.geometry:
            return Response({
                'type': 'LineString',
                'coordinates': []
            })
        # convert from tuple to geojson
        geojson = {
            'type': 'LineString',
            'coordinates': trip.geometry.coords
        }
        return Response(geojson or {})


class OperatorViewSet(UpsertViewsetMixin, viewsets.ModelViewSet):
    queryset = Operator.objects.all()
    serializer_class = OperatorSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filterset_fields = ['ijpp_id', 'name', 'active']

    @action(methods=['get'], detail=False, url_path='details')
    def details(self, request, *args, **kwargs):
        resp = []

        for operator in Operator.objects.filter(active=True):
            logo = None
            if operator.logo_square:
                try:
                    image = Image.open(io.BytesIO(operator.logo_square.read()))
                    image.thumbnail((100, 100))
                    image_bytes = io.BytesIO()
                    image.save(image_bytes, format='PNG')
                    logo = b64encode(image_bytes.getvalue())
                except Exception as e:
                    logging.error(e)
            resp.append({
                'id': operator.id,
                'name': operator.get_short_name(),
                'logo_base64': logo,
                'color': operator.color,
            })
        return Response(resp)

    @action(methods=['get'], detail=True, url_path='logo.png')
    def logo(self, request, *args, **kwargs):
        operator: Operator = self.get_object()
        if operator.logo_square:
            image = Image.open(io.BytesIO(operator.logo_square.read()))
            image.thumbnail((100, 100))
            image_bytes = io.BytesIO()
            image.save(image_bytes, format='PNG')
            return HttpResponse(image_bytes.getvalue(), content_type='image/png')
        else:
            raise Http404('Provider does not have a logo!')

    class Meta:
        lookup_field = 'id'


class BuiltInGalleryImageViewSet(UpsertViewsetMixin, viewsets.ModelViewSet):
    queryset = BuiltInGalleryImage.objects.all()
    serializer_class = BuiltInGalleryImageSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filterset_fields = ['creator']

    class Meta:
        lookup_field = 'id'


class VehicleModelViewSet(UpsertViewsetMixin, viewsets.ModelViewSet):
    queryset = VehicleModel.objects.all()
    serializer_class = VehicleModelSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filterset_fields = ['id', 'name']

    class Meta:
        lookup_field = 'id'

class StopViewSet(UpsertViewsetMixin, viewsets.ModelViewSet):
    queryset = Stop.objects.all()
    serializer_class = StopSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filterset_fields = ['id', 'ijpp_id', 'marprom_id']

    class Meta:
        lookup_field = 'id'


class StopLocationViewSet(UpsertViewsetMixin, viewsets.ModelViewSet):
    queryset = StopLocation.objects.all()
    serializer_class = StopLocationSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filterset_fields = ['stop', 'ijpp_id', 'marprom_id']

    class Meta:
        lookup_field = 'id'


router = routers.DefaultRouter()
router.register('vehicles', VehicleViewSet)
router.register('trips', TripViewSet)
router.register('operators', OperatorViewSet)
router.register('photos', BuiltInGalleryImageViewSet)
router.register('vehicle-models', VehicleModelViewSet)
router.register('stops', StopViewSet)
router.register('stop-locations', StopLocationViewSet)

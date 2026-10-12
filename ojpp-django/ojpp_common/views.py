import json
import logging
from datetime import datetime, timedelta, date, time

import pytz
from ajax_datatable import AjaxDatatableView
from django.core.serializers import serialize
from django.db.models import Count, Sum, Min, Max
from django.db.models.functions import TruncHour
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.gzip import gzip_page
from django.views.generic import ListView, DetailView, TemplateView
from django_filters import FilterSet, BooleanFilter
from django_filters.views import FilterView
from rest_framework.views import APIView

from ojpp_common.models import Stop, VehicleLocation, StopLocation, Operator, Vehicle, Trip, Route, StopTime, Schedule, \
    TripInstance
from ojpp_common.util import calculate_active_days, get_times_for_active_trips, format_timedelta


class StopLocationsView(APIView):

    def get_queryset(self):
        qs = StopLocation.objects.select_related("stop")
        if self.request.query_params.get("include_active") != '1':
            qs = qs.filter(is_active=True)
        return qs

    @method_decorator(gzip_page)
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request, *args, **kwargs):
        qs = self.get_queryset()
        features = []
        for sl in qs:
            sl: StopLocation
            try:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "id": sl.id,
                        "operator_id": sl.operator_stop_id,
                        "name": sl.name or sl.stop.name,
                        "photo": sl.photo.url if sl.photo else None,
                    },
                    "geometry": {"type": "Point", "coordinates": [sl.location.x, sl.location.y]}
                })
            except:
                logging.exception(f'Error while processing StopLocation #{sl.id}')
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        return JsonResponse(geojson, safe=False)


class StopLocationsArrivalsView(APIView):
    def get(self, request, *args, **kwargs):

        pk = self.kwargs['pk']
        d = date.today()
        if self.request.GET.get('date'):
            d = datetime.strptime(self.request.GET.get('date'), '%Y-%m-%d').date()

        stoptimes = get_times_for_active_trips(pk, d)
        stoptimes = stoptimes.select_related('trip', 'trip__route', 'trip__route__operator')
        stoptimes = list(stoptimes)
        stoptimes.sort(key=lambda x: min(x.time_arrival or time.max, x.time_departure or time.max))
        a_bit_before_now = datetime.now().astimezone() - timedelta(minutes=5)
        if d == date.today():
            locations = VehicleLocation.objects.filter(trip_id__in=[stoptime.trip_id for stoptime in stoptimes], time__gt=a_bit_before_now).select_related('vehicle', 'vehicle__model')
        else:
            locations = []
        loc_by_trip = {l.trip_id: l for l in locations}

        j = []
        for stoptime in stoptimes:
            stoptime: StopTime
            o = {
                'trip_id': stoptime.trip_id,
                'route_id': stoptime.trip.route_id,
                'route_name': stoptime.trip.route.get_name(),
                'time_arrival': stoptime.time_arrival.strftime(
                    '%H:%M:%S') if stoptime.time_arrival is not None else None,
                'time_departure': stoptime.time_departure.strftime(
                    '%H:%M:%S') if stoptime.time_departure is not None else None,
                'operator': {
                    'id': stoptime.trip.route.operator_id,
                    'name': stoptime.trip.route.operator.name,
                },
                'active': stoptime.active,
            }
            if stoptime.trip_id in loc_by_trip:
                loc = loc_by_trip[stoptime.trip_id]
                o['vehicle'] = {
                    'id': loc.vehicle_id,
                    'plate': loc.vehicle.plate if loc.vehicle.plate else None,
                    'model': {
                        'name': loc.vehicle.model.name,
                        'low_floor': loc.vehicle.model.low_floor,
                    } if loc.vehicle.model else None,
                }
            j.append(o)

        rsp = json.dumps(j)

        return HttpResponse(rsp, content_type='application/json')


class VehicleLocationsView(APIView):
    LAST_MINUTES = 5
    def get_queryset(self):
        now = datetime.now().astimezone() - timedelta(minutes=self.LAST_MINUTES)
        qs = VehicleLocation.objects.prefetch_related('vehicle', 'trip', 'trip__route', 'vehicle__operator').order_by('vehicle_id', '-time').distinct('vehicle_id').filter(time__gt=now)
        if 'exclude_operators' in self.request.GET:
            slugs = self.request.GET['exclude_operators'].split(',')
            qs = qs.exclude(vehicle__operator__slug__in=slugs)
        return qs

    @method_decorator(gzip_page)
    def get(self, request, *args, **kwargs):
        qs = self.get_queryset()
        features = []
        for loc in qs:
            loc: VehicleLocation
            try:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "operator_vehicle_id": loc.vehicle.operator_vehicle_id,
                        "vehicle_id": loc.vehicle.id,
                        "trip_id": loc.trip_id,
                        "route_id": loc.trip.route_id if loc.trip else None,
                        "route_name": loc.trip.name if loc.trip else None,
                        "operator_id": loc.vehicle.operator_id,
                        "operator_name": loc.vehicle.operator.name,
                        "direction": loc.bearing,
                        "time": loc.time.isoformat(),
                        "opacity": 1 - (datetime.now().astimezone() - loc.time).total_seconds() / 60 / self.LAST_MINUTES,
                    },
                    "geometry": {"type": "Point", "coordinates": [loc.location.x, loc.location.y]}
                })
            except:
                logging.exception(f'Error while processing VehicleLocation #{loc.id}')
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        return JsonResponse(geojson, safe=False)


@method_decorator(cache_page(60 * 60 * 24), name='dispatch')
class OperatorListView(FilterView, ListView):
    model = Operator
    template_name = 'ojpp_common/operator_list.html'
    filterset_fields = ('active',)

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.annotate(vehicles__count=Count('vehicles', distinct=True), routes__count=Count('routes', distinct=True))
        qs = qs.order_by('name')
        return qs


class OperatorDetailView(DetailView):
    model = Operator

    def get_queryset(self):
        return super().get_queryset().prefetch_related('routes', 'vehicles', 'routes__route_group')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['routes'] = ctx['object'].routes.annotate(trip_count=Count('trips')).order_by('trip_count').prefetch_related('last_stop', 'first_stop')
        return ctx


class VehicleView(DetailView):
    model = Vehicle

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['tripinstances'] = TripInstance.objects.filter(vehicle=self.get_object()).order_by('-created')[:10]
        return ctx


class VehicleListView(FilterView):
    model = Vehicle
    filterset_fields = ('operator', 'type', 'model',)

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.prefetch_related('operator', 'model')
        return qs


class RouteListView(ListView):
    model = Route
    template_name = 'ojpp_common/route_list.html'

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related('operator', 'first_stop', 'last_stop')
        return qs


class RouteDetailView(DetailView):
    model = Route

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['line'] = serialize('geojson', [self.get_object()], geometry_field='geometry')

        return context

class TripFilterView(FilterView):
    template_name_suffix = '_list'
    model = Trip
    filterset_fields = ('schedule',)

    def get_queryset(self):
        return super().get_queryset().select_related('route__operator',)


class TripDetailView(DetailView):
    model = Trip

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['stoptimes'] = context['object'].stoptimes.prefetch_related('stop_location__stop').order_by('sequence_num')
        context['tripinstances'] = context['object'].instances.order_by('-created')[:10]

        return context

class TripInstanceFilterView(FilterView):
    model = TripInstance
    filterset_fields = ('trip', 'trip__route__operator')

    def get_queryset(self):
        qs = super().get_queryset()

        #qs = qs.annotate(vehicles__count=Count('vehicles', distinct=True), routes__count=Count('routes', distinct=True))
        #qs = qs.order_by('name')
        return qs

class StopListView(ListView):
    model = Stop

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.prefetch_related('route', )
        return qs


class StopDetailView(DetailView):
    model = Stop

    def get_queryset(self):
        return super().get_queryset().prefetch_related('stoplocation_set')


class StopLocationListView(ListView):
    model = StopLocation

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.prefetch_related('stop', )
        return qs


class StopLocationsDatatableView(AjaxDatatableView):
    model = StopLocation
    title = 'Permissions'
    initial_order = [["id", "asc"], ]
    # length_menu = [[10, 20, 50, 100, -1], [10, 20, 50, 100, 'all']]
    search_values_separator = '+'

    column_defs = [
        AjaxDatatableView.render_row_tools_column_def(),
        {'name': 'id', 'title': 'ID'},
        {'name': 'name', 'title': 'Ime'},
        {'name': 'operator_stop_id', 'title': 'Št. postaje'},
        {'name': 'ijpp_id', 'title': 'ijpp_id'},
        {'name': 'marprom_id', 'title': 'marprom_id'},
    ]


class StopLocationDetailView(DetailView):
    model = StopLocation

    def get_queryset(self):
        return super().get_queryset().prefetch_related('stop')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        stoploc = ctx['object']
        ctx['stoptimes'] = StopTime.objects.filter(stop_location=stoploc).prefetch_related('trip', 'trip__route').order_by('trip__route__name', 'trip__name', 'sequence_num')
        ctx['routes'] = Route.objects.filter(trips__stoptimes__stop_location=stoploc).prefetch_related('operator', 'route_group').distinct()
        return ctx


class ScheduleListView(ListView):
    model = Schedule

    def get_queryset(self):
        return super().get_queryset().annotate(trips__count=Count('trip', distinct=True))


class ScheduleDetailView(DetailView):
    model = Schedule

    def get_queryset(self):
        return super().get_queryset().prefetch_related('periods', 'exceptions')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['days_active'] = calculate_active_days(context['object'], datetime.now().year)
        return context


class StatsView(TemplateView):
    template_name = 'ojpp_common/stats.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['counts'] = {
            'routes': Route.objects.count(),
            'stop_locations': StopLocation.objects.count(),
            'vehicles': Vehicle.objects.count(),
        }
        dataset = VehicleLocation.objects.filter(
            time__gt=timezone.now() - timedelta(days=10),
        ).annotate(
            hour=TruncHour('time')
        ).values(
            'hour',
        ).annotate(
            c=Count('vehicle_id', distinct=True)
        ).values(
            'hour',
            'c',
        )
        ctx['vehicle_locations'] = list(dataset)[:-1]
        return ctx


class TripInstanceDetailView(DetailView):
    model = TripInstance

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['trip'] = context['object'].trip
        context['stoptime_instances'] = context['object'].stoptimes.select_related('stoptime', 'vehicle_location').prefetch_related('stoptime__stop_location', 'stoptime__stop_location__stop').order_by('stoptime__sequence_num')

        stis = {sti.stoptime: sti for sti in context['stoptime_instances']}
        context['rows'] = [
            {
                'stoptime': st,
                'stoptime_instance': stis.get(st),
            }
            for st in context['trip'].stoptimes.order_by('sequence_num').all()
        ]
        # calculate delays
        for row in context['rows']:
            sti = row['stoptime_instance']
            st = row['stoptime']
            if not sti:
                continue

            TZ = pytz.timezone('Europe/Ljubljana')
            if st.time_arrival and sti.time_arrival:
                # Convert location timestamp (UTC) to bus-local time
                time_arrival_local = sti.time_arrival.astimezone(TZ)
                row['time_arrival_local'] = time_arrival_local
                # Convert scheduled time (in local time) to a datetime
                sched_time_arrival_local = time_arrival_local.replace(hour=st.time_arrival.hour, minute=st.time_arrival.minute, second=0, microsecond=0)
                # Calculate delay
                sti.time_arrival_delay = format_timedelta(time_arrival_local - sched_time_arrival_local)
            if st.time_departure and sti.time_departure:
                time_departure_local = sti.time_departure.astimezone(TZ)
                row['time_departure_local'] = time_departure_local
                sched_time_departure_local = time_departure_local.replace(hour=st.time_departure.hour, minute=st.time_departure.minute, second=0, microsecond=0)
                sti.time_departure_delay = format_timedelta(time_departure_local - sched_time_departure_local)
        return context

class ActiveTripInstanceListView(ListView):
    model = TripInstance
    template_name = 'ojpp_common/active_tripinstance_list.html'

    def get_queryset(self):
        qs = super().get_queryset()
        # Last 24 hrs
        qs = qs.filter(created__gt=(date.today() - timedelta(days=1)))
        # Get last stop time
        qs = qs.annotate(last_stop_arrival=Max('stoptimes__time_arrival'))
        # Optimizations
        qs = qs.select_related('trip', 'vehicle__operator')
        # Order by
        qs = qs.order_by('-created')
        return qs

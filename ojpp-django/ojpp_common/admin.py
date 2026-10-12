from django.contrib import admin
from django.contrib.admin import TabularInline
from django.db.models import Count
from django.forms import ModelForm
from django.utils.safestring import mark_safe
from django_admin_relation_links import AdminChangeLinksMixin
from galleryfield.mixins import GalleryFormMediaMixin
from leaflet.admin import LeafletGeoAdminMixin
from leaflet_admin_list.admin import LeafletAdminListMixin
from rangefilter.filters import DateRangeFilter
from import_export.admin import ImportExportModelAdmin

from ojpp_core.util import AdminAnnotateMixin
from .models import *
from .util import merge_objects_action

admin.site.site_title = 'oJPP Admin'
admin.site.site_header = 'oJPP Admin'
admin.site.index_title = 'oJPP Admin'


class CustomInline(LeafletGeoAdminMixin, TabularInline):
    show_change_link = True
    extra = 0

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VehicleLocation)
class VehicleLocationAdmin(LeafletGeoAdminMixin, ImportExportModelAdmin):
    model = VehicleLocation
    list_display = ('__str__', 'vehicle_id', 'time', 'vehicle_operator', 'vehicle_plate')
    list_filter = ('vehicle__operator',)
    raw_id_fields = ('vehicle', 'trip',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('vehicle', 'vehicle__operator')

    def vehicle_id(self, obj):
        return mark_safe(f'<a href="/admin/ojpp_common/vehicle/{obj.vehicle_id}">{obj.vehicle.id}</a>')
    vehicle_id.admin_order_field = 'vehicle__id'

    def vehicle_operator(self, obj):
        return obj.vehicle.operator

    def vehicle_plate(self, obj):
        return obj.vehicle.plate


@admin.register(VehicleModel)
class VehicleModelAdmin(ImportExportModelAdmin):
    model = VehicleModel
    search_fields = ('name',)
    list_display = ('name',)
    actions = [merge_objects_action]


class VehicleAdminForm(GalleryFormMediaMixin, ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["photos"].required = False

    class Meta:
        model = Vehicle
        exclude = ()


@admin.register(Vehicle)
class VehicleAdmin(ImportExportModelAdmin):
    model = Vehicle
    search_fields = ('ijpp_id', 'plate', 'model__name')
    list_filter = ('operator',)
    list_display = ('__str__', 'operator', 'plate', 'model', 'operator_vehicle_id')
    autocomplete_fields = ('model',)
    form = VehicleAdminForm
    actions = [merge_objects_action]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('operator')


class VehicleInline(CustomInline):
    model = Vehicle


class RouteInline(CustomInline):
    model = Route


@admin.register(Operator)
class OperatorAdmin(AdminAnnotateMixin, ImportExportModelAdmin):
    model = Operator
    list_display = ('__str__', 'name', 'ijpp_šifra', 'active', 'aliases', 'vehicle_count', 'route_count')
    search_fields = ('ijpp_id', 'name', 'tax_id', 'active', 'aliases')
    list_editable = ('active', 'ijpp_šifra', 'aliases')
#    inlines = [RouteInline, VehicleInline]
    actions = [merge_objects_action]
    annotate = {
        'vehicle_count': Count('vehicles', distinct=True),
        'route_count': Count('routes', distinct=True),
    }


class TripInline(CustomInline):
    model = Trip


@admin.register(Route)
class RouteAdmin(AdminChangeLinksMixin, LeafletGeoAdminMixin, AdminAnnotateMixin, ImportExportModelAdmin):
    model = Route
    search_fields = ('ijpp_id', 'name', 'nvr_name',)
    list_filter = ('active', 'operator',)
    list_display = ('id', 'active', 'name', 'operator', 'nvr_name', 'route_type', 'first_stop', 'last_stop', 'trip_count')
    inlines = [TripInline]
    annotate = {
        'trip_count': Count('trips'),
    }


class StopTimeInline(CustomInline):
    model = StopTime


@admin.register(Trip)
class TripAdmin(AdminChangeLinksMixin, ImportExportModelAdmin):
    model = Trip
    search_fields = ('ijpp_id',)
    list_display = ('id', 'active', 'ijpp_id', 'route', 'headsign', 'schedule')
    list_filter = ('active', 'route__operator', 'schedule')
    inlines = [StopTimeInline]
    changelist_links = ('route', 'schedule',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('route', 'schedule')

@admin.register(StopTime)
class StopTimeAdmin(AdminChangeLinksMixin, ImportExportModelAdmin):
    model = StopTime
    search_fields = ('ijpp_id',)
    list_display = ('active', 'stop_location', 'time_arrival', 'time_departure')
    list_filter = ('active', 'trip__route__operator',)
    fields = ('active', 'trip', 'time_arrival', 'time_departure',)
    changelist_links = ('trip',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('stop_location')


class StopLocationInline(CustomInline):
    model = StopLocation

@admin.register(RouteSegment)
class RouteSegmentAdmin(AdminChangeLinksMixin, ImportExportModelAdmin):
    model = RouteSegment
    list_display = ('id', 'start_stop', 'end_stop', 'time', 'length',)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('start_stop', 'end_stop')
                        


@admin.register(Stop)
class StopAdmin(LeafletAdminListMixin, LeafletGeoAdminMixin, ImportExportModelAdmin):
    search_fields = ('name', 'ijpp_id',)
    list_display = ('id', 'name', 'location_count',)
    model = Stop
    inlines = (StopLocationInline, )


@admin.register(StopLocation)
class StopLocationAdmin(AdminChangeLinksMixin, LeafletAdminListMixin, LeafletGeoAdminMixin, ImportExportModelAdmin):
    model = StopLocation
    list_display = ('__str__', 'stop', 'ijpp_id', 'marprom_id')
    changelist_links = ('stop',)


class TimetablePeriodInline(CustomInline):
    model = TimetablePeriod

class TimetableExceptionInline(CustomInline):
    model = TimetableException

@admin.register(Schedule)
class ScheduleAdmin(ImportExportModelAdmin):
    model = Schedule
    list_display = ('__str__', 'ijpp_id', 'name', 'ijpp_tag', 'description', '_trip_count', '_period_count', '_exception_count',)
    search_fields = ('name', 'ijpp_id', 'ijpp_tag', 'description',)
    inlines = (TimetablePeriodInline, TimetableExceptionInline, )

    def _trip_count(self, obj):
        return obj.trips__count
    _trip_count.admin_order_field = 'trips__count'

    def _period_count(self, obj):
        return obj.periods__count
    _period_count.admin_order_field = 'periods__count'

    def _exception_count(self, obj):
        return obj.exceptions__count
    _exception_count.admin_order_field = 'exceptions__count'

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(periods__count=Count('periods', distinct=True), exceptions__count=Count('exceptions', distinct=True), trips__count=Count('trip', distinct=True))

@admin.register(StopTimeInstance)
class StopTimeInstanceAdmin(ImportExportModelAdmin):
    model = StopTimeInstance
    list_display = ('__str__', 'trip_instance_id', 'seq', 'stop', 'time_arrival', 'time_arrival_scheduled', 'time_departure', 'time_departure_scheduled')
    raw_id_fields = ('trip_instance', 'stoptime', 'vehicle_location',)
    ordering = ('trip_instance', 'stoptime__sequence_num',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('trip_instance', 'stoptime',).prefetch_related('stoptime__stop_location__stop')

    def seq(self, obj):
        return obj.stoptime.sequence_num

    def stop(self, obj):
        return obj.stoptime.stop_location.stop.name

    def time_arrival_scheduled(self, obj):
        return obj.stoptime.time_arrival
    time_arrival_scheduled.admin_order_field = 'stoptime__time_arrival'

    def time_departure_scheduled(self, obj):
        return obj.stoptime.time_departure
    time_departure_scheduled.admin_order_field = 'stoptime__time_departure'

class StopTimeInstanceInline(admin.TabularInline):
    model = StopTimeInstance
    raw_id_fields = ('stoptime', 'trip_instance', 'vehicle_location',)

@admin.register(TripInstance)
class TripInstanceAdmin(AdminAnnotateMixin, ImportExportModelAdmin):
    model = TripInstance
    list_display = ('id', 'created', 'trip', 'stop_time_count', )
    list_filter = (
        ('created', DateRangeFilter),
        'trip__route__operator',
    )
    inlines = (StopTimeInstanceInline, )
    raw_id_fields = ('trip', 'vehicle')
    annotate = {
        'stop_time_count': Count('stoptimes', distinct=True),
    }

    #def get_queryset(self, request):
    #    return super().get_queryset(request).prefetch_related('trip',)

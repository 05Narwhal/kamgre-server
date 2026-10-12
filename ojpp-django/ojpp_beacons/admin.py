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
from .resources import *


@admin.register(VehicleBeacon)
class VehicleBeaconAdmin(AdminAnnotateMixin, ImportExportModelAdmin):
    model = VehicleBeacon
    list_display = ('__str__', 'identifier', 'type', 'submitted_by', 'observation_count')
    search_fields = ('submitted_by',)
    resource_classes = [VehicleBeaconResource]
    annotate = {
        'observation_count': Count('observations', distinct=True),
    }

    def get_changeform_initial_data(self, request):
        return super().get_changeform_initial_data(request) | {
            'submitted_by': request.user.username
        }

@admin.register(BeaconObservation)
class BeaconObservationAdmin(admin.ModelAdmin):
    models = BeaconObservation
    list_display = ('__str__', 'beacon', 'timestamp', 'submitted_by')
    search_fields = ('submitted_by',)

    def get_changeform_initial_data(self, request):
        return super().get_changeform_initial_data(request) | {
            'submitted_by': request.user.username
        }

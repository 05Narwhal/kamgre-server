from django.shortcuts import redirect
from django.urls import path, include
from django.views.generic import TemplateView, RedirectView

from ojpp_common.rest_views import router
from ojpp_common.views import *

urlpatterns = [
    path('', lambda r: redirect('/operators?active=true')),

    path('legal', TemplateView.as_view(template_name='legal.html')),
    path('stats', StatsView.as_view(), name='stats'),
    path('about', TemplateView.as_view(template_name='about.html')),
    path('map', TemplateView.as_view(template_name='location_map.html')),
    path('locations', RedirectView.as_view(url='/map')),

    path('api/stop_locations', StopLocationsView.as_view()),
    path('api/stop_locations/<int:pk>/arrivals', StopLocationsArrivalsView.as_view()),
    path('api/vehicle_locations', VehicleLocationsView.as_view()),
    path('operators', OperatorListView.as_view(), name='operator_list'),
    path('operators/<int:pk>', OperatorDetailView.as_view(), name='operator_detail'),
    path('vehicles', VehicleListView.as_view(), name='vehicle_list'),
    path('vehicles/<int:pk>', VehicleView.as_view(), name='vehicle_detail'),
    path('routes', RouteListView.as_view(), name='route_list'),
    path('routes/<int:pk>', RouteDetailView.as_view(), name='route_detail'),
    path('trips', TripFilterView.as_view(), name='trip_list'),
    path('trips/<int:pk>', TripDetailView.as_view(), name='trip_detail'),
    #path('tripinstances', TripInstanceFilterView.as_view(), name='tripinstance_list'),
    path('tripinstances/active', ActiveTripInstanceListView.as_view(), name='tripinstance_active'),
    path('tripinstances/<int:pk>', TripInstanceDetailView.as_view(), name='tripinstance_detail'),
    path('stops', StopListView.as_view(), name='stop_list'),
    path('stops/<int:pk>', StopDetailView.as_view(), name='stop_detail'),
    path('stop_locations', StopLocationListView.as_view(), name='stop_location_list'),
    path('stop_locations/datatables', StopLocationsDatatableView.as_view(), name='stop_location_list_datatables'),
    path('stop_locations/<int:pk>', StopLocationDetailView.as_view(), name='stop_location_detail'),
    path('schedules', ScheduleListView.as_view(), name='schedule_list'),
    path('schedules/<int:pk>', ScheduleDetailView.as_view(), name='schedule_detail'),

    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework'))
]


urlconf = urlpatterns, 'ojpp_common', 'ojpp_common'


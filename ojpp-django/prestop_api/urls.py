from django.urls import path

from . import views

urlpatterns = [
    path('health', views.health),
    path('capabilities', views.capabilities),
    path('stats/hello', views.stats_hello),
    path('locale', views.locale),
    path('places', views.places),
    path('stops', views.stops),
    path('stops/<path:stop_id>/board', views.board),
    path('vehicles', views.vehicles),
    path('rentals', views.rentals),
    path('trips', views.trip_list),
    path('trips/<path:trip_id>', views.trip_detail),
    path('lines/<path:route_id>', views.line_detail),
    path('statistics/reliability', views.statistics_reliability),
    path('journeys', views.journeys),
    path('alerts', views.alerts),
    path('alerts/<path:alert_id>/votes', views.alert_votes),
    path('statistics/routes', views.statistics_routes),
    path('statistics/routes/<path:route_id>/daily', views.statistics_daily),
]

from django.urls import path

from . import views

urlpatterns = [
    path('health', views.health),
    path('capabilities', views.capabilities),
    path('stats/hello', views.stats_hello),
    path('hop/presence', views.hop_presence),
    path('hop/nearby', views.hop_nearby),
    path('hop/send', views.hop_send),
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
    path('pricing/catalog', views.pricing_catalog),
    path('alerts', views.alerts),
    path('alerts/<path:alert_id>/votes', views.alert_votes),
    path('statistics/routes', views.statistics_routes),
    path('statistics/routes/<path:route_id>/daily', views.statistics_daily),
    path('statistics/overview', views.statistics_overview),
    path('stations/<path:stop_id>/statistics', views.station_statistics),
    path('rail/works', views.rail_works),
    path('trains/<str:number>/history', views.train_history),
    path('trains/<str:number>', views.train_detail),
]

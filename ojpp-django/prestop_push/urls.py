from django.urls import path

from . import views

urlpatterns = [
    path('subscriptions', views.subscriptions),
    path('watches', views.watches),
    path('watches/<path:client_id>', views.watch_detail),
    path('test', views.test),
]

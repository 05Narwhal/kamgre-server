"""Upstream URLs plus the Prestop facade at /api/v1/ (mounted first so upstream
catch-all routes cannot shadow it). Upstream `urls.py` stays untouched."""
from django.urls import include, path

from ojpp_core.urls import urlpatterns as upstream

urlpatterns = [path('api/v1/push/', include('prestop_push.urls')), path('api/v1/', include('prestop_api.urls')), *upstream]

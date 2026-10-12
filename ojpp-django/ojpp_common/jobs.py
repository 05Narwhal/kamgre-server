import requests
from django.core.management import call_command
from django.db.models import Count

from ojpp_common.metrics import G_LOCATIONS_TOTAL


def updatedata():
    call_command("updatedata")


def ping():
    r = requests.post('https://hc-ping.com/4404e378-98cc-4ebb-b7d0-ac8b8f6b81fe')
    r.raise_for_status()

def update_stop_active_status():
    # TODO: implement
    StopLocation.objects.annotate(stoptime_count=Count('stoptime')).filter(stoptime_count=0).select_related('stop').update(is_active=False)
    StopLocation.objects.annotate(stoptime_count=Count('stoptime')).filter(stoptime_count__gt=0).select_related(
        'stop').update(is_active=True)

def update_prometheus_metrics():
    from ojpp_common.models import VehicleLocation
    G_LOCATIONS_TOTAL.set(VehicleLocation.objects.count())

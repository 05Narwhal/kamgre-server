import time
from collections import defaultdict
from datetime import timedelta, datetime
from types import TracebackType

from django.contrib import admin

SENTRY_MAX_PER_LINE = timedelta(hours=10).total_seconds()
last_sent = defaultdict(float)


def sentry_filter(event, hint):
    if 'exc_info' in hint:
        exc_type, exc_value, tb = hint['exc_info']
        tb: TracebackType
        fingerprint = f'{tb.tb_frame.f_lineno}:{tb.tb_frame.f_code.co_filename}'
        if time.time() - last_sent[fingerprint] > SENTRY_MAX_PER_LINE:
            last_sent[fingerprint] = time.time()
            return event
        return None
    return event


class AdminAnnotateMixin(admin.ModelAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if hasattr(self, 'annotate'):
            qs = qs.annotate(**self.annotate)
        return qs

    def __init__(self, *args, **kwargs):
        if hasattr(self, 'annotate'):
            for field in self.annotate:
                fun = lambda obj, f=field: getattr(obj, f)
                fun.__name__ = field
                fun.admin_order_field = field
                setattr(self, field, fun)
        super().__init__(*args, **kwargs)



def seconds_to_time(seconds):
    return datetime.utcfromtimestamp(seconds).time()

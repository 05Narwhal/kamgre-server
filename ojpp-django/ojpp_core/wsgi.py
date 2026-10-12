"""
WSGI config for ojpp_core project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ojpp_core.settings")

application = get_wsgi_application()

# Fill the timetable and stop caches as the server starts, so the first person doesn't wait for them
# (prestop_api/warm.py; off in tests and when PRESTOP_WARM is false).
from prestop_api import warm  # noqa: E402

warm.boot()

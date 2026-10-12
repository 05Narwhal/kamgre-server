"""Production settings for the Oracle server: the Prestop overlay plus hardening.

Kept in backend/deploy so no backend source file changes. The systemd units put this
directory on PYTHONPATH and set DJANGO_SETTINGS_MODULE=prestop_production.
"""
from ojpp_core.settings_prestop import *  # noqa: F401,F403
from ojpp_core.settings_prestop import env, DATABASES, MIDDLEWARE  # noqa: E402

DEBUG = False
SECRET_KEY = env('SECRET_KEY')  # required: no insecure fallback in production

PRESTOP_DOMAIN = env('PRESTOP_DOMAIN')
# The app is served by Vercel on the domain; this server answers only on api.<domain>.
ALLOWED_HOSTS = [f'api.{PRESTOP_DOMAIN}', '127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = [f'https://{PRESTOP_DOMAIN}', f'https://www.{PRESTOP_DOMAIN}']
# Only the app's own origins may call the API from a browser, with cookies (kg_admit).
CORS_ALLOWED_ORIGINS = [f'https://{PRESTOP_DOMAIN}', f'https://www.{PRESTOP_DOMAIN}']
CORS_ALLOWED_ORIGIN_REGEXES = []
CORS_ALLOW_CREDENTIALS = True
CORS_URLS_REGEX = r'^/api/v1/'
CORS_PREFLIGHT_MAX_AGE = 86400
# CORS runs first, so the traffic guard's 429/503 answers carry CORS headers and the app can
# show their message, and preflight requests are answered without counting against a visitor.
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware', *(m for m in MIDDLEWARE if m != 'corsheaders.middleware.CorsMiddleware')]

# Cloudflare terminates HTTPS; Caddy forwards X-Forwarded-Proto from cloudflared.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Load shedding (prestop_api/traffic.py), always on in production: new visitors are refused when
# the server is busy, and everything stops when the egress guard trips. Visitors only arrive through
# the Cloudflare tunnel, which sets CF-Connecting-IP; requests without it come from the server itself.
PRESTOP_TRAFFIC_GUARD = True
PRESTOP_CLIENT_IP_HEADER = 'CF-Connecting-IP'
PRESTOP_TRAFFIC_STATE_DIR = '/var/lib/prestop/traffic'

# Reuse database connections between requests (peer auth over the local socket).
DATABASES['default']['CONN_MAX_AGE'] = 60
DATABASES['default']['CONN_HEALTH_CHECKS'] = True

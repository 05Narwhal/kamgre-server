from pathlib import Path

from environ import environ

from ojpp_core.util import sentry_filter

root = Path(__file__).parent.parent

# Fetch env vars
env = environ.Env(
    DEBUG=(bool, False),
    DEBUG_IPS=(list, []),
    ALLOWED_HOSTS=(list, []),
    ADMINS=(list, ["admin"]),
    SENTRY_DSN=(str, None),
    ENVIRONMENT=(str, 'dev-unknown'),
    DATA_DIR=(str, '/tmp'),
)
environ.Env.read_env(root / ".env")

DEVELOPMENT = 'dev' in env('ENVIRONMENT')

#################
#               #
#   Locations   #
#               #
#################

# Storage paths
STATIC_ROOT = env('STATIC_ROOT', default=root / 'data/static')
MEDIA_ROOT = env('MEDIA_ROOT', default=root / 'data/media')
DATA_DIR = Path(env('DATA_DIR'))

# URLs
STATIC_URL = '/static/'
MEDIA_URL = '/media/'

X_FRAME_OPTIONS = 'SAMEORIGIN'

##################
#                #
#   APP CONFIG   #
#                #
##################

INSTALLED_APPS = [
    'ojpp_core',
    'ojpp_common',
    'ojpp_beacons',
    'adapter_ijpp',
    'adapter_lpp',
    'adapter_arriva',
    'adapter_marprom',
    'adapter_nap',
    #'adapter_piran',
    'exporter_gtfs',

    'import_export',

    'jazzmin',
    'debug_toolbar',
    'colorfield',

    'rangefilter',  # django-jazzmin-admin-rangefilter

    'django_prometheus',

    'django.contrib.postgres',
    'psqlextra',
    'leaflet',
    'leaflet_admin_list',
    'djgeojson',

    'ajax_datatable',

    'ckeditor',
    'dynamic_preferences',

    'sorl.thumbnail',
    'galleryfield',

    'computedfields',

    'shouty',

    # 'django_apscheduler',

    'django_filters',

    'rest_framework',
    'rest_framework.authtoken',

    'corsheaders',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_prometheus.middleware.PrometheusAfterMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'debug': env('DEBUG'),

            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

ROOT_URLCONF = 'ojpp_core.urls'
WSGI_APPLICATION = 'ojpp_core.wsgi.application'

#######################
#                     #
#   INSTANCE CONFIG   #
#                     #
#######################

# Database
DATABASES = {
    "default": {
        "ENGINE": "psqlextra.backend",
        "HOST": env("POSTGRES_HOST"),
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
    },
}

# Cache
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': env('REDIS_URL'),
    }
}

# Misc
SECRET_KEY = env("SECRET_KEY", default='django-insecure-123456875432123456764322345')
ALLOWED_HOSTS = env("ALLOWED_HOSTS", default=[])
CSRFTRUSTED_ORIGINS = ['*', 'https://*', 'http://*']
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_FOR = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

####################
#                  #
#   LOCALIZATION   #
#                  #
####################

USE_I18N = True
USE_L10N = False

DATE_FORMAT = "j. N Y"
DATETIME_FORMAT = "j. N Y H:i"
TIME_FORMAT = "H:i"

TIME_ZONE = 'Europe/Ljubljana'
USE_TZ = True

#############
#           #
#   DEBUG   #
#           #
#############

DEBUG = env("DEBUG")

INTERNAL_IPS = [
    '127.0.0.1',
] + env("DEBUG_IPS")



#######################
#                     #
#   SORT THIS LATER   #
#                     #
#######################

POSTGRES_EXTRA_DB_BACKEND_BASE = 'django.contrib.gis.db.backends.postgis'

REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if env('SENTRY_DSN') and not DEVELOPMENT:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=env('SENTRY_DSN'),
        integrations=[
            DjangoIntegration(),
        ],
        environment=env('ENVIRONMENT'),
        traces_sample_rate=0,
        send_default_pii=True,
        before_send=sentry_filter,
    )

IJPP_USERNAME, IJPP_PASSWORD = env('IJPP_LOGIN').split(':')
LPP_API_KEY = env('LPP_API_KEY')

CORS_ALLOWED_ORIGINS = [
    'https://dev.vlak.si',
    'http://dev.vlak.si',
    'https://db.ojpp.derp.si',
    'http://db.ojpp.derp.si',
    'http://mestnipromet.cyou',
    'http://127.0.0.1:5501',
    'http://localhost:5501',
]


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

PRINT_DB_QUERIES = False
if PRINT_DB_QUERIES:
    LOGGING['loggers'] = {
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    }

JAZZMIN_SETTINGS = {
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        "ojpp_common.Operator": "fas fa-building",
        "ojpp_common.Route": "fas fa-route",
        "ojpp_common.Trip": "fas fa-road",
        "ojpp_common.Stop": "fas fa-map-marker-alt",
        "ojpp_common.StopLocation": "fas fa-map-marker",
        "ojpp_common.Vehicle": "fas fa-bus-alt",
        "ojpp_common.VehicleModel": "fas fa-bus",
        "ojpp_common.VehicleLocation": "fas fa-location-arrow",
        "ojpp_common.Schedule": "fas fa-calendar",

    },
}
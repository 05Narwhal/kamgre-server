#!/bin/sh

# Collect static files
echo "Collect static files"
python manage.py collectstatic --noinput
#chmod o+r /usr/src/{static,media}

# Apply database migrations
echo "Apply database migrations"
python manage.py migrate

# Start server
echo "Starting server"
exec gunicorn ojpp_core.wsgi:application --bind 0.0.0.0:${PORT:-80} --capture-output

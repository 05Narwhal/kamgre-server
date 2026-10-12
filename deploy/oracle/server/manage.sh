#!/usr/bin/env bash
# prestop-manage <command> [args]: any Django manage.py command, as the prestop user with production settings.
#   sudo prestop-manage createsuperuser
#   sudo prestop-manage import_gtfs
set -euo pipefail
exec runuser -u prestop -- bash -c 'set -a; . /etc/prestop/prestop.env; set +a; cd /opt/prestop/app; exec /opt/prestop/venv/bin/python manage.py "$@"' prestop-manage "$@"

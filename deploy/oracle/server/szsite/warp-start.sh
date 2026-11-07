#!/usr/bin/env bash
# Inside the prestop-warp container: an anonymous registration (first start only), proxy mode on
# 127.0.0.1:40000, then stay in the foreground with warp-svc.
set -euo pipefail
warp-svc &
svc=$!
w() { warp-cli --accept-tos "$@"; }
for _ in $(seq 30); do w status >/dev/null 2>&1 && break; sleep 1; done
w registration show >/dev/null 2>&1 || w registration new
w mode proxy
w proxy port 40000
w connect
# The proxy listens on this container's own loopback; socat hands it to the port docker publishes on the VM's
# 127.0.0.1:40000 (the container has its own network namespace, see systemd/prestop-szsite-warp.service).
socat TCP-LISTEN:40001,fork,reuseaddr TCP:127.0.0.1:40000 &
wait "$svc"

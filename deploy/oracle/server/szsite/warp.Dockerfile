# Anonymous Cloudflare WARP in local proxy mode, from Cloudflare's own packages (arm64 + amd64).
# Built on the VM by server/szsite.sh as prestop-warp:local; run by systemd/prestop-szsite-warp.service.
FROM ubuntu:24.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg socat \
 && curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor -o /usr/share/keyrings/cloudflare-warp.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp.gpg] https://pkg.cloudflareclient.com/ noble main" \
      > /etc/apt/sources.list.d/cloudflare-client.list \
 && apt-get update && apt-get install -y --no-install-recommends cloudflare-warp \
 && rm -rf /var/lib/apt/lists/*
COPY warp-start.sh /warp-start.sh
CMD ["bash", "/warp-start.sh"]

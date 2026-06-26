# Sandbox image for the node-22-web environment. `npm test` / `npm` are built into the base; SAST is
# the generic Semgrep image. Writable HOME/npm cache for the non-root --user run.
FROM node:22-alpine

# Corporate root CA (see go.Dockerfile): trust it BEFORE any npm restore. Safe no-op when no cert is
# staged (dir present via certs/.gitkeep).
COPY certs/ /usr/local/share/ca-certificates/
RUN command -v update-ca-certificates >/dev/null && update-ca-certificates || true

# Mount point for the PERSISTENT package-cache volume (cache_volume in environments.py). Created
# world-writable so the fresh named volume seeds those perms — else the non-root --user run hits
# EPERM on the root-owned empty volume. The volume is RW only on the network-ON restore phase.
RUN mkdir -p /cache && chmod 0777 /cache

# NODE_EXTRA_CA_CERTS points node/npm at the system store (npm uses its own CA handling otherwise).
ENV HOME=/tmp \
    npm_config_cache=/tmp/.npm \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

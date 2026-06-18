# Sandbox image for the go-*-cli environments. `go test ./...` is built into the base; SAST is the
# generic Semgrep image. Only writable cache/HOME is baked so the non-root --user run never hits
# `mkdir /.cache: permission denied`.
FROM golang:1.23-alpine

# Corporate root CA: behind a TLS-intercepting proxy the container trust store lacks the corp root,
# so any HTTPS fetch (go install / go mod download) fails `x509: certificate signed by unknown
# authority`. Stage it in BEFORE any network step. Copying the directory (always present via
# certs/.gitkeep) makes this a safe no-op when no cert is staged — the build never breaks.
COPY certs/ /usr/local/share/ca-certificates/
RUN command -v update-ca-certificates >/dev/null && update-ca-certificates || true

# Mount point for the PERSISTENT package-cache volume (cache_volume in environments.py). Created
# world-writable so the fresh named volume seeds those perms — else the non-root --user run hits
# EPERM on the root-owned empty volume. The volume is RW only on the network-ON restore phase.
RUN mkdir -p /cache && chmod 0777 /cache

# goimports powers the post-QA format pass (format_cmd): it removes unused imports — a HARD compile
# error in Go — so generated tests clear the compile gate without a Reviewer bounce. Install it onto
# the system PATH (runtime GOPATH=/tmp/go is an ephemeral tmpfs, so a $GOPATH/bin install would
# vanish). With the corp CA trusted above this fetch succeeds. Pin to the last x/tools release that
# builds on this base's Go (newer `@latest` requires a toolchain upgrade; GOTOOLCHAIN=local forbids
# it). Bump this in lockstep with the base `golang:` tag. Kept NON-FATAL so a future proxy/CA/version
# hiccup can't break the image build (build_sandbox_images.sh runs `set -e`) — format_cmd falls back
# to the always-present `gofmt` when goimports is absent.
RUN GOPATH=/root/go GOBIN=/usr/local/bin go install golang.org/x/tools/cmd/goimports@v0.28.0 \
    && rm -rf /root/go \
    || echo "WARN: goimports unavailable at build (offline/proxy/version) — format pass falls back to gofmt"

ENV HOME=/tmp \
    GOCACHE=/tmp/.cache/go-build \
    GOPATH=/tmp/go \
    GOMODCACHE=/tmp/go/pkg/mod

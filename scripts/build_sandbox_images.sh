#!/usr/bin/env bash
# Build the per-environment sandbox images and pull the generic Semgrep SAST image.
# One-time (or after a Dockerfile change) prerequisite for the runtime validation gates.
# Run inside the WSL2 Ubuntu shell where the docker-ce engine lives (see docs/guides/docker-on-windows.md).
#
# Image tags MUST match SUPPORTED_ENVIRONMENTS[...]["image"] in src/shared/core/environments.py.
set -euo pipefail

TAG="${SDLC_SANDBOX_TAG:-latest}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="$HERE/docker"

# Stage the corporate root CA into the build context so each image trusts the TLS-intercepting proxy
# (lets `go install` / dependency restores succeed at build time). The cert is gitignored — provisioned
# from the host here. Override the source path with CORP_CA_PATH. Absent → warn and continue: the
# Dockerfiles COPY the (always-present) certs/ dir, so update-ca-certificates is just a no-op.
CORP_CA_PATH="${CORP_CA_PATH:-/usr/local/share/ca-certificates/corporate/company_root.crt}"
mkdir -p "$DOCKER_DIR/certs"
if [ -f "$CORP_CA_PATH" ]; then
  # `install` overwrites and forces a writable+world-readable mode — the host source is often
  # root-owned read-only (r-xr-xr-x), which a plain `cp` cannot overwrite on a re-run.
  install -m 0644 "$CORP_CA_PATH" "$DOCKER_DIR/certs/company_root.crt"
  echo "🔐 Staged corporate CA from $CORP_CA_PATH into the build context."
else
  echo "⚠️  No corporate CA at $CORP_CA_PATH — building without it (set CORP_CA_PATH to override)."
fi

# env-key -> Dockerfile (one image per language; multiple env_ids may share a language image).
declare -A IMAGES=(
  ["sdlc-sandbox/python"]="python.Dockerfile"
  ["sdlc-sandbox/go"]="go.Dockerfile"
  ["sdlc-sandbox/node"]="node.Dockerfile"
  ["sdlc-sandbox/dotnet"]="dotnet.Dockerfile"
)

for name in "${!IMAGES[@]}"; do
  dockerfile="${IMAGES[$name]}"
  echo "🐳 Building ${name}:${TAG} from docker/${dockerfile}"
  docker build -t "${name}:${TAG}" -f "${DOCKER_DIR}/${dockerfile}" "${DOCKER_DIR}"
done

# Generic SAST scanner (one tool for every language) with rules VENDORED for fully-offline scans.
# Tag must match SAST_IMAGE in src/shared/core/environments.py.
echo "🐳 Building sdlc-sandbox/semgrep:${TAG} from docker/semgrep.Dockerfile (vendored rules, offline)"
docker build -t "sdlc-sandbox/semgrep:${TAG}" -f "${DOCKER_DIR}/semgrep.Dockerfile" "${DOCKER_DIR}"

echo "✅ Sandbox images ready."

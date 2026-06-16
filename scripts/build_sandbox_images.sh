#!/usr/bin/env bash
# Build the per-environment sandbox images and pull the generic Semgrep SAST image.
# One-time (or after a Dockerfile change) prerequisite for the runtime validation gates.
# Run inside the WSL2 Ubuntu shell where the docker-ce engine lives (see docs/docker-on-windows.md).
#
# Image tags MUST match SUPPORTED_ENVIRONMENTS[...]["image"] in src/shared/core/environments.py.
set -euo pipefail

TAG="${SDLC_SANDBOX_TAG:-latest}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="$HERE/docker"

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

# Generic SAST scanner (one tool for every language). Keep the pin in sync with environments.py.
SEMGREP_IMAGE="${SDLC_SEMGREP_IMAGE:-semgrep/semgrep:1.92.0}"
echo "🐳 Pulling generic SAST image ${SEMGREP_IMAGE}"
docker pull "${SEMGREP_IMAGE}"

echo "✅ Sandbox images ready."

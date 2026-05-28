FROM python:3.11-slim

# Tools the orchestrator shells out to: Node + Claude CLI, docker CLI (inner QA gate), git, bandit (pip)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates git docker.io \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Framework code is baked in and owned by root -> read-only for the unprivileged app user.
COPY src/ ./src/
COPY orchestrator.py .

RUN useradd -m appuser \
    && mkdir -p artifacts \
    && chown -R appuser:appuser artifacts

ENV RUNTIME_ENV=docker
USER appuser

ENTRYPOINT ["python3", "orchestrator.py"]

# --- Run (host with Docker daemon) ---------------------------------------------------------
# The inner QA gate spawns sibling containers on the HOST daemon (Docker-out-of-Docker), so:
#   1. Mount the docker socket.
#   2. Bind the project at a HOST-MATCHING absolute path so the gate's `-v <abs>:...` paths
#      resolve on the host daemon (DooD path translation).
#   3. Provide both API keys (Claude CLI runs non-interactively via ANTHROPIC_API_KEY).
#
#   docker run --rm \
#     -e GEMINI_API_KEY -e ANTHROPIC_API_KEY \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     -v "$PWD":"$PWD" -w "$PWD" \
#     <image>

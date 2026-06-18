# Generic SAST image: Semgrep with rules VENDORED at build time so the gate runs fully OFFLINE
# (--network none). Stock `semgrep/semgrep` + `--config auto` calls semgrep.dev at runtime, which
# fails behind a corporate TLS proxy (the container's CA store lacks the corporate CA). Building here
# goes through the WSL/daemon trust store (which DOES have the CA), so the clone succeeds; at runtime
# no network is needed at all.
FROM semgrep/semgrep:1.92.0

# Pin the ruleset for reproducibility. NOTE: the semgrep-rules repo is versioned SEPARATELY from the
# Semgrep CLI — it carries NO release tags (only branches), so a CLI-style `v1.92.0` tag does not
# exist there. We pin a specific commit SHA on the stable `release` branch and fetch it directly
# (GitHub serves a commit by SHA), which is fully reproducible without depending on a moving branch.
# To bump: pick a newer commit from https://github.com/semgrep/semgrep-rules/commits/release
ARG SEMGREP_RULES_REF=818d4cce153d8e01a29af96572597296cca51bb7
RUN (command -v git >/dev/null 2>&1 || (apk add --no-cache git 2>/dev/null || (apt-get update && apt-get install -y --no-install-recommends git))) \
    && mkdir -p /tmp/semgrep-rules \
    && cd /tmp/semgrep-rules \
    && git init -q \
    && git remote add origin https://github.com/semgrep/semgrep-rules \
    && git fetch -q --depth 1 origin "${SEMGREP_RULES_REF}" \
    && git checkout -q FETCH_HEAD \
    && mkdir -p /opt/semgrep-rules \
    && for d in python go javascript typescript csharp generic; do \
         if [ -d "/tmp/semgrep-rules/$d" ]; then cp -r "/tmp/semgrep-rules/$d" /opt/semgrep-rules/; fi; \
       done \
    && rm -rf /tmp/semgrep-rules

# Run as the calling (non-root) user; rules live read-only in the image.

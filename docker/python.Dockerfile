# Sandbox image for the python-*-core environments: stock slim + the test runner the gate needs.
# SAST is handled generically by the separate Semgrep image, so no bandit here.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest
# Writable HOME/cache for the non-root --user the adapter runs as (avoids mkdir /.cache EPERM).
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/.cache

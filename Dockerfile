# syntax=docker/dockerfile:1.7
#
# Dependencies are fetched in stages that see only the hashed lock files and
# download wheels only, so no package code runs while the network is on. Every
# later step that installs, tests or runs code has no network (SPEC §11, K43).
#
#   docker build -t kervan-search .                 # the service
#   docker build --target test -t kervan-search:test .   # runs the test suite offline

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

FROM base AS deps
COPY requirements.txt /lock/
RUN pip download --only-binary=:all: --no-deps -r /lock/requirements.txt -d /wheels

FROM base AS deps-dev
COPY requirements-dev.txt /lock/
RUN pip download --only-binary=:all: --no-deps -r /lock/requirements-dev.txt -d /wheels

FROM base AS test
RUN --mount=type=bind,from=deps-dev,source=/wheels,target=/wheels \
    --mount=type=bind,source=requirements-dev.txt,target=/lock/requirements-dev.txt \
    --network=none \
    pip install --no-index --find-links /wheels -r /lock/requirements-dev.txt
WORKDIR /app
COPY . .
RUN --network=none python -m pytest -q -p no:cacheprovider

FROM base AS runtime
RUN --mount=type=bind,from=deps,source=/wheels,target=/wheels \
    --mount=type=bind,source=requirements.txt,target=/lock/requirements.txt \
    --network=none \
    pip install --no-index --find-links /wheels -r /lock/requirements.txt
RUN --network=none useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin kervan \
 && install -d -o kervan -g kervan /var/log/kervan
WORKDIR /app
COPY src ./src
COPY data ./data
RUN --network=none python -m compileall -q src
ENV PYTHONPATH=/app/src \
    PORT=8001
USER kervan
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8001'), timeout=2)"]
# Runs uvicorn on 0.0.0.0:$PORT with JSON-lines logs (see src/kervan_search/__main__.py).
CMD ["python", "-m", "kervan_search"]

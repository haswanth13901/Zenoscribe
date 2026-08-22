# Two usable build targets - see docker-compose.prod.yml and
# docker-compose.yml for which each one uses:
#
#   backend                (default target) Lean backend-only image, no
#                           frontend/dist/ baked in. What production uses
#                           (docker-compose.prod.yml's `web`) - the frontend
#                           is built and served by its own container instead
#                           (frontend/Dockerfile, nginx; see Caddyfile for
#                           how the two are routed behind the same TLS
#                           edge). Also what a bare `docker build .` and CI's
#                           docker-build job produce, since it's the default
#                           when no --target is given.
#   backend-with-frontend  Same backend, plus frontend/dist/ baked in, so
#                           voice_transcriber/server.py's SERVE_FRONTEND
#                           check is true and page-serving routes/the
#                           /static mount register too. Only
#                           docker-compose.yml (local Docker dev parity)
#                           uses this, via `target: backend-with-frontend`.

# ---- Stage: build the React SPA (frontend/) - only feeds the
# backend-with-frontend target below ----
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage: install production Python deps ----
# Build tools (build-essential/libssl-dev) live only in this stage, not the
# final image - requirements.txt is the production-only dependency set (see
# that file), which mostly has prebuilt wheels, but this stage stays in
# place as a safety net for any transitive dep that doesn't.
FROM python:3.12-slim AS python-deps
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ---- Stage: common base for both backend targets below ----
FROM python:3.12-slim AS app-base

# python:3.12-slim's own baked-in OS packages lag Debian's security repo -
# CI's Trivy scan (docker-build job) failed on CVEs in util-linux/bsdutils
# (already-patched HIGH-severity issues) that were sitting in the base
# image untouched, not in anything requirements.txt pulls in. Pull the
# latest security patches for whatever's already installed rather than
# adding new packages.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Non-root: runs as an unprivileged user rather than the container default
# (root). RECORDINGS.mkdir() runs at import time (config.py), so the
# recordings dir and everything else under /app need to be owned by this
# user before CMD ever runs.
RUN groupadd --system app && useradd --system --gid app --home /app app

COPY --from=python-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . /app

# ---- Stage: backend-with-frontend (dev-parity only, see header comment) ----
FROM app-base AS backend-with-frontend

COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Created here (not left to config.py's RECORDINGS.mkdir() at import time)
# so the directory exists, owned by `app`, before any volume ever mounts
# over it: Docker initializes a named volume's first mount from whatever
# already exists at that path in the image, ownership included. Skip this
# and a fresh `zenoscribe-recordings`/`zenoscribe-recordings-prod` volume
# would mount in root-owned, and the non-root app user couldn't write to it.
RUN mkdir -p /app/voice_transcriber/recordings && chown -R app:app /app
USER app

EXPOSE 8000

# Shell form (not exec-array form) so $PORT is expanded at container start -
# PaaS hosts (Render/Railway/Heroku-style) inject PORT and require the app
# to bind to it; fixed-port hosts (VPS, Fly.io) get the 8000 default.
#
# --workers 1 is pinned explicitly, not left to uvicorn's default: raising
# it would give each worker process its own SERVER_BOOT_ID (auth.py), so
# users get bounced between workers with random 401s, and each worker would
# run `alembic upgrade head` concurrently against the same database on
# startup (db.init()). Scale this app vertically or run --workers 1 per
# container behind a load balancer instead - see the README's "Production"
# section.
#
# --proxy-headers --forwarded-allow-ips="*" trusts X-Forwarded-* from
# whatever calls this process directly. Safe here because in every shipped
# deployment (docker-compose.prod.yml + Caddyfile) that's always Caddy on
# the private Compose network - port 8000 is never published to the host
# (see docker-compose.prod.yml's `expose:`) - so nothing else can spoof
# these headers. Without this, every row in `failed_logins` (auth
# forensics) and every rate-limit bucket (rate_limit.py) key off Caddy's IP
# instead of the real client's.
CMD uvicorn voice_transcriber.server:app --host 0.0.0.0 --port ${PORT:-8000} \
    --workers 1 --proxy-headers --forwarded-allow-ips="*"

# ---- Stage: backend (production, default target - see header comment) ----
FROM app-base AS backend

RUN mkdir -p /app/voice_transcriber/recordings && chown -R app:app /app
USER app

EXPOSE 8000

CMD uvicorn voice_transcriber.server:app --host 0.0.0.0 --port ${PORT:-8000} \
    --workers 1 --proxy-headers --forwarded-allow-ips="*"

# Frontend + edge image: builds the SPA and serves it with nginx, which
# also now does TLS termination and routing (see nginx.conf). Used by
# docker-compose.prod.yml's `nginx` service; the backend has its own image
# (../Dockerfile) and only ever handles /api, /ws, /ws/translate and
# /healthz - see nginx.conf for how the two are routed behind the same TLS
# edge. Build context for this Dockerfile is the repo root (not
# frontend/), same as the backend, so both share one .dockerignore - see
# docker-compose.prod.yml's `nginx.build`.

# ---- Stage 1: build the SPA ----
FROM node:20-slim AS build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage: dev - Vite dev server with hot reload, used only by
# docker-compose.yml's `frontend` service (local Docker dev parity, the
# containerized equivalent of README's "two-terminal" workflow's `npm
# --prefix frontend run dev`). Not used by production or by Stage 2 below -
# entirely independent of the `build` stage above, since dev serves
# frontend/src/ live rather than a compiled dist/. ----
FROM node:20-slim AS dev
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
EXPOSE 8000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---- Stage 2: serve it ----
FROM nginx:1.31-alpine

# nginx:1.27-alpine's own baked-in Alpine packages lag its security repo -
# CI's Trivy scan (docker-build job) found dozens of already-patched
# CRITICAL/HIGH CVEs (libssl3/libcrypto3 among them) sitting in the base
# image untouched. Pull the latest security patches for whatever's already
# installed rather than adding new packages.
RUN apk update && apk upgrade --no-cache

# nginx's own default.conf (a generic try_files SPA config) doesn't match
# this app's actual routing - see nginx.conf's own comments for why a
# blanket SPA fallback isn't used here.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80

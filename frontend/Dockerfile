# Frontend-only image: builds the SPA and serves it with nginx. Used by
# docker-compose.prod.yml's `frontend` service; the backend has its own
# image (../Dockerfile) and only ever handles /api, /ws, /ws/translate and
# /healthz - see ../Caddyfile for how the two are routed behind the same
# TLS edge. Build context for this Dockerfile is the repo root (not
# frontend/), same as the backend, so both share one .dockerignore - see
# docker-compose.prod.yml's `frontend.build`.

# ---- Stage 1: build the SPA ----
FROM node:20-slim AS build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: serve it ----
FROM nginx:1.27-alpine

# nginx's own default.conf (a generic try_files SPA config) doesn't match
# this app's actual routing - see nginx.conf's own comments for why a
# blanket SPA fallback isn't used here.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80

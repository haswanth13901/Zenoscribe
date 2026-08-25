#!/usr/bin/env bash
set -euo pipefail

# One-time first-boot bootstrap for the nginx + certbot TLS setup
# (docker-compose.prod.yml's `nginx`/`certbot` services). Solves the
# chicken-and-egg problem: nginx's port-443 server block needs a
# certificate file to exist just to start, but certbot can only obtain a
# real one by having nginx already serving the ACME HTTP-01 challenge on
# port 80. This script breaks that loop: dummy self-signed cert -> start
# nginx -> real certbot cert -> reload nginx.
#
# Run once, from the repo root, before the very first
# `docker compose -f docker-compose.prod.yml up -d`:
#     ./scripts/init-letsencrypt.sh
#
# After this runs successfully, the `certbot` service's own renew loop
# (see docker-compose.prod.yml) keeps the certificate current on its own -
# this script is not part of routine deploys.
#
# Set STAGING=1 to use Let's Encrypt's staging environment instead (much
# higher rate limits, but the browser will show an untrusted cert) - useful
# for debugging DOMAIN/nginx.conf mistakes before spending your real
# production rate-limit budget (5 certs per domain per week).

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"

if [ ! -f .env.production ]; then
    echo "[init-letsencrypt] .env.production not found - copy .env.production.example and fill it in first."
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env.production
set +a

if [ -z "${DOMAIN:-}" ] || [ "$DOMAIN" = "your-domain.example.com" ]; then
    echo "[init-letsencrypt] DOMAIN is unset or still the placeholder in .env.production - set it to your real domain."
    exit 1
fi

if [ -z "${CERTBOT_EMAIL:-}" ]; then
    echo "[init-letsencrypt] CERTBOT_EMAIL is unset in .env.production - Let's Encrypt needs it for expiry/registration notices."
    exit 1
fi

if ! grep -q "$DOMAIN" frontend/nginx.conf; then
    echo "[init-letsencrypt] '$DOMAIN' not found in frontend/nginx.conf - edit its server_name/ssl_certificate lines to match .env.production's DOMAIN first (this repo hand-edits the domain there, the same way the old Caddyfile worked - see frontend/nginx.conf's own header comment)."
    exit 1
fi

echo "[init-letsencrypt] Writing a dummy self-signed cert so nginx has something to bind to at first start..."
$COMPOSE run --rm --entrypoint "sh -c \"mkdir -p /etc/letsencrypt/live/$DOMAIN && \
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
    -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
    -subj /CN=localhost\"" certbot

echo "[init-letsencrypt] Starting nginx on the dummy cert..."
$COMPOSE up -d nginx

echo "[init-letsencrypt] Deleting the dummy cert so certbot doesn't refuse to overwrite it..."
$COMPOSE run --rm --entrypoint "sh -c \"rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf\"" certbot

STAGING_ARG=""
if [ "${STAGING:-0}" = "1" ]; then
    echo "[init-letsencrypt] STAGING=1 - requesting a staging (untrusted) certificate."
    STAGING_ARG="--staging"
fi

echo "[init-letsencrypt] Requesting the real certificate from Let's Encrypt..."
$COMPOSE run --rm certbot certonly --webroot -w /var/www/certbot \
  $STAGING_ARG \
  --email "$CERTBOT_EMAIL" -d "$DOMAIN" \
  --rsa-key-size 4096 --agree-tos --no-eff-email

echo "[init-letsencrypt] Reloading nginx to pick up the real certificate..."
$COMPOSE exec nginx nginx -s reload

echo "[init-letsencrypt] Done. Bring up the rest of the stack with: docker compose -f docker-compose.prod.yml --env-file .env.production up -d"

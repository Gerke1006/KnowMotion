#!/bin/sh
# Certbot invokes this only after successfully renewing a certificate.
set -eu
cd /opt/knowmotion
/usr/bin/docker compose -f docker-compose.production.yml exec -T web nginx -t
/usr/bin/docker compose -f docker-compose.production.yml exec -T web nginx -s reload

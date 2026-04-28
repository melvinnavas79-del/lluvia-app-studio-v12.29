#!/usr/bin/env bash
# ============================================================================
# Lluvia App Studio - infra-init.sh
# Se ejecuta UNA VEZ en el VPS para preparar el reverse-proxy global.
# Despues, cada cliente se levanta con setup-cliente.sh.
# ============================================================================

set -e

LLUVIA_HOME="${LLUVIA_HOME:-/opt/lluvia}"
ROOT_DOMAIN="${LLUVIA_ROOT_DOMAIN:-lluvia.app}"
ADMIN_EMAIL="${LLUVIA_ADMIN_EMAIL:-melvinnavas79@gmail.com}"

mkdir -p "$LLUVIA_HOME/caddy/sites" "$LLUVIA_HOME/caddy/data" "$LLUVIA_HOME/caddy/config" "$LLUVIA_HOME/clients"

# Caddyfile global - importa cualquier *.caddy de sites/
cat > "$LLUVIA_HOME/caddy/Caddyfile" <<EOF
{
    email ${ADMIN_EMAIL}
    admin off
}

import sites/*.caddy
EOF

# Stack global de Caddy
cat > "$LLUVIA_HOME/caddy/docker-compose.yml" <<'EOF'
version: "3.9"
services:
  caddy:
    image: caddy:2-alpine
    container_name: lluvia_caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./sites:/etc/caddy/sites:ro
      - ./data:/data
      - ./config:/config
    networks:
      - web

networks:
  web:
    name: lluvia_proxy
EOF

cd "$LLUVIA_HOME/caddy"
docker compose up -d

cat <<EOF

  Reverse-proxy global de Lluvia App Studio listo.

  Caddy escuchando en :80 / :443 con SSL automatico (Let's Encrypt).
  Carpeta de sitios: $LLUVIA_HOME/caddy/sites/
  Cada cliente nuevo agrega un .caddy alli.

  PROXIMO PASO:
    Apunta tu DNS *.${ROOT_DOMAIN} (wildcard) hacia este VPS.
    Despues ejecuta:  ./setup-cliente.sh

EOF

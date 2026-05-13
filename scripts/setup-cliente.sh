#!/usr/bin/env bash
# ============================================================================
# Lluvia App Studio - setup-cliente.sh
# Despliegue automatizado de copias del bot.
#
# MODOS:
#   Interactivo (default): te pregunta los datos uno a uno
#   No interactivo:        LLUVIA_NI=1 + env vars con cada campo
#   Dry-run:               LLUVIA_DRY_RUN=1 (no levanta Docker, solo genera files)
#                          util para entornos sin Docker / preview / pruebas
# ============================================================================

set -e

# ----- Paths -----
LLUVIA_HOME="${LLUVIA_HOME:-/opt/lluvia}"
SOURCE_DIR="${LLUVIA_SOURCE:-$LLUVIA_HOME/source}"
CLIENTS_DIR="$LLUVIA_HOME/clients"
TEMPLATES_DIR="${LLUVIA_TEMPLATES:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/templates}"
CADDY_CONF_DIR="${CADDY_CONF_DIR:-$LLUVIA_HOME/caddy/sites}"

# Defaults
DEFAULT_OPENAI_KEY="${LLUVIA_DEFAULT_OPENAI:-}"
DEFAULT_ROOT_DOMAIN="${LLUVIA_ROOT_DOMAIN:-lluvia.app}"
DRY_RUN="${LLUVIA_DRY_RUN:-0}"
NI="${LLUVIA_NI:-0}"

# ----- Util -----
GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'; NC=$'\033[0m'
log()  { echo "[lluvia] $*"; }
ok()   { echo "[ ok ] $*"; }
warn() { echo "[warn] $*" >&2; }
err()  { echo "[ err] $*" >&2; exit 1; }

ask() {
    local prompt="$1" default="$2" var
    if [ "$NI" = "1" ]; then echo "${default}"; return; fi
    if [ -n "$default" ]; then read -rp "$prompt [$default]: " var; echo "${var:-$default}"
    else read -rp "$prompt: " var; echo "$var"; fi
}
ask_secret() {
    if [ "$NI" = "1" ]; then echo ""; return; fi
    local prompt="$1" var; read -rsp "$prompt: " var; echo >&2; echo "$var"
}
slug_from() {
    # Quita comillas, trim, lowercase, no alfa numericos -> guion, recorta
    echo "$1" | sed -E 's/^["'"'"' ]+|["'"'"' ]+$//g' \
              | tr '[:upper:]' '[:lower:]' \
              | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
              | cut -c1-30
}
valid_hex() { [[ "$1" =~ ^#[0-9a-fA-F]{6}$ ]]; }

# Flag para idempotencia: LLUVIA_FORCE=1 borra el directorio del cliente si ya existe
FORCE="${LLUVIA_FORCE:-0}"

# ----- Pre-checks -----
[ -d "$SOURCE_DIR/backend" ] || err "No encontrado $SOURCE_DIR/backend (define LLUVIA_SOURCE)"
[ -d "$SOURCE_DIR/frontend" ] || err "No encontrado $SOURCE_DIR/frontend"
if [ "$DRY_RUN" != "1" ]; then
    command -v docker >/dev/null || err "Docker no disponible (usa LLUVIA_DRY_RUN=1 para preview)"
    docker compose version >/dev/null 2>&1 || err "Docker Compose v2 no disponible"
fi

# ----- Inputs -----
CLIENT_DISPLAY="${LLUVIA_DISPLAY:-$(ask 'Nombre del cliente (display)' '')}"
[ -z "$CLIENT_DISPLAY" ] && err "Nombre del cliente vacio"

SLUG="${LLUVIA_SLUG:-$(ask 'Slug del cliente (lowercase, sin espacios)' "$(slug_from "$CLIENT_DISPLAY")")}"
[ -z "$SLUG" ] && err "Slug invalido"

ROOT_DOMAIN="${LLUVIA_ROOT_DOMAIN_OVERRIDE:-$(ask 'Dominio raiz' "$DEFAULT_ROOT_DOMAIN")}"
PUBLIC_URL="https://${SLUG}.${ROOT_DOMAIN}"

PRODUCT_NAME="${LLUVIA_PRODUCT:-$(ask 'Nombre del producto que ve el cliente' "$CLIENT_DISPLAY")}"
TAGLINE="${LLUVIA_TAGLINE:-$(ask 'Tagline / frase corta' 'Tu agencia inteligente de bots e IA')}"
LOGO_URL="${LLUVIA_LOGO:-$(ask 'URL del logo (https://...) opcional' '')}"
PRIMARY="${LLUVIA_PRIMARY:-$(ask 'Color primario (#RRGGBB)' '#5fb4ff')}"
ACCENT="${LLUVIA_ACCENT:-$(ask 'Color de acento (#RRGGBB)' '#5fdbc4')}"
BG="${LLUVIA_BG:-$(ask 'Color de fondo (#RRGGBB)' '#0a1220')}"
TEXTC="${LLUVIA_TEXTC:-$(ask 'Color de texto (#RRGGBB)' '#e7eef8')}"

valid_hex "$PRIMARY" || err "Color primario invalido"
valid_hex "$ACCENT" || err "Color de acento invalido"
valid_hex "$BG" || err "Color de fondo invalido"
valid_hex "$TEXTC" || err "Color de texto invalido"

ADMIN_EMAIL="${LLUVIA_EMAIL:-$(ask 'Email del admin del cliente' '')}"
[ -z "$ADMIN_EMAIL" ] && err "Email vacio"

ADMIN_PASSWORD="${LLUVIA_PASSWORD:-$(ask_secret 'Password admin (vacio = autogenerar)')}"
if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)
fi

CLIENT_OPENAI="${LLUVIA_OPENAI_CLIENT:-$(ask 'OPENAI_API_KEY del cliente (vacio = usar la tuya)' '')}"
OPENAI_KEY="${CLIENT_OPENAI:-$DEFAULT_OPENAI_KEY}"

TG_TOKEN="${LLUVIA_TG_TOKEN:-$(ask 'Telegram token del cliente (vacio = configurar despues)' '')}"

# ----- Crear estructura -----
CLIENT_DIR="$CLIENTS_DIR/$SLUG"
if [ -d "$CLIENT_DIR" ]; then
    if [ "$FORCE" = "1" ]; then
        warn "Ya existe $CLIENT_DIR, LLUVIA_FORCE=1 -> bajando containers y borrando"
        (cd "$CLIENT_DIR" && docker compose down -v 2>/dev/null || true)
        rm -rf "$CLIENT_DIR"
    else
        err "Ya existe $CLIENT_DIR. Para reinstalar: 'LLUVIA_FORCE=1 bash setup-cliente.sh' o borralo manualmente con 'rm -rf $CLIENT_DIR'"
    fi
fi
mkdir -p "$CLIENT_DIR"
log "Estructura en $CLIENT_DIR"

cp -r "$SOURCE_DIR/backend" "$CLIENT_DIR/backend"
cp -r "$SOURCE_DIR/frontend" "$CLIENT_DIR/frontend"
rm -rf "$CLIENT_DIR/frontend/node_modules" "$CLIENT_DIR/backend/.env" "$CLIENT_DIR/frontend/.env" 2>/dev/null || true

cp "$TEMPLATES_DIR/Dockerfile.backend" "$CLIENT_DIR/backend/Dockerfile"
cp "$TEMPLATES_DIR/Dockerfile.frontend" "$CLIENT_DIR/frontend/Dockerfile"
cp "$TEMPLATES_DIR/nginx.conf" "$CLIENT_DIR/frontend/nginx.conf"

JWT_SECRET=$(openssl rand -hex 32)
VERIFY_TOKEN=$(openssl rand -hex 8)

cat > "$CLIENT_DIR/backend.env" <<EOF
MONGO_URL=mongodb://mongo:27017
DB_NAME=bot_${SLUG}
CORS_ORIGINS=*
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=${OPENAI_KEY}
JWT_SECRET=${JWT_SECRET}
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
VERIFY_TOKEN=${VERIFY_TOKEN}
TELEGRAM_TOKEN=${TG_TOKEN}
GITHUB_TOKEN=
WHATSAPP_TOKEN=
PHONE_ID=
INSTAGRAM_TOKEN=
IG_ID=
ADMIN_TELEGRAM_CHAT_IDS=
EOF

cat > "$CLIENT_DIR/.env" <<EOF
SLUG=${SLUG}
PUBLIC_URL=${PUBLIC_URL}
EOF

sed -e "s|__SLUG__|${SLUG}|g" -e "s|__PUBLIC_URL__|${PUBLIC_URL}|g" \
    "$TEMPLATES_DIR/docker-compose.yml.tmpl" > "$CLIENT_DIR/docker-compose.yml"

# Sanity check: el archivo se genero y NO quedo ningun placeholder
if [ ! -s "$CLIENT_DIR/docker-compose.yml" ]; then
    err "docker-compose.yml no se genero. Revisa $TEMPLATES_DIR/docker-compose.yml.tmpl"
fi
if grep -q "__SLUG__\|__PUBLIC_URL__" "$CLIENT_DIR/docker-compose.yml"; then
    err "Quedaron placeholders sin reemplazar en docker-compose.yml"
fi
ok "docker-compose.yml generado en $CLIENT_DIR"

mkdir -p "$CADDY_CONF_DIR"
sed "s/__SLUG__/${SLUG}/g; s/__ROOT_DOMAIN__/${ROOT_DOMAIN}/g" \
    "$TEMPLATES_DIR/Caddyfile.tmpl" > "$CADDY_CONF_DIR/${SLUG}.caddy"

cat > "$CLIENT_DIR/branding.json" <<EOF
{
  "product_name": "${PRODUCT_NAME}",
  "tagline": "${TAGLINE}",
  "primary_color": "${PRIMARY}",
  "accent_color": "${ACCENT}",
  "background_color": "${BG}",
  "text_color": "${TEXTC}",
  "logo_data_url": "${LOGO_URL}",
  "company_name": "${PRODUCT_NAME}",
  "support_email": "${ADMIN_EMAIL}"
}
EOF

ok "Archivos generados"

# ----- Despliegue -----
if [ "$DRY_RUN" = "1" ]; then
    warn "DRY_RUN activo: NO se levanta Docker ni Caddy. Solo se generaron archivos."
else
    log "docker compose build (puede tardar 3-5 min en la primera vez)"
    cd "$CLIENT_DIR"
    if ! docker compose build 2>&1 | tail -20; then
        err "Build fallo. Revisa 'cd $CLIENT_DIR && docker compose build' a mano."
    fi
    ok "Build completo"

    log "docker compose up -d"
    docker compose up -d || err "docker compose up -d fallo"

    log "Esperando backend (max 60s)..."
    for i in {1..30}; do
        if docker compose exec -T backend curl -fs http://localhost:8001/api/ >/dev/null 2>&1; then
            ok "Backend up (intento $i)"
            break
        fi
        sleep 2
        if [ "$i" = "30" ]; then
            warn "Backend no respondio en 60s. Logs ultimos:"
            docker compose logs backend --tail 30
        fi
    done

    docker ps --format '{{.Names}}' | grep -q '^lluvia_caddy$' && \
        docker exec lluvia_caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || warn "Caddy reload manual requerido"

    sleep 3
    TOKEN=$(curl -fs -X POST "${PUBLIC_URL}/api/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
        2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
    [ -n "$TOKEN" ] && curl -fs -X PUT "${PUBLIC_URL}/api/branding" \
        -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
        --data @"$CLIENT_DIR/branding.json" >/dev/null 2>&1 && ok "Branding aplicado"
fi

# ----- Output JSON (parseable por el bot) -----
cat <<EOF
LLUVIA_RESULT_JSON_BEGIN
{"url":"${PUBLIC_URL}","admin_email":"${ADMIN_EMAIL}","admin_password":"${ADMIN_PASSWORD}","slug":"${SLUG}","product_name":"${PRODUCT_NAME}","client_dir":"${CLIENT_DIR}","dry_run":"${DRY_RUN}"}
LLUVIA_RESULT_JSON_END
EOF

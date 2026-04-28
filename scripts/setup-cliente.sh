#!/usr/bin/env bash
# ============================================================================
# Lluvia App Studio - setup-cliente.sh
# Crea una instancia aislada para un cliente nuevo en menos de 10 minutos.
# Cada cliente tiene su propio MongoDB, backend, frontend, dominio y branding.
# ============================================================================

set -e

# ----- Configuracion del entorno -----
LLUVIA_HOME="${LLUVIA_HOME:-/opt/lluvia}"
SOURCE_DIR="${LLUVIA_SOURCE:-$LLUVIA_HOME/source}"
CLIENTS_DIR="$LLUVIA_HOME/clients"
TEMPLATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/templates"
CADDY_CONF_DIR="${CADDY_CONF_DIR:-$LLUVIA_HOME/caddy/sites}"

# Defaults heredables (puedes exportarlos antes de ejecutar)
DEFAULT_OPENAI_KEY="${LLUVIA_DEFAULT_OPENAI:-}"
DEFAULT_ROOT_DOMAIN="${LLUVIA_ROOT_DOMAIN:-lluvia.app}"

# ----- Utilidades -----
GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'; CYAN=$'\033[0;36m'; NC=$'\033[0m'
log()  { echo -e "${CYAN}[lluvia]${NC} $*"; }
ok()   { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[ err]${NC} $*" >&2; exit 1; }

ask() {
    local prompt="$1" default="$2" var
    if [ -n "$default" ]; then
        read -rp "$prompt [$default]: " var
        echo "${var:-$default}"
    else
        read -rp "$prompt: " var
        echo "$var"
    fi
}

ask_secret() {
    local prompt="$1" var
    read -rsp "$prompt: " var; echo >&2
    echo "$var"
}

slug_from() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-30
}

valid_hex() { [[ "$1" =~ ^#[0-9a-fA-F]{6}$ ]]; }

# ----- Pre-checks -----
[ -d "$SOURCE_DIR/backend" ] || err "No encontrado $SOURCE_DIR/backend. Define LLUVIA_SOURCE o copia el codigo a $SOURCE_DIR"
[ -d "$SOURCE_DIR/frontend" ] || err "No encontrado $SOURCE_DIR/frontend"
command -v docker >/dev/null || err "Docker no esta instalado"
docker compose version >/dev/null 2>&1 || err "Docker Compose v2 no esta disponible"

# ----- Banner -----
cat <<'BANNER'
============================================================
  LLUVIA APP STUDIO - Setup automatico de cliente
  Tiempo objetivo: < 10 minutos
============================================================
BANNER

# ----- Inputs -----
CLIENT_DISPLAY=$(ask "Nombre del cliente (display)" "")
[ -z "$CLIENT_DISPLAY" ] && err "Nombre del cliente vacio"

SLUG=$(ask "Slug del cliente (sin espacios, lowercase)" "$(slug_from "$CLIENT_DISPLAY")")
[ -z "$SLUG" ] && err "Slug invalido"

ROOT_DOMAIN=$(ask "Dominio raiz" "$DEFAULT_ROOT_DOMAIN")
PUBLIC_URL="https://${SLUG}.${ROOT_DOMAIN}"

PRODUCT_NAME=$(ask "Nombre del producto que ve el cliente" "$CLIENT_DISPLAY")
TAGLINE=$(ask "Tagline / frase corta" "Tu agencia inteligente de bots e IA")
LOGO_URL=$(ask "URL del logo (https://... opcional)" "")
PRIMARY=$(ask "Color primario (#RRGGBB)" "#5fb4ff")
ACCENT=$(ask "Color de acento (#RRGGBB)" "#5fdbc4")
BG=$(ask "Color de fondo (#RRGGBB)" "#0a1220")
TEXTC=$(ask "Color de texto (#RRGGBB)" "#e7eef8")

valid_hex "$PRIMARY" || err "Color primario invalido"
valid_hex "$ACCENT" || err "Color de acento invalido"
valid_hex "$BG" || err "Color de fondo invalido"
valid_hex "$TEXTC" || err "Color de texto invalido"

ADMIN_EMAIL=$(ask "Email del admin del cliente" "")
[ -z "$ADMIN_EMAIL" ] && err "Email vacio"
ADMIN_PASSWORD=$(ask_secret "Password del admin (vacio = autogenerar)")
if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)
    ok "Password autogenerada: $ADMIN_PASSWORD"
fi

CLIENT_OPENAI=$(ask "OPENAI_API_KEY del cliente (vacio = usar la tuya por defecto)" "")
OPENAI_KEY="${CLIENT_OPENAI:-$DEFAULT_OPENAI_KEY}"
[ -z "$OPENAI_KEY" ] && warn "Sin OPENAI_API_KEY - el motor IA respondera 'no configurado'. Agrega LLUVIA_DEFAULT_OPENAI o pide la key al cliente despues."

TG_TOKEN=$(ask "Telegram bot token del cliente (vacio = lo agregan despues)" "")

# ----- Crear directorio del cliente -----
CLIENT_DIR="$CLIENTS_DIR/$SLUG"
[ -d "$CLIENT_DIR" ] && err "Ya existe $CLIENT_DIR. Elige otro slug o borra el directorio."
mkdir -p "$CLIENT_DIR"
log "Creando estructura en $CLIENT_DIR"

# Copiar codigo fuente
cp -r "$SOURCE_DIR/backend" "$CLIENT_DIR/backend"
cp -r "$SOURCE_DIR/frontend" "$CLIENT_DIR/frontend"

# Eliminar node_modules y .env del fuente (cada cliente tiene los suyos)
rm -rf "$CLIENT_DIR/frontend/node_modules" "$CLIENT_DIR/backend/.env" "$CLIENT_DIR/frontend/.env"

# Copiar Dockerfiles
cp "$TEMPLATES_DIR/Dockerfile.backend" "$CLIENT_DIR/backend/Dockerfile"
cp "$TEMPLATES_DIR/Dockerfile.frontend" "$CLIENT_DIR/frontend/Dockerfile"
cp "$TEMPLATES_DIR/nginx.conf" "$CLIENT_DIR/frontend/nginx.conf"

# Generar secrets
JWT_SECRET=$(openssl rand -hex 32)
VERIFY_TOKEN=$(openssl rand -hex 8)

# backend.env
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
GITHUB_USER=
WHATSAPP_TOKEN=
PHONE_ID=
INSTAGRAM_TOKEN=
IG_ID=
ADMIN_TELEGRAM_CHAT_IDS=
EOF

# .env del compose
cat > "$CLIENT_DIR/.env" <<EOF
SLUG=${SLUG}
PUBLIC_URL=${PUBLIC_URL}
EOF

# docker-compose.yml
sed "s/__SLUG__/${SLUG}/g" "$TEMPLATES_DIR/docker-compose.yml.tmpl" > "$CLIENT_DIR/docker-compose.yml"

# Caddyfile (sites)
mkdir -p "$CADDY_CONF_DIR"
sed "s/__SLUG__/${SLUG}/g; s/__ROOT_DOMAIN__/${ROOT_DOMAIN}/g" \
    "$TEMPLATES_DIR/Caddyfile.tmpl" > "$CADDY_CONF_DIR/${SLUG}.caddy"

# branding.json (semilla que se aplicara post-startup)
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

ok "Estructura creada"

# ----- Levantar stack -----
log "Construyendo y levantando contenedores (puede tardar 2-3 min la primera vez)"
cd "$CLIENT_DIR"
docker compose up -d --build

log "Esperando que el backend este listo..."
for i in {1..30}; do
    if docker compose exec -T backend curl -fs http://localhost:8001/api/ >/dev/null 2>&1; then
        ok "Backend respondiendo"
        break
    fi
    sleep 2
done

# ----- Reload Caddy -----
if docker ps --format '{{.Names}}' | grep -q '^lluvia_caddy$'; then
    log "Recargando Caddy"
    docker exec lluvia_caddy caddy reload --config /etc/caddy/Caddyfile || warn "No pude recargar Caddy automaticamente"
else
    warn "Container 'lluvia_caddy' no esta corriendo. Asegurate de tener el reverse-proxy global activo."
fi

# ----- Sembrar branding via API -----
log "Aplicando branding del cliente..."
sleep 3
TOKEN=$(curl -fs -X POST "${PUBLIC_URL}/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
    2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])" 2>/dev/null || echo "")

if [ -n "$TOKEN" ]; then
    curl -fs -X PUT "${PUBLIC_URL}/api/branding" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        --data @"$CLIENT_DIR/branding.json" >/dev/null && ok "Branding aplicado" || warn "PUT branding fallo"
else
    warn "No se pudo loguear al admin via dominio publico (DNS aun no propaga?). Aplica el branding manualmente desde el panel."
fi

# ----- Resumen -----
cat <<EOF

${GREEN}============================================================
  CLIENTE DESPLEGADO: ${PRODUCT_NAME}
============================================================${NC}

  URL Panel:    ${PUBLIC_URL}
  Admin Email:  ${ADMIN_EMAIL}
  Admin Pass:   ${ADMIN_PASSWORD}
  Slug:         ${SLUG}
  Directorio:   ${CLIENT_DIR}
  DB:           bot_${SLUG} (aislada en su propio volumen)

  Telegram bot: ${TG_TOKEN:-(no configurado, agregalo en backend.env y reinicia)}
  OpenAI:       ${OPENAI_KEY:0:14}...

${YELLOW}PROXIMOS PASOS PARA EL CLIENTE:${NC}
  1. Manda ${PUBLIC_URL} al cliente
  2. Que entre con ${ADMIN_EMAIL} / la password de arriba
  3. En Branding tab puede subir su logo y ajustar colores
  4. (Opcional) Reemplazar tu OPENAI_API_KEY por la suya en backend.env

${YELLOW}MANTENIMIENTO:${NC}
  cd ${CLIENT_DIR}
  docker compose logs -f          # ver logs
  docker compose restart          # reiniciar
  docker compose down             # detener
  docker compose down -v          # detener y BORRAR datos (cuidado)

EOF

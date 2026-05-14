#!/usr/bin/env bash
# ============================================================
# Lluvia App Studio — Quickstart Master (v11)
# Para Ubuntu 22.04 / 24.04 en VPS limpio
#
# Uso:
#   sudo bash quickstart-master.sh <DOMINIO> <ADMIN_EMAIL>
# Ejemplo:
#   sudo bash quickstart-master.sh lluvia.app melvin@gmail.com
# ============================================================
set -e

DOMAIN="${1:-}"
ADMIN_EMAIL="${2:-}"
LLUVIA_HOME="/opt/lluvia"

if [[ -z "$DOMAIN" || -z "$ADMIN_EMAIL" ]]; then
  echo "Uso: sudo bash quickstart-master.sh <DOMINIO> <ADMIN_EMAIL>"
  echo "Ej:  sudo bash quickstart-master.sh lluvia.app tu@correo.com"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Necesita sudo / root"; exit 1
fi

echo "==> Lluvia App Studio MASTER setup"
echo "    Dominio:  $DOMAIN  (asegurate de tener wildcard DNS *.${DOMAIN} apuntando aqui)"
echo "    Admin:    $ADMIN_EMAIL"
echo "    Carpeta:  $LLUVIA_HOME"
sleep 2

# ----------------- 1. Dependencias base
echo ""
echo "==> [1/6] Instalando Docker + Caddy + utilidades"
apt update
apt install -y curl wget tar git ca-certificates gnupg apt-transport-https debian-keyring debian-archive-keyring

if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version &>/dev/null; then
  apt install -y docker-compose-plugin
fi

if ! command -v caddy &>/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt update && apt install -y caddy
fi

# ----------------- 2. Estructura de carpetas
echo ""
echo "==> [2/6] Estructura $LLUVIA_HOME"
mkdir -p "$LLUVIA_HOME"/{source,clients,backups}
mkdir -p /etc/caddy/Caddyfile.d

# ----------------- 3. Copiar source desde el directorio del tarball
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../source" && pwd)"
if [[ ! -d "$SRC_DIR/backend" ]]; then
  echo "ERROR: no encuentro $SRC_DIR/backend. Descomprimi el tarball antes de ejecutar."
  exit 1
fi
echo ""
echo "==> [3/6] Copiando source desde $SRC_DIR -> $LLUVIA_HOME/source/"
rsync -a "$SRC_DIR/" "$LLUVIA_HOME/source/"

# ----------------- 4. Generar .env del master
ENVF="$LLUVIA_HOME/source/backend/.env"
if [[ ! -f "$ENVF" ]]; then
  JWT="$(openssl rand -hex 32)"
  PASS="$(openssl rand -base64 18 | tr -d '=+/' | head -c 16)"
  cat > "$ENVF" <<EOF
MONGO_URL=mongodb://mongo:27017
DB_NAME=lluvia_admin
CORS_ORIGINS=*
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=PEGA_TU_KEY_AQUI
JWT_SECRET=$JWT
ADMIN_EMAIL=$ADMIN_EMAIL
ADMIN_PASSWORD=$PASS

GITHUB_TOKEN=
GITHUB_USER=
GITHUB_BACKUP_REPO=

TELEGRAM_TOKEN=
TELEGRAM_POLLING=1
ADMIN_TELEGRAM_CHAT_IDS=

PAYPAL_MODE=live
PAYPAL_CLIENT_ID=
PAYPAL_SECRET=
PAYPAL_WEBHOOK_ID=

LLUVIA_HOME=$LLUVIA_HOME
LLUVIA_BASE_DOMAIN=$DOMAIN
LLUVIA_DRY_RUN=0
LLUVIA_SOURCE=$LLUVIA_HOME/source
LLUVIA_TEMPLATES=$LLUVIA_HOME/source/scripts/templates

VERIFY_TOKEN=changeme
WHATSAPP_TOKEN=
PHONE_ID=
INSTAGRAM_TOKEN=
IG_ID=
EOF
  echo ""
  echo "============================================================"
  echo "  ATENCION: editar $ENVF y pegar tus claves antes del compose"
  echo "  ADMIN_EMAIL:    $ADMIN_EMAIL"
  echo "  ADMIN_PASSWORD: $PASS    <-- GUARDAR ESTO"
  echo "============================================================"
fi

# ----------------- 5. Caddy reverse proxy del master
CADDY_MASTER="/etc/caddy/Caddyfile.d/master.conf"
cat > "$CADDY_MASTER" <<EOF
admin.${DOMAIN} {
    encode gzip
    reverse_proxy /api/* localhost:8001
    reverse_proxy localhost:3000
}
EOF
systemctl reload caddy || systemctl restart caddy
echo ""
echo "==> [5/6] Caddy configurado: https://admin.${DOMAIN}"

# ----------------- 6. Docker compose up
COMPOSE="$LLUVIA_HOME/source/docker-compose.yml"
if [[ -f "$COMPOSE" ]]; then
  echo ""
  echo "==> [6/6] Levantando containers (build + up)"
  cd "$LLUVIA_HOME/source"
  docker compose up -d --build
  echo ""
  echo "==> Logs en vivo: docker compose logs -f"
else
  echo ""
  echo "AVISO: no encuentro docker-compose.yml. Levanta los servicios manualmente."
fi

echo ""
echo "============================================================"
echo "  Lluvia App Studio MASTER instalado"
echo "  Panel: https://admin.${DOMAIN}"
echo "  Login: $ADMIN_EMAIL / (ver password mas arriba o en .env)"
echo "  Siguiente paso: editar .env con tus claves OpenAI/PayPal/Telegram"
echo "                  y reiniciar:  docker compose restart backend"
echo "============================================================"

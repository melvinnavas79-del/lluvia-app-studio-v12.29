#!/usr/bin/env bash
# =============================================================================
# Lluvia App Studio - diagnose.sh
# Diagnostico rapido del despliegue. Ejecutar en el VPS cuando algo falle.
#
#   bash diagnose.sh                -> diagnostico de la instalacion completa
#   bash diagnose.sh <slug>         -> + diagnostico del cliente <slug>
# =============================================================================

set +e

SLUG="${1:-}"
LLUVIA_HOME="${LLUVIA_HOME:-/opt/lluvia}"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'; NC=$'\033[0m'
section() { echo; echo "${YELLOW}===== $* =====${NC}"; }
ok()      { echo "${GREEN}[OK]${NC} $*"; }
fail()    { echo "${RED}[FAIL]${NC} $*"; }

section "Sistema"
echo "Hostname: $(hostname)"
echo "Kernel:   $(uname -r)"
echo "RAM:"; free -h
echo "Disco:"; df -h /

section "Docker"
docker --version 2>/dev/null && ok "Docker presente" || fail "Docker NO instalado"
docker compose version 2>/dev/null && ok "Docker Compose v2 OK" || fail "Docker Compose v2 NO disponible"

section "Estructura /opt/lluvia"
for d in "$LLUVIA_HOME" "$LLUVIA_HOME/source" "$LLUVIA_HOME/source/backend" \
         "$LLUVIA_HOME/source/frontend" "$LLUVIA_HOME/source/scripts" \
         "$LLUVIA_HOME/caddy" "$LLUVIA_HOME/clients"; do
    [ -d "$d" ] && ok "$d" || fail "FALTA $d"
done

[ -f "$LLUVIA_HOME/source/backend/.env" ] && ok "backend/.env existe" || fail "backend/.env FALTA"
[ -f "$LLUVIA_HOME/source/backend/requirements-prod.txt" ] && ok "requirements-prod.txt existe" || fail "requirements-prod.txt FALTA"

section "Caddy global"
if docker ps --format '{{.Names}}' | grep -q '^lluvia_caddy$'; then
    ok "Caddy corriendo"
    docker logs lluvia_caddy --tail 5 2>&1 | sed 's/^/  /'
else
    fail "Caddy NO corriendo - re-ejecuta scripts/infra-init.sh"
fi

section "Containers Lluvia"
docker ps --filter "name=lluvia_" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

section "Red lluvia_proxy"
docker network ls | grep lluvia_proxy >/dev/null && ok "Red lluvia_proxy existe" || fail "Red lluvia_proxy FALTA"

if [ -n "$SLUG" ]; then
    section "Cliente: $SLUG"
    CDIR="$LLUVIA_HOME/clients/$SLUG"
    if [ ! -d "$CDIR" ]; then
        fail "No existe $CDIR - corre setup-cliente.sh primero"
        exit 1
    fi
    ok "Directorio $CDIR"
    [ -f "$CDIR/docker-compose.yml" ] && ok "docker-compose.yml" || fail "docker-compose.yml FALTA"
    [ -f "$CDIR/backend.env" ] && ok "backend.env" || fail "backend.env FALTA"

    cd "$CDIR"

    section "Estado de containers del cliente $SLUG"
    docker compose ps

    section "Logs backend (ultimos 40)"
    docker compose logs backend --tail 40 2>&1 | sed 's/^/  /'

    section "Logs frontend (ultimos 20)"
    docker compose logs frontend --tail 20 2>&1 | sed 's/^/  /'

    section "Test interno backend"
    if docker compose exec -T backend curl -fs http://localhost:8001/api/ 2>&1; then
        ok "Backend responde en :8001"
    else
        fail "Backend NO responde en :8001 (esto es la causa de Connection Refused)"
    fi

    section "Test desde Caddy (red lluvia_proxy)"
    if docker exec lluvia_caddy wget -qO- "http://lluvia_${SLUG}_backend:8001/api/" 2>&1 | head -2; then
        ok "Caddy puede alcanzar al backend"
    else
        fail "Caddy NO puede alcanzar al backend - revisa que ambos esten en red lluvia_proxy"
    fi

    section "Sitio Caddy"
    if [ -f "$LLUVIA_HOME/caddy/sites/$SLUG.caddy" ]; then
        ok "$LLUVIA_HOME/caddy/sites/$SLUG.caddy existe:"
        sed 's/^/  /' "$LLUVIA_HOME/caddy/sites/$SLUG.caddy"
    else
        fail "Falta $LLUVIA_HOME/caddy/sites/$SLUG.caddy"
    fi
fi

section "Sugerencias"
cat <<EOF
- Si hay containers caidos:    cd $LLUVIA_HOME/clients/<slug> && docker compose logs backend --tail 100
- Si build fallo (Trixie/repos rotos): rebuilda con la version Operario nueva (Dockerfile pineado a bookworm).
- Si Caddy no tiene SSL: docker logs lluvia_caddy --tail 50 - mira si el ACME challenge se completo.
- Si webhook Telegram da Connection Refused: verifica https://<slug>.<dominio>/api/  (debe devolver JSON, no error).
EOF

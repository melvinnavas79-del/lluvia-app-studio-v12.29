# PRD - Lluvia App Studio Bot — Pipeline de Escalamiento

## URLs activas
- **Panel**: https://ai-bot-cost-calc.preview.emergentagent.com
- **Bot Telegram**: https://t.me/LluviaAppStudioBot

## Estado de implementación

### ✅ Iter 1-5 (resumen)
Bot multiplataforma + IA + GitHub + Modo Afiliado + Branding + Comandos shell admin-gated + Self-vinculación admin (`/vincular-admin`) + Salida real de servidor (RAM/disco/uptime).

### ✅ Iter 6 — Cleanup + Pipeline de venta
**1. Parser de comandos tolerante a lenguaje natural**:
  - `clean_shell_command()` strip de muletillas: "en el servidor", "en mi vps", "por favor", "el comando", etc.
  - Triggers ampliados: `ejecuta`, `comando`, `corre`, `/run`
  - Tolerancia a backticks, comillas, asteriscos

**2. Suite de despliegue automatizado** (`/app/scripts/`):
  - `infra-init.sh` — una sola vez en VPS: levanta Caddy reverse-proxy global con SSL automático
  - `setup-cliente.sh` — interactivo, despliega un cliente nuevo en ~5-10 min
  - `templates/` — Dockerfiles (backend/frontend), docker-compose template, Caddyfile, nginx.conf
  - `README.md` — guía de 5 pasos

**Aislamiento por cliente garantizado**:
  - Volumen Docker exclusivo `lluvia_<slug>_mongo_data` (cada cliente, su propia DB)
  - Backend container con `JWT_SECRET` único, `ADMIN_EMAIL/PASSWORD` independientes
  - Frontend buildeado con `REACT_APP_BACKEND_URL` específico del subdominio del cliente
  - Network Docker separada por cliente
  - Subdominio dedicado con SSL Let's Encrypt automático
  - Branding seedeado en su MongoDB privada

**Defaults configurables vía env**:
  - `LLUVIA_HOME=/opt/lluvia`
  - `LLUVIA_SOURCE=/opt/lluvia/source`
  - `LLUVIA_DEFAULT_OPENAI=` (master key opcional)
  - `LLUVIA_ROOT_DOMAIN=lluvia.app`

**Cobertura del pipeline**:
- Pre-requisitos one-shot: 15 min (VPS + DNS wildcard + Docker)
- Por cliente nuevo: 5-10 min (objetivo del usuario era < 30 min — superado con margen)
- 6+ clientes/hora factibles

## Backlog priorizado

### P0
- Rotar todas las credenciales compartidas en este chat (TELEGRAM_TOKEN, GITHUB_TOKEN, OPENAI_API_KEY, JWT_SECRET)
- Comprar el dominio raíz `lluvia.app` y configurar DNS wildcard
- Probar el pipeline con un cliente de prueba real

### P1
- Backups automáticos de volúmenes Mongo por cron
- Endpoint `/api/admin/clients` para que el script reporte el alta a un dashboard central de Lluvia
- Comando `/cliente nuevo` desde Telegram que detone `setup-cliente.sh` remotamente vía SSH

### P2
- Monitorización (Prometheus + Grafana) global
- Pagos automáticos por copia (Stripe Connect)
- Multi-idioma en todo el bot
- Función calling de OpenAI para que el bot decida automáticamente qué comando shell ejecutar

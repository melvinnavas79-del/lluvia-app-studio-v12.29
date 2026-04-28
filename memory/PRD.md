# PRD - Lluvia App Studio Bot — ENTREGA FINAL

## URLs operativas
- **Panel de control**: https://ai-bot-cost-calc.preview.emergentagent.com
- **Bot Telegram**: https://t.me/LluviaAppStudioBot

## Iteraciones completas
1. Bot core (16 + 6 tests)
2. White-label + Modo Afiliado MANUAL (25 + 9)
3. Pantalla Branding + persistencia (16 + 14)
4. Cierre Lluvia App Studio (18 + 12)
5. GitHub real + admin gates + identidad oficial
6. Pipeline `setup-cliente.sh` + parser tolerante
7. **Comando `/cliente nuevo` desde Telegram** — entrega final

## Iteración 7 — Despliegue desde el chat

### Funcionalidades nuevas
- Comando `/cliente nuevo` (alias: `cliente nuevo`, `/nuevocliente`) inicia un flujo conversacional
- State machine con 6 pasos: nombre → logo → primario → acento → email → confirmación
- Validaciones in-line (hex colors, email, URLs)
- `cancelar` aborta el flujo en cualquier momento
- Al confirmar: ejecuta `setup-cliente.sh` con `LLUVIA_NI=1` (no interactivo) vía subprocess
- Devuelve URL + email + password en el mismo chat de Telegram
- Defensa: solo admin (chat_id vinculado) puede iniciar el flujo
- Dry-run mode automático cuando Docker no está disponible (preview env) — útil para demo

### Cambios técnicos
- `setup-cliente.sh` ahora soporta:
  - Modo no interactivo via env vars `LLUVIA_DISPLAY`, `LLUVIA_PRIMARY`, etc.
  - `LLUVIA_DRY_RUN=1` salta Docker/Caddy y solo genera archivos
  - Output JSON parseable: `LLUVIA_RESULT_JSON_BEGIN ... END`
- `actions/client_provisioning.py` (180 líneas):
  - `_sessions` dict in-memory por chat_id
  - `start()`, `handle()`, `cancel()`, `has_session()`
  - Ejecución asíncrona del script con timeout de 5 min
- `agent.py`: si hay sesión activa, todos los mensajes del chat van al state machine

### Verificado en runtime
- Vinculación admin OK
- `/cliente nuevo` inicia flujo
- Validación rechaza colores inválidos
- Resumen muestra todos los datos antes de confirmar
- Confirmación ejecuta el script y devuelve credenciales formateadas
- Archivos generados correctamente (backend.env aislado, JWT único, MongoDB DB nombrada `bot_<slug>`, Caddyfile con SSL automático, branding.json con colores del cliente)
- Cancelación funciona en cualquier paso

## Estructura final del repositorio

```
/app/
├── backend/
│   ├── server.py              FastAPI + supervisor
│   ├── auth.py                JWT + bcrypt + seed migratorio
│   ├── affiliates.py          /auth, /affiliates, /sales, /stats
│   ├── branding.py            /branding (público/admin)
│   ├── ai.py                  OpenAI directo + system prompt blindado
│   ├── agent.py               Intent dispatcher + state machine awareness
│   ├── memory.py
│   ├── security.py            Blacklist anti-catastrofe
│   ├── models.py
│   ├── config.py
│   └── actions/
│       ├── github.py          Crear/listar repos
│       ├── server.py          run_command con safety
│       ├── apps.py
│       ├── business.py        greeting/help/auto_reply oficial
│       ├── affiliate_stats.py /mi-rendimiento
│       ├── admin_link.py      /vincular-admin <password>
│       └── client_provisioning.py  /cliente nuevo (state machine)
├── frontend/
│   └── src/  React + tema dark + branding dinámico CSS vars
└── scripts/
    ├── setup-cliente.sh       Despliegue por cliente
    ├── infra-init.sh          Caddy global one-shot
    ├── README.md              Guía 5 pasos
    └── templates/             Dockerfiles + compose + nginx + Caddy
```

## Listo para vender ✅

### Para tu Telegram personal:
1. Abre @LluviaAppStudioBot
2. `/vincular-admin Admin#2026`
3. `/cliente nuevo`
4. Sigue las preguntas → confirma → recibes URL + credenciales

### Para producción real (no preview):
1. Quita `LLUVIA_DRY_RUN=1` de `backend/.env` cuando estés en VPS con Docker
2. Setea `LLUVIA_HOME=/opt/lluvia` y copia el código a `/opt/lluvia/source/`
3. Ejecuta `infra-init.sh` una vez
4. Desde tu Telegram: `/cliente nuevo` cuantas veces quieras

### Pendientes obligatorios antes de la primera venta
- Rotar TELEGRAM_TOKEN, GITHUB_TOKEN, OPENAI_API_KEY, JWT_SECRET (todos compartidos en chat)
- Comprar dominio `lluvia.app` y configurar wildcard DNS
- Provisionar VPS con Docker + Docker Compose v2

## Backlog post-lanzamiento
- Backups automáticos de volúmenes Mongo
- Dashboard central que liste todos los clientes desplegados
- Edición remota de un cliente (`/cliente <slug> editar branding`)
- Métricas Prometheus + Grafana global
- Pago automático Stripe Connect por copia
- Función calling de OpenAI (decide qué shell ejecutar)

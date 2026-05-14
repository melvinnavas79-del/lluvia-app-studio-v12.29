# PRD - Lluvia App Studio Bot

## URLs operativas
- Panel: https://ai-bot-cost-calc.preview.emergentagent.com
- Telegram: https://t.me/LluviaAppStudioBot
- Tarball v10: `/api/download/lluvia-deploy` → `lluvia-deploy.tar.gz` (3.4 MB)

## Estado actual: v10 ENTREGADO (Feb 2026)

### Iteración 10 (Feb 2026) — COMPLETA

**Backend (server.py + nuevos módulos)**
- `telegram_unified.py` wired en `server.py` y `agent.py`. Comandos `/agente`, `/agente_<id>`, `/miagente`, `/saldo`, `/recargar` enrutados desde Telegram. Mensajes normales se envían al agente seleccionado via `run_with_selected_agent`. Persistencia en `tg_user_pref`.
- `app_builder` prompt reforzado en `agents_catalog.py`: estructura obligatoria de 7 pantallas (Inicio, Popular, Explorar, Crear, Notificaciones, Perfil, Detalle) estilo TikTok/Bigo.
- `call_center.py` — endpoint `POST /api/voice/call-center/turn` (multipart audio + agent_id + session_id) que encadena Whisper → GPT → TTS en un solo turno. Cobra oros por capa (audio in + chat + audio out). Persiste sesión en `chat_sessions`. Límite 8 MB/turno.
- `rate_limit.py` con `slowapi`:
  - `/api/auth/login` 8/min/IP
  - `/api/paypal/create-order` 15/h/IP
  - `/api/paypal/webhook` 60/min/IP
  - `/api/voice/transcribe`, `/tts` 30/min/IP
  - `/api/voice/call-center/turn` 20/min/IP
- `paypal_integration.py`: nuevo `POST /api/paypal/webhook` con `_verify_paypal_signature` (API oficial PayPal `verify-webhook-signature`). Rechaza 403 si `PAYPAL_WEBHOOK_ID` no configurado. Acreditación idempotente.
- `promos.py` ya integrado con `/api/paypal/packs` aplicando descuento dinámico (mayor % activo).
- `proposals.py` con handlers seguros por tipo (`branding_update`, `promo_create`, `agent_create`, `agent_update`, `pricing_update`). JAMÁS ejecuta código arbitrario.
- Fix bug `voice.py`: `_client()` no instanciaba antes de Whisper.

**Frontend (3 tabs nuevos en AdminDashboard)**
- `ProposalsTab.js` — lista propuestas, botones Aprobar/Rechazar, muestra payload JSON, autor y estado.
- `PromosTab.js` — CRUD reglas de descuento, picker dias de semana, dias de mes.
- `CallCenter.js` — selector de agente, botón "Llamar/Colgar", loop continuo MediaRecorder (4.5s/turno) → backend → reproduce TTS → graba de nuevo. Muestra transcripción turno por turno con badge de oros restantes.
- CSS nuevo en `App.css` (proposals-list, cc-transcript, cc-bubble, status-* chips).

**Seguridad — blindaje total**
- JWT 8h con bcrypt, `seed_admin` idempotente
- Rate limit en 6 endpoints sensibles
- Webhook PayPal con firma criptográfica obligatoria
- `is_command_safe` blacklist + `is_admin_chat` gate en Telegram
- CORS sin credentials para bloquear CSRF
- Aislamiento Mongo+JWT por cliente desplegado
- Detalles completos en `SECURITY.md`

**Documentación entregada**
- `LICENSE` — licencia propietaria 100% Melvin Navas, clausula work-for-hire
- `MIGRATION.md` — guía VPS paso a paso (Docker, Caddy, PayPal webhook, backups)
- `SECURITY.md` — documentación técnica del blindaje
- `PRD.md` — este archivo

### Testing v10 (iteración 5 del job actual)
- **26/26 pytest cases PASSED** sobre URL pública
- 0 issues found, 0 blockers
- Cubre: auth+rate-limit, promos CRUD, proposals end-to-end, PayPal packs con promo, PayPal webhook 403 sin firma, Telegram unified completo, Call Center con 413/400/502 controlados, branding extendido, /info v10, endpoints v9 intactos.

## Iteraciones anteriores
1-8: bot core, white-label, branding, GitHub real, setup-cliente, modo operario, /cliente nuevo
9: 7 agentes especializados, voz Whisper+TTS, PayPal Checkout, Agency View, Arquitecto UI

## Stack

```
/app/
├── backend/
│   ├── server.py            FastAPI + slowapi middleware
│   ├── agent.py             dispatcher con telegram_unified hook
│   ├── telegram_unified.py  menu /agente + persistencia agent seleccionado
│   ├── telegram_poller.py   long-polling background
│   ├── call_center.py       Whisper -> GPT -> TTS por turno
│   ├── promos.py            CRUD descuentos
│   ├── proposals.py         auto-update propuesto + admin approve
│   ├── paypal_integration.py packs+orders+webhook firmado
│   ├── voice.py             transcribe + tts
│   ├── rate_limit.py        slowapi limiter por IP
│   ├── auth.py              JWT + bcrypt + seed_admin
│   ├── agents_catalog.py    8 agentes built-in
│   ├── agent_builder.py     custom_agents CRUD
│   ├── agency_view.py       MRR + lista clientes desplegados
│   └── actions/             github, server (shell), client_provisioning
├── frontend/src/components/
│   ├── BossConsole.js       chat texto multi-agente
│   ├── CallCenter.js        loop voz continuo (v10)
│   ├── ProposalsTab.js      aprobar cambios propuestos (v10)
│   ├── PromosTab.js         CRUD reglas descuento (v10)
│   ├── BrandingTab.js       white-label extendido
│   ├── AgencyView.js        MRR + clientes
│   ├── AgentBuilder.js      crear agentes custom
│   └── AdminDashboard.js    tabs orquestador
└── scripts/                 setup-cliente.sh, infra-init.sh, templates
```

## Backlog futuro (v11+)

P1:
- Backups automáticos Mongo por cliente (cron + S3/Backblaze)
- Dashboard central que liste todos los clientes con métricas en tiempo real
- Stripe Connect para pagos automáticos por copia desplegada
- Edición remota de cliente desde panel maestro

P2:
- Métricas Prometheus + Grafana global
- Marketing Agent UI con sugerencias automáticas de copys
- Función calling de OpenAI decide qué shell ejecutar (parser tools)
- Soporte WhatsApp Cloud API + Instagram DM con polling unificado

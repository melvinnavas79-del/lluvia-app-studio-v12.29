# PRD - Lluvia App Studio Bot

## URLs operativas
- Panel: https://ai-bot-cost-calc.preview.emergentagent.com
- Telegram: https://t.me/LluviaAppStudioBot
- Tarball v10: `/api/download/lluvia-deploy` → `lluvia-deploy.tar.gz`

## Estado actual: v11 ENTREGADO (Feb 2026) · 26/26 tests passed

### Iteración 11 - Modulos nuevos

**Backend**
- `super_admin.py` — `/api/super/{overview, sessions/all, sessions/{id}, sessions/{id}/takeover, users, github/push, github/history}`. Admin-only (futuro flag `is_super_admin`). Bypass de oros heredado del role admin.
- `appointments.py` — CRUD `/api/appointments` + 4 tool handlers (book, check_availability, list, cancel). Validacion fechas, formato, solapamiento.
- `console.py` extendido con 6 tools: `book_appointment`, `check_availability`, `list_appointments`, `cancel_appointment`, `paypal_invoice_card` (genera orden PayPal LIVE real), `service_card`. Inyecta `_agent_id` desde sesion.
- `agents_catalog.py` — Prompt del Arquitecto reforzado: agentes de rubros con citas/cobros llevan automaticamente las tools de appointments + paypal.
- Fix `create_session` ahora soporta custom agents via `_get_agent_any`.

**Frontend**
- `SuperAdminPanel.js` tab principal (default) con 4 sub-tabs: Overview KPIs, Sesiones cross-tenant con takeover, Usuarios+balance, Push & Backup.
- Rich Cards en `BossConsole.js`: `<PaymentCard>` (logo, monto, descripcion, cliente, order_id, boton "Pagar con PayPal") y `<ServiceCard>` (imagen, titulo, precio, CTA).
- Avatares circulares enterprise (iniciales sobre color), eliminados emojis grandes.
- Badge "👑 SuperAdmin" en mensajes de takeover.

**Integraciones activas**
- OpenAI GPT/Whisper/TTS — keys validas, respuestas reales.
- PayPal LIVE — orden real probada (`0LE40408PX...`).
- Telegram bot @LluviaAppStudioBot — polling activo.
- GitHub Push — add/commit OK; push pendiente de token valido (rotar antes).

**E2E real verificado**
- Arquitecto crea "Recepcionista Glam Studio" via `create_agent` tool.
- Agente reserva cita real: `check_availability` + `book_appointment` → persistida en MongoDB.
- Agente cobra seña: `paypal_invoice_card` → Rich Card visual con approve_url LIVE.

### Iteracion 10 (entregada antes)
Telegram unificado, App Builder multi-pagina, Call Center, Promos, Proposals, Branding extendido, blindaje seguridad. 26/26 tests passed.

## Backlog futuro

P0:
- **Gmail OAuth2**: agente "Soporte Lluvia" como auto-responder. Requiere proyecto Google Cloud del user (client_id + secret + redirect_uri).

P1:
- Multi-tenant takeover cross-VPS (panel maestro -> VPS via API key)
- Backups automaticos Mongo por cliente (cron + S3)
- Stripe Connect

P2:
- Metricas Prometheus + Grafana
- WhatsApp Cloud API + Instagram DM

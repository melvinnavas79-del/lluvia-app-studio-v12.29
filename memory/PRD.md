# PRD — Lluvia App Studio

## URLs operativas
- Preview: https://ai-bot-cost-calc.preview.emergentagent.com
- Producción: https://lluvia-app-studio.lluvia-live.com (Emergent Native Deploy)
- Telegram: https://t.me/LluviaAppStudioBot

## Estado actual: v12 — UI/UX Premium Rediseño (Feb 2026)

### Iteración 12 — Rediseño Premium "Emergent-style" (HECHO)
Pivot visual completo de aspecto "developer console oscuro" a **enterprise SaaS premium**.

**Nuevo sistema de diseño** (`/app/design_guidelines.json` + `/app/frontend/src/App.css`):
- **Paleta**: Warm off-white `#FDFBF7`, charcoal navy `#0F172A`, azul corporativo `#2563EB`. Reemplaza el dark + gold anterior.
- **Tipografía**: Cabinet Grotesk (display, italic accents) + Satoshi (body) + Geist Mono (traces). Cero AI-slop fonts.
- **Avatares de agentes**: `AgentAvatar` nuevo componente que usa **DiceBear bottts-neutral** con seeds deterministas + fondos pastel únicos por agente. Reemplaza emoji-en-cuadrado.
- **Radios & sombras**: r-xl 22px, sombras ambient suaves, glassmorphism solo donde aplica.
- Compatibilidad white-label preservada via CSS variables.

**Componentes rediseñados**:
- `PublicChat.js` — landing premium con hero italic, strip decorativo de bots, feature grid, agent grid, CTA final navy.
- `Login.js` — card blanca, trial badge de 50 oros, jerarquía editorial.
- `ClientDashboard.js` — header sticky con logo navy, tabs limpios sin emojis, balance gold sutil.
- `BossConsole.js` — chat estilo Linear/Notion, bubbles asimétricos (user navy / agent surface), DiceBear avatars en threads/cards/mensajes/header.

**Backend**: `branding.py` defaults actualizados al nuevo theme. Branding existente en DB reseteado al theme premium.

### Iteración 11 (entregada antes)
- `super_admin.py` — `/api/super/{overview, sessions/all, sessions/{id}/takeover, users, github/push}`. Admin-only.
- `appointments.py` — CRUD `/api/appointments` + 4 tool handlers (book, check_availability, list, cancel).
- `console.py` extendido con 6 tools: book_appointment, check_availability, list_appointments, cancel_appointment, paypal_invoice_card, service_card.
- `user_workspace.py` — cada usuario puede configurar su GitHub token y hacer push personal.
- `auth.py` — registro público + 50 oros de trial.
- Rich Cards (PaymentCard / ServiceCard) en BossConsole.

**Integraciones activas**: OpenAI GPT/Whisper/TTS · PayPal LIVE · Telegram bot · GitHub Push.

### Iteración 10
Telegram unificado, App Builder multi-página, Call Center, Promos, Proposals, Branding extendido, blindaje seguridad. 26/26 tests passed.

## Backlog futuro

**P0 (próximo)**:
- Validar el flujo completo Registro → Dashboard → Chat con trial → Push GitHub via testing_agent_v3_fork (pendiente aprobación visual del usuario antes de testear).

**P1**:
- Gmail OAuth2 — agente "Soporte Lluvia" auto-responder. Requiere Google Cloud (client_id + secret + redirect_uri).
- Multi-tenant takeover cross-VPS (panel maestro → VPS via API key).
- Backups automáticos Mongo por cliente (cron + S3).
- Stripe Connect para split payments con afiliados.

**P2**:
- WhatsApp Cloud API + Instagram DM.
- Métricas Prometheus + Grafana.

## Archivos clave de referencia
- `/app/frontend/src/App.css` (sistema de diseño v12)
- `/app/frontend/src/components/AgentAvatar.js` (nuevo — bots DiceBear)
- `/app/frontend/src/components/PublicChat.js`, `Login.js`, `ClientDashboard.js`, `BossConsole.js` (rediseñados)
- `/app/backend/branding.py` (defaults nuevos)
- `/app/design_guidelines.json` (blueprint completo del rediseño)

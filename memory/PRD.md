# PRD — Lluvia App Studio

## URLs operativas
- Preview: https://ai-bot-cost-calc.preview.emergentagent.com
- Producción: https://lluvia-app-studio.lluvia-live.com (Emergent Native Deploy)
- Telegram: https://t.me/LluviaAppStudioBot

## Estado actual: v12.10 — Vision (foto en chat) + UI ChatGPT-like (Feb 2026)

### Iteración 12.10 — Chat con imágenes + UI Emergent-style (HECHO)
**Imágenes en el chat de agentes** (`BossConsole`):
- Nuevo endpoint backend `POST /api/console/sessions/{id}/upload-image` con upload por chunks (64KB), valida MIME (jpeg/png/gif/webp), límite 8MB, guarda en `/app/backend/uploads/chat_images/<userid>_<uuid>.ext`. Retorna `{url, filename, size, content_type}`.
- `app.mount("/api/uploads", StaticFiles(...))` en `server.py` para servir las imágenes públicamente (URLs con UUID hex no enumerable).
- `MessageIn` extendido con `image_urls: Optional[List[str]]`. Cuando viene, `send_message` construye contenido multimodal para GPT-4o (`[{type:text},{type:image_url,detail:auto}]`), resuelve URL relativa → absoluta usando `PUBLIC_BASE_URL` (fallback data:base64), cobra +3 oros por imagen (`COST_VISION_IMAGE`), persiste `image_urls` dentro del `user_msg`.
- Frontend: botón paperclip + file picker (multiple), drag-and-drop sobre el chat con overlay "Soltá la imagen", paste de imagen desde clipboard, preview chip con thumbnail + spinner de uploading + botón X, imagen renderizada dentro de la burbuja del usuario con click → abre en pestaña nueva.

**UI ChatGPT/Emergent-style**:
- Burbujas pegadas al borde: usuario derecha (navy), asistente izquierda (surface). Border-radius asimétrico (top-right:6px / top-left:6px según rol).
- Avatares circulares de 40px con sombra suave.
- Composer rediseñado como una caja redondeada (radius 22px) con paperclip + mic + textarea autoresize (hasta 200px) + botón send circular con icono de avión SVG. Focus state con glow azul. Hint legend abajo "GPT-4o vision · 3 oros por imagen · arrastrá o pegá fotos".
- Animaciones nuevas: `bcSlide` (mensaje entrante), `bcChipIn` (chip de adjunto), pulse en mic recording.

**Tests**: backend pytest 9/9 verde (`/app/backend/tests/test_iteration_7_vision.py`). E2E smoke verificado: GPT-4o describe correctamente una imagen verde de 96x96 subida. Voz (Whisper + TTS) sin regresión.

## Estado anterior: v12.1 — UI/UX Premium + Light/Dark + Reposicionamiento comercial (Feb 2026)

### Iteración 12.1 — Light/Dark Toggle + Pivot Comercial (HECHO)
**Reposicionamiento de copy** (landing pública):
- Hero title nuevo: "Creá Aplicaciones Profesionales y Agentes de IA que trabajan por vos 24/7"
- Subtítulo enfocado en: apps multimedia (TikTok/Kwai/Likee), agentes IA personalizados para negocios (peluquerías, WhatsApp), sistemas de radio en vivo.
- **3 tarjetas pilar grandes** con gradientes radiales únicos:
  1. Apps Complejas y Multimedia (fucsia · feeds + streaming + perfiles dinámicos)
  2. Agentes Personalizados para Negocios (verde · citas + cobros + WhatsApp)
  3. Sistemas de Radio y Audio Live (ámbar · emisora 24/7 + DJ-IA + moderación)
- Reemplazados emojis grandes por **iconos lucide-react** (Video, Bot, Radio, Sparkles, Calendar, etc).

**Toggle Light/Dark Premium**:
- `ThemeContext.js` nuevo — gestiona modo, persiste en `localStorage`, expone `<ThemeToggle/>`.
- Variables CSS para canvas (bg/surface/text/border) separadas del white-label (que sigue controlando solo primary/accent).
- Dark theme con: deep navy `#0B0F19`, gradients radiales acentuados, glow en pillar cards, primary invertido a `#F9FAFB`.
- Toggle accesible en headers de `PublicChat` y `ClientDashboard`.

### Iteración 12 — Rediseño Premium "Emergent-style" (HECHO)
[anterior]
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

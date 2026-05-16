# PRD — Lluvia App Studio

## URLs operativas
- Preview: https://ai-bot-cost-calc.preview.emergentagent.com
- Producción: https://lluvia-app-studio.lluvia-live.com (Emergent Native Deploy)
- Telegram: https://t.me/LluviaAppStudioBot

## Estado actual: v12.12 — Before/After Nano Banana + Marketing Lab (Feb 2026)

### Iteración 12.12 — Estilista Before/After (Gemini Image) + agente Marketing Lab (HECHO)
**💇✨ Estilista Visual ahora genera imagen real "After" con Gemini Nano Banana**
- Nuevo módulo `/app/backend/image_gen.py` que usa `emergentintegrations.LlmChat` con modelo `gemini-3.1-flash-image-preview` para img2img.
- Nueva tool `generate_haircut_preview(look_description, look_name)` que toma la última foto del cliente, le aplica el prompt en inglés (largo + color + textura + movimiento) y guarda el resultado en `/app/backend/uploads/ai_generated/`. Cobro: **15 oros**.
- Inyección automática de `_last_image_url` en el args (busca en el mensaje actual o en el historial).
- Rich card nuevo `BeforeAfterCard`: grid 3 columnas (Antes | flecha | Después · IA), imágenes 1:1 con click-to-zoom.
- System prompt del Estilista actualizado para llamar a `generate_haircut_preview` por cada una de las 3 opciones de corte (después de las `service_card`).
- Verificado E2E: una foto real de Unsplash → Nano Banana → imagen 627KB del rostro con el corte sugerido manteniendo identidad facial.

**🎬 Nuevo agente: Marketing Lab**
- ID `marketing_lab`, emoji 🎬, color `#f59e0b`, voice `fable`.
- Recibe una feature de la app y genera el GUION COMPLETO para TikTok/Reels/Shorts.
- Nueva tool `video_script_card` con: `title`, `platform`, `duration_sec`, `hook`, `scenes[{t,visual,voiceover}]`, `caption`, `hashtags[]`, `music_suggestion`, `cta`. Cobro: 2 oros.
- Rich card `VideoScriptCard` con secciones organizadas (hook con accent border, escenas numeradas con timecodes, hashtags como chips, botón 📋 para copiar todo al clipboard).
- System prompt obliga al modelo a hacer 1 pregunta por turno hasta tener los 4 datos mínimos (feature, plataforma, duración, tono) y solo entonces emitir la tarjeta.

**🐛 Bug fix técnico crítico**
- `result_preview` en `tool_calls` truncaba a 300 chars (no permitía renderizar `video_script_card` ni `before_after_card` completos en el frontend). Ahora 6000 chars.

**Tests**: 5/5 backend pytest verde incluyendo llamada real a Nano Banana (~25s). Frontend E2E ambos flujos verde. Cero regresiones.



### Iteración 12.11 — Estilista Visual + UX fixes (HECHO)
**🐛 Bug fix: Settings tab para admin**
- `AdminDashboard` no exponía la pantalla de configuración de GitHub (solo el `ClientDashboard` la tenía). El usuario admin no podía configurar su token y el botón "Push" del chat se quedaba en un dead-end.
- Extraído `SettingsTab` a `/app/frontend/src/components/SettingsTab.js` (form GitHub + tarjeta Telegram).
- Agregado tab "Mi Cuenta" (data-testid='tab-settings') al `AdminDashboard`.
- Ambos dashboards ahora sincronizan el tab con `location.hash` (#/settings, #/github, etc) y escuchan el evento `lluvia:goto-settings`.
- `BossConsole.pushNow()` ya no recarga la página: dispara `CustomEvent('lluvia:goto-settings')` cuando el push falla por falta de configuración → el dashboard salta limpiamente al tab settings.

**🎨 Composer estilo Emergent (orden de izq→der)**
- 📎 paperclip → textarea → 🎙 mic → ▶ send.
- Mic e icono de send ahora son SVGs (no emoji). Botones circulares de 36px.
- Spinner animado mientras se envía.

**💇 Nuevo agente: Estilista Visual** (`/app/backend/agents_catalog.py`)
- ID `estilista_visual`, emoji 💇, color `#ec4899`, voice `shimmer`.
- System prompt: cliente manda foto → análisis (forma de rostro, textura, subtono) → 3 opciones (corte + por qué favorece + mantenimiento + precio USD) → service_card por cada opción → check_availability + book_appointment + paypal_invoice_card cuando reserva.
- Tools: `service_card`, `check_availability`, `book_appointment`, `list_appointments`, `cancel_appointment`, `paypal_invoice_card`.
- Usa GPT-4o vision (ya implementado en iteración 12.10) → wow-demo perfecto para videos de TikTok.

**Tests**: backend 7/7 verde (`/app/backend/tests/test_iteration_8_estilista.py`), frontend e2e 100% (settings tab, composer order, hash routing, estilista vision). Cero regresiones.



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

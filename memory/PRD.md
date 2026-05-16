# PRD — Lluvia App Studio

## URLs operativas
- Preview: https://ai-bot-cost-calc.preview.emergentagent.com
- Producción: https://lluvia-app-studio.lluvia-live.com (Emergent Native Deploy)
- Telegram: https://t.me/LluviaAppStudioBot

## Estado actual: v12.19 — App Builder Pro + Audio Room template (Feb 2026)

### Iteración 12.19 — App Builder Pro: apps deployables reales en 30 seg (HECHO)
**🚀 Nuevo agente `app_builder_pro` (emoji 🚀, color #5B8DEF, voice onyx)**
- Objetivo: cumplir la promesa de la landing — entregar apps multi-pantalla deployables, no juguetes single-page.
- Arquitectura clave: **NO genera código con el LLM** (costoso + lento + propenso a APIs inventadas). En su lugar, copia un **template pre-construido y testeado** al workspace del usuario, reemplazando `{{APP_NAME}}` y `{{BRAND_COLOR}}`.
- System prompt corto y duro: pregunta solo 2 datos (nombre + color) y dispara la tool en el mismo turno.

**🎙 Template `audio_room` (Clubhouse / Twitter Spaces clone)**
- `/app/backend/app_templates/audio_room/`:
  - **Backend** (`backend/server.py`): FastAPI + python-socketio + SQLite. JWT propio, registro anónimo, modelos User/Room/Follow/RoomAccess. Endpoints `/api/users/anonymous|top|{id}|{id}/follow`, `/api/rooms` CRUD, `/api/rooms/{id}/purchase`. Socket.IO eventos: `join-room`, `leave-room`, `offer`/`answer`/`ice-candidate` (signaling WebRTC), `request-speak`, `promote-speaker`, `reaction`. Cero deps externas obligatorias.
  - **Frontend** (`frontend/{index.html, css/styles.css, js/{api.js, webrtc.js, app.js}}`): SPA con hash router puro vanilla JS. 4 pantallas: Inicio (categorías + salas live), Tendencias (top creadores + más escuchadas), Sala Activa (hosts/speakers/listeners con mute/raise-hand/reacciones), Perfil (stats + follow + suscripción premium). Bonus: Crear Sala con monetización free/premium.
  - **README.md** completo con instrucciones de deploy a Railway/Render en 5 min.
  - **.env.example** + **.gitignore** listos.
- Monetización ya cableada: `room.monetization='premium'` + `price_credits` + endpoint `purchase_access` que valida server-side antes de dar acceso.

**🛠 Nueva tool `generate_audio_room_app` (40 oros fijos)**
- Definida en `console.py:259` (OPENAI_TOOLS) y ejecutada en `_exec_tool` (rama ~línea 670).
- Implementación reusable en `/app/backend/app_builder.py` con `list_templates()` y `materialize_template(template_id, target_dir, app_name, brand_color)` — copia recursiva del template a `{LLUVIA_HOME}/user_apps/{user_id}/{slug}/` con reemplazo de placeholders.
- Skip de binarios runtime (`data.db`, `.pyc`, `__pycache__`, `.git`).
- Refund automático de 40 oros si la materialización falla.

**🎴 Rich Card `AppBuiltCard` en `BossConsole.js`**
- Renderiza badge verde 'App ensamblada', stack chip, app_name destacado, grid 2×2 de los 4 screens, next_step (sugerencia de push GitHub). En error: badge rojo + mensaje + aviso de refund.
- `data-testid='app-built-card'`.

**Verificación E2E (iteration_17.json)**: backend 7/7 pytest verde, frontend Playwright verde. El agente dispara la tool confiablemente en español, la materialización copia 10 archivos (52 KB) con placeholders reemplazados, re-invocación falla limpia, admin no pierde oros (admin_free), endpoints existentes intactos. Test reusable en `/app/backend/tests/test_iteration_17_app_builder_pro.py`.

**Nit conocido (LOW, by-design)**: el emoji 🚀 del agente no se ve en el agent-picker del BossConsole porque `AgentAvatar` usa dicebear bot SVG por el rebrand v12 enterprise. El 🚀 sí aparece dentro de la `AppBuiltCard` final.



## Estado anterior: v12.18 — Pre-validación GitHub + refund push + UI admin clara (Feb 2026)

### Iteración 12.18 — Fix de raíz del push fallido (HECHO)
**🐛 Causa raíz del frustrante "-51 oros y push falla"**
- `do_push` invocaba `git push` con el token **sin validar primero**. Si GitHub rechazaba el token, el error técnico ("Invalid username or token") se mostraba en crudo al usuario.
- El cobro de oros se contabilizaba aunque el push fallara, sin refund.
- Para admin, se mostraba `cost_oros=51` aunque el `credits.charge` retorna sin descontar (admin_free), lo que confundía al usuario haciéndole creer que perdió oros.

**🛡 Fixes aplicados (todos testeados 7/7 backend + E2E frontend)**:
1. **Pre-validación GitHub via API REST** (`user_workspace._validate_github_token`): consulta `api.github.com/user` con el token antes de gastar git. Si rechazado → mensaje claro en español con link a tokens/new.
2. **Nuevo endpoint** `POST /api/me/github/validate` que el usuario puede llamar para probar SIN cobrar.
3. **Botón "Probar mi token de GitHub"** en SettingsTab (data-testid='github-validate-btn') que muestra ✅/❌ con mensaje claro.
4. **Errores de git traducidos al español**: "Invalid username or token" → mensaje paso-a-paso con link.
5. **Refund automático** en console.py cuando push falla (8 oros) para no-admins.
6. **Admin UI**: separación `cost_oros` (real, 0 para admin) vs `nominal_cost_oros` (display). Frontend muestra "👑 Gratis (admin · sería X oros)" en verde para admin.
7. **Seguridad**: token enmascarado en los logs `steps` que se persisten en mongo (no más leakage).

**Verificado**: el token actual del admin está rechazado por GitHub. Al hacer click en "Probar mi token" devuelve el mensaje correcto. Ningún oro se descuenta del balance real del admin.



### Iteración 12.17 — API key del admin para TODO + composer Emergent (HECHO)
**🔑 Cero dependencia de Universal Key Emergent**
- `video_gen.py` reescrito con `OpenAI SDK 2.37.0` nativo (`client.videos.create/retrieve/download_content`). Usa `OPENAI_API_KEY` del admin → el costo de Sora 2 se carga a su billing de OpenAI, no al Universal Key.
- `image_gen.py` reescrito con `client.images.edit(model='gpt-image-1', image, prompt, size='1024x1024')` para Before/After del Estilista Visual. Reemplaza la dependencia de Gemini Nano Banana.
- `gmail_maestro.py`: clasificación/draft de correos ahora prioriza `OPENAI_API_KEY` sobre `EMERGENT_LLM_KEY`. Si OpenAI key existe, NO usa el `base_url` de Emergent (llamada directa a api.openai.com).
- `requirements.txt`: `openai>=2.37.0` (era 1.99.9, pinneado por emergentintegrations).
- Mensajes de error claros si la cuenta OpenAI no tiene saldo / acceso a Sora 2.

**Verificado E2E con la API key del admin**:
- Sora 2 (`sora-2`, 4s, 720x1280) → video real generado en 70s, 2.1 MB ✅
- Image edit (`gpt-image-1`, 1024x1024) → before/after generado para foto Unsplash, 1.3 MB ✅
- Refund automático en error sigue funcionando.

**🎨 Composer estilo Emergent al 100%**
- Botón `+` (data-testid='bc-attach-btn') abre menú flotante con: 🖼 Subir desde galería · 📷 Tomar foto · ⬆ Push a GitHub.
- Quitado el botón de cámara separado.
- Click-outside cierra el menú automáticamente.
- Push a GitHub ahora accesible desde 2 lugares: el `+` del composer y el botón superior del chat.



### Iteración 12.16 — Pago real + economia sustentable (HECHO)
**💳 Bug crítico PayPal RESUELTO**
- Causa raíz: `create-order` no incluía `return_url`/`cancel_url` en `application_context`, por lo que PayPal nunca devolvía al cliente a la app, y el frontend nunca llamaba `/paypal/capture/{order_id}`. **Pagos completados sin acreditar oros**.
- Fix backend: `paypal_integration.py` ahora pasa `return_url={PUBLIC_BASE_URL}/?paypal=success#/recharge` y `cancel_url={PUBLIC_BASE_URL}/?paypal=cancel#/recharge`.
- Fix frontend: `RechargeTab` detecta `?paypal=success&token=ORDER_ID` al montarse → llama capture → muestra mensaje verde "Pago confirmado! Acreditamos X oros" (data-testid='paypal-success') → limpia URL con `history.replaceState`. Si cancel → warning.
- Fix UX: `ClientDashboard.initialTab()` detecta el query string y fuerza tab `recharge` aunque el usuario haya estado en otra pestaña antes.

**🎁 Trial reducido + dinámico + anti-abuso**
- De 50 → **15 oros** por registro (configurable desde SuperAdmin via `site_content.trial_oros` con field Pydantic 0-500).
- Anti-farming por IP: máximo **3 registros/24h** desde la misma IP, sino HTTP 429.
- Trial usado dinámicamente en backend (`affiliates.py` lee `site_content.trial_oros`) y frontend (`Login.js` y `PublicChat.js` leen `/api/site/content` y muestran el número correcto en CTA, bullet, badge, banner). Verificado en landing: "Empezar gratis con 15 oros →" + "✓ 15 oros gratis al registrarte".

**Tests**: backend 7/7 pytest verde (PayPal create-order con return_url, trial dinámico, anti-farming 429). Frontend verificado vía screenshot del landing.



### Iteración 12.15 — Bug crítico: budget EMERGENT_LLM_KEY agotado (HECHO)
**🐛 Causa raíz descubierta**
- Sora 2 venía fallando con "archivo vacío" desde las 12:54hs. El error real era `Budget has been exceeded! Current cost: 1.34609861, Max budget: 1.34609861` del Universal Key. Los oros del cliente se cobraban antes de saber si Sora 2 funcionaría → cliente sin video y sin oros = pérdida directa para el negocio del usuario.

**🛡 Refund automático implementado**
- Nuevo helper `credits.refund(user_id, amount, reason, meta)` con log de transacción tipo `refund`.
- `video_gen._run_job` ahora: (a) detecta cualquier fallo, (b) busca el `charged_oros` guardado en el doc del job, (c) devuelve los oros al usuario, (d) marca `refunded=true` en el job, (e) si el error es "budget exceeded" lo reescribe a un mensaje claro ("Recarga saldo en Emergent → Profile → Universal Key → Add Balance").
- `console.py` ahora pasa `charged_oros=cost` (o 0 si admin) al encolar el video Sora 2.
- `generate_haircut_preview` (Nano Banana) también hace refund automático del costo (15 oros) si falla.
- Frontend `VideoJobCard` y `BeforeAfterCard` ahora muestran "💸 Te reembolsamos X oros automáticamente" cuando el job falla con `refunded=true`. Quitado el aviso engañoso de "no reembolsable".

**Verificado E2E**: usuario test no-admin con 100 oros → Sora 2 falla por budget exceeded → refund automático aplicado → balance restaurado.



### Iteración 12.14 — 4 bugs reportados en screenshots (HECHO)
**🐛 Bug 1: Marketing Lab solo devolvía guion, no video**
- System prompt v3: ahora exige decisión A (guion 2 oros) vs B (Sora 2 30-55 oros) cuando el cliente dice "crea un video" sin más contexto. Y cuando el cliente confirma B con duración + "dale/confirmo", el agente DEBE llamar `generate_promo_video` **en el mismo turno** (regla explícita anti-procrastinación del LLM).
- Frontend: botón CTA dentro de `VideoScriptCard` (data-testid='vs-request-real-video') con "🎥 Generar este video REAL con Sora 2 · 30–55 oros". Dispara `CustomEvent('lluvia:compose-message',{text,send:true})` que el BossConsole escucha y envía automáticamente con los datos del guion.
- Verificado E2E: confirmación explícita → tool call con cost=31 oros (1 base + 30 video 4s), card status=queued.

**🐛 Bug 2: Cámara negra en iOS WebView (Preview de Emergent)**
- Causa raíz: el Preview de Emergent en iOS Safari corre en WebView/iframe que bloquea `getUserMedia` con `NotAllowedError`.
- Fix: `openCamera()` ahora detecta `!window.isSecureContext`, ausencia de `mediaDevices`, o `NotAllowedError` → cae automáticamente al `<input capture="environment">` nativo (data-testid='bc-native-camera-input') que SÍ funciona en WebView iOS porque abre la app de cámara del SO. Botón fallback visible "📱 Usar cámara del teléfono" dentro del overlay de error. Flip también con fallback.

**🐛 Bug 3: "Procesados undefined correos"**
- Fix: `data.newly_processed ?? 0` + `data.total_unread ?? 0` en `SuperAdminPanel.js:485`.

**🐛 Bug 4: Usuario vinculó cuenta Gmail equivocada y no encontraba cómo cambiar**
- Fix: en `IntegrationsPanel`, junto al email vinculado ahora aparece un aviso ⚠ "Asegurate que esta sea la cuenta a la que te llegan los correos de tus clientes" + botón inline "Desvincular y cambiar cuenta" (data-testid='gmail-unlink-btn-inline'). El botón original al fondo del panel sigue disponible.

**Tests**: backend 6/6 pytest verde + frontend E2E del panel Gmail verificado en vivo. Cero regresiones.



### Iteración 12.13 — Sora 2 + Bug fix cámara negra (HECHO)
**🎥 Sora 2 generación de video real (Marketing Lab)**
- Nuevo módulo `/app/backend/video_gen.py` con `OpenAIVideoGeneration` de `emergentintegrations` (EMERGENT_LLM_KEY).
- **Bug del SDK descubierto y patcheado**: la API real de Sora 2 solo acepta `720x1280` y `1280x720`, pero el SDK validaba contra una whitelist vieja. Sobrescribimos `OpenAIVideoGeneration.SIZES` al cargar el módulo.
- Nueva tool `generate_promo_video(prompt, duration, aspect, quality)`. Tarifa dinámica: **4s=30 oros, 8s=40 oros, 12s=55 oros** (cubre costo API + margen).
- Arquitectura: tool encola job en mongo `video_jobs`, lanza `asyncio.create_task` con referencia trackeada (anti-GC), endpoint `GET /api/console/video-jobs/{id}` con auth + owner check para polling.
- Frontend: `VideoJobCard` con spinner + cronómetro + progress bar con ETA, polling cada 6s, render final con `<video controls>` aspect-ratio dinámico + botón ⬇ Descargar MP4. Aviso UX: cobro no reembolsable si Sora falla.
- Marketing Lab system prompt v2: ahora maneja flujo 1 (guion barato con `video_script_card`) y flujo 2 (video real con `generate_promo_video`). Obliga a confirmar costo antes de invocar la tool.
- **Verificado E2E**: video real de 4s vertical generado en ~90s, 2.6MB, servido y reproducible en el chat.

**📷 Bug fix: cámara negra**
- Causa raíz: el `<input capture="environment">` falla silenciosamente en muchos WebViews/navegadores mobile → pantalla negra sin error.
- Solución: botón nuevo (data-testid=`bc-camera-btn`) que abre un modal fullscreen con `getUserMedia` directo + `<video>` element. Captura el frame a un `<canvas>` y lo pasa por el mismo `uploadImage()` que el paperclip.
- Modal con: shutter circular blanco, botón cancelar, botón flip (delantera/trasera). Mensaje de error explícito si no hay cámara/permiso (en vez de quedar congelado).
- Cleanup de tracks al cerrar y al desmontar (evita "pantalla negra" en reintentos).

**Tests**: 7/7 backend pytest verde, frontend E2E 100% verde (camera modal + VideoJobCard renderiza correcto). Cero regresiones.



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
- Templates adicionales para App Builder Pro: Radio Online (streaming continuo + DJ-AI), Feed Vertical estilo TikTok (videos + likes + follows), Landing Peluquería (1 pager + servicios + booking inline), Ecommerce simple (catálogo + carrito + Stripe).

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

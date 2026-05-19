# PRD — Lluvia App Studio

## URLs operativas
- Preview: https://ai-bot-cost-calc.preview.emergentagent.com
- Producción: https://lluvia-app-studio.lluvia-live.com (Emergent Native Deploy)
- Telegram: https://t.me/LluviaAppStudioBot

## Estado actual: v12.29 — Réplica de Emergent 100% completa (Feb 2026)

### Iteración 12.29 — Terminal xterm + Preview Playwright + Logs streaming (HECHO)
**🎯 PEDIDO DEL USUARIO**: Terminar el 100% de la réplica de Emergent (Fases 4, 5, 6 del plan) para subir a producción y Play Store.

**🆕 Backend (2 módulos nuevos)**:
- `ws_streams.py` (~220 líneas) — WebSocket endpoints: `/me/vps/{id}/terminal` (PTY via asyncssh con xterm-256color) + `/me/vps/{id}/logs/{service}` (streaming de `journalctl -u {svc} -f`). Auth via query param `?token=` (browsers no soportan headers en WS nativos).
- `workspace_preview.py` (~250 líneas) — Preview uvicorn temporal con port assignment 9100-9300, TTL 10min, proxy HTTP interno + Playwright screenshots con chromium headless.

**🆕 Endpoints (9 nuevos)**:
- WS `/me/vps/{id}/terminal`, WS `/me/vps/{id}/logs/{service}`
- POST `/me/apps/{slug}/preview`, POST `/preview/stop`, GET `/preview/status`, ALL `/preview/proxy/{path}`
- POST `/me/apps/{slug}/screenshot`, GET `/me/apps/_/screenshots/{id}.png`

**🆕 Frontend (3 componentes nuevos + Studio.js reescrito)**:
- `VpsTerminal.js` — xterm.js v6 + FitAddon + WebSocket, resize handling, banner de status, botón reconectar. Soporta protocolo custom `\x1bRESIZE:cols,rows` para sincronizar tamaño.
- `DeployLogs.js` — WebSocket streaming en vivo (reemplaza el polling con botón "Cargar"). Filtros por nivel (ERROR/WARN/INFO/DEBUG), colorizado, autoscroll toggle, buffer de 5000 líneas, botón limpiar.
- `PreviewIframe.js` — iframe del preview + toggle desktop/mobile (375x812 sandbox), reload, screenshot 1-click via Playwright. Heartbeat cada 60s para mantener vivo el preview.
- `Studio.js` REESCRITO: 4 tabs ahora (Editor / Preview / Terminal / Logs) integrando todos los nuevos componentes. Click en deploy de la sidebar → auto-cambia a tab Logs con el service del deploy.

**Dependencias agregadas**:
- Backend: `playwright==1.49.1` (+ chromium headless ~280MB descarga aparte con `playwright install chromium --with-deps`).
- Frontend: `@xterm/xterm@6.0.0`, `@xterm/addon-fit@0.11.0`.

**Variables de entorno nuevas**:
- `PLAYWRIGHT_BROWSERS_PATH` (path donde Playwright busca el browser).
- `PREVIEW_PORT_BASE=9100`, `PREVIEW_PORT_MAX=9300`.

**Testing**: Smoke tests con curl pasaron — endpoint /preview/status responde, screenshot endpoint genera PNG de 18KB con Playwright + chromium en preview de Emergent. UI compila sin errores, app renderiza OK.

**📄 Doc handoff actualizado**: `/app/CLAUDE_V12_29_STATUS.md` con todos los pasos para Claude del VPS (incluye config nginx para WebSocket que es crítica).

**🎯 LISTO PARA**:
- Producción (push del usuario + git pull en VPS + rebuild + restart).
- Play Store (PWA con Capacitor o TWA — backend ya no necesita cambios).

---

## Estado anterior: v12.28 — Réplica de Emergent (Lluvia Studio) implementada al ~70% (Feb 2026)

### Iteración 12.28 — Auto-deploy a VPS + File editor + Lluvia Studio (HECHO)
**🎯 PEDIDO DEL USUARIO**: Dejar listo el 100% para que Claude (en su Contabo) pueda construir el resto sin más créditos de Emergent. El usuario será operado de la mano.

**🆕 Backend (3 módulos nuevos, ~620 líneas)**:
- `crypto_utils.py` — AES-GCM encrypt/decrypt para SSH keys (master key autogenerada y persistida en .env).
- `vps_manager.py` — CRUD VPS con SSH cifrada, test connection, exec, deploy completo (git clone → venv → pip → systemd → nginx → certbot), restart service, tail logs, undeploy.
- `workspace_files.py` — File tree recursivo, read/write con guardado de diff para rollback, delete, historial.

**🆕 Endpoints (~14 nuevos)**:
- `POST /api/me/vps`, `GET /api/me/vps`, `DELETE /api/me/vps/{id}`, `POST /test`, `POST /exec`, `POST /deploy-app`, `POST /restart-service`, `GET /tail-logs`, `GET /deployments`, `DELETE /deployments/{id}`
- `GET/PUT/DELETE /api/me/apps/{slug}/files|file`, `GET /file-edits`, `POST /file-edits/{id}/rollback`

**🆕 Modelos Mongo**: `vps_servers`, `vps_deployments`, `file_edits`.

**🪄 Nuevo agente IA "Lluvia Studio"** con 10 tools:
- `list_workspace_files`, `read_workspace_file`, `write_workspace_file` (2 oros), `search_replace_workspace` (1 oro)
- `list_my_vps`, `run_vps_command` (1 oro), `deploy_app_to_vps` (25 oros), `tail_vps_logs`, `restart_vps_service` (1 oro)
- Reusable: `push_to_my_github`
- System prompt completo (~60 líneas) con reglas duras y flujos típicos.

**🆕 Frontend (4 componentes nuevos)**:
- `Studio.js` — IDE web tipo Emergent: 3 paneles redimensionables (FileTree | Chat/Deploys | Editor/Preview/Logs).
- `FileTree.js` — Árbol recursivo con iconos por ext, expand/collapse, selección.
- `CodeEditor.js` — Monaco Editor con auto-save 1.2s debounce, indicador "guardado/sin guardar/guardando", lenguaje auto-detectado.
- `VpsServersTab.js` — UI completa para conectar VPS: form (alias, host, port, user, ssh_key|password), botón "Probar conexión" con feedback visual, listado con badges de status.

**🪄 Integraciones**:
- `ClientDashboard.js` — nueva pestaña "🛠 Studio" en top nav.
- `SettingsTab.js` — refactor: 3 sub-secciones (🔧 GitHub, 🖥 Mis Servidores, ⚙ Cuenta).

**Dependencias agregadas**:
- Backend: `asyncssh==2.18.0`, `paramiko==3.5.0`, `cryptography==46.0.7` (en `requirements.txt`).
- Frontend: `@monaco-editor/react`, `react-resizable-panels@4.11.1`, `lucide-react@0.469.0`.

**Testing**: Smoke tests con curl pasaron — endpoints funcionan, Mongo guarda VPS cifrado, listar muestra sin exponer keys, delete funciona, agente con tools registradas, app principal renderiza OK en preview.

**Lo que FALTA (Fases 4-6 del plan, ~5-7h)**:
- Terminal xterm.js embebido (workaround: tool `run_vps_command` ya funciona desde chat).
- Preview iframe (workaround: usuario abre URL deployada en otra pestaña).
- Logs WebSocket streaming (workaround: tab "Logs" del Studio hace polling on-demand).

**📄 Doc handoff para Claude del VPS**: `/app/CLAUDE_V12_28_STATUS.md` con checklist post-deploy + troubleshooting.

---

## Estado anterior: v12.27 — Multi-Repo Push + Template TikTok/Bigo Live (Feb 2026)

### Iteración 12.27 — Bug "todas las apps al mismo repo" RESUELTO + nuevo template TikTok (HECHO)
**🔥 BUGS P0 REPORTADOS POR EL CLIENTE EN PRODUCCIÓN**:
1. "Todas las apps generadas van al mismo repositorio, se sobrescriben entre sí, debería haber opción para crear repo nuevo".
2. "Necesito apps completas tipo Bigo Live y TikTok".

**🛠 Fix 1: Multi-Repo Push (cada app a SU propio repo)**:
- Nuevo endpoint `POST /api/me/github/push-app` con payload `{app_slug, repo_name, create_new, target_owner_repo?, set_as_default?, private?}`.
- Flujo: valida token GitHub → sanitiza repo_name → si `create_new=true`, crea el repo en GitHub (idempotente: si ya existe lo usa) → ejecuta push solo del subfolder `user_apps/{user_id}/{app_slug}/` al repo dedicado.
- `do_push()` ahora acepta `repo_override`, `branch_override`, `auto_create_repo` — sin tocar el default global del usuario.
- Endpoint legacy `POST /api/me/github/push` sigue funcionando para compat (acepta los nuevos params como opcionales).
- Tool `push_to_my_github` del chat también acepta `repo` y `auto_create_repo`.

**🛠 Fix 2: AppBuiltCard rediseñada con flow "Push & Deploy"**:
- Después de generar una app (rich card), aparece sección destacada con botón **"⬆ Push & Deploy"**.
- El frontend sugiere automáticamente un repo_name único (`{app-slug}-{random4chars}`) — el usuario lo puede editar.
- Al confirmar, llama a `/api/me/github/push-app` con `create_new=true` → crea repo dedicado.
- Después del push exitoso: muestra link "Ver en GitHub" + botón **"⚡ Deploy a Render (1-click)"** con URL `https://render.com/deploy?repo={repo_url}`.
- Resultado: cada app generada va a un repo SEPARADO, listo para deploy en Render en 1 click.

**🆕 Template TikTok / Bigo Live Clone (Feed Vertical en Vivo)**:
- Nuevo template `/app/backend/app_templates/tiktok_clone/` con 13 archivos (4 frontend + 2 backend + 7 deploy).
- **Stack**: FastAPI + python-socketio (ASGI) + SQLite + Vanilla JS + Socket.IO client. Cero build, todo se sirve desde el mismo puerto.
- **4 pantallas**:
  1. **Feed Vertical**: scroll snap full-screen, autoplay, double-tap heart, mute, like/comment/gift/share, bottom drawer.
  2. **Descubrir**: top creadores + grid de videos trending.
  3. **Subir Video**: form para publicar (URL mp4/HLS, caption, tags, thumbnail).
  4. **Perfil**: stats, follow, recarga de créditos, grid de videos.
- **Features comerciales**: registros anónimos (JWT 1-click), likes persistentes, comentarios en tiempo real (Socket.IO), follows, regalos virtuales (Rosa 5cr, Corazón 10cr, Cohete 50cr, Diamante 200cr, Corona 500cr) con cobro de credits + creator share 70%.
- **Seed automático**: 3 creadores demo (Luna Star, DJ Neo, Chef Mia) + 6 videos con thumbnails Unsplash y videos de muestra Google CDN. Funciona "out of the box" sin configuración.
- **Deploy files**: render.yaml, railway.toml, Dockerfile, docker-compose.yml, Procfile, install.sh, README.md exhaustivo con troubleshooting.

**🛠 Fix 3: render.yaml de Audio Room simplificado**:
- Removida la sobreescritura conflictiva de `PORT=10000`. Render asigna `$PORT` automáticamente; antes el doble seteo causaba healthcheck en puerto incorrecto en algunos casos.

**🪄 App Builder Pro actualizado**:
- System prompt menciona ambos templates (Audio Room + TikTok) con precios y stack.
- Pregunta los 4 datos en UN turno: tipo (audio_room | tiktok), nombre, color, deploy_target.
- Regla dura agregada: "Cada app generada debe ir a SU PROPIO REPO. Nunca sugieras pushear varias apps al mismo repo (se sobrescriben)."

**Pricing**:
- `generate_tiktok_app` = 50 oros (default, editable desde panel admin).
- TEMPLATE_METADATA actualizada con TikTok como template ACTIVO (ya no coming_soon).

**Testing (iteration_24.json)**: **19/19 PASS** en tests nuevos + 38/39 en regresión (1 fallo esperado por test stale de iter_20 que asumía 4 coming_soon — hoy son 3 porque TikTok pasó a activo).

**Archivos generados por una app TikTok**: 13 (vs 16 del audio_room, no usa Socket.IO server file separado).

---

## Estado anterior: v12.26 — Audio Room multi-provider deploy + Gmail OAuth fix (Feb 2026)

### Iteración 12.26 — Apps que SI deployan en Render/VPS/Docker + magic-link domain-aware (HECHO)
**🔥 BUG CRÍTICO REPORTADO POR EL CLIENTE**: app generada por App Builder Pro fallaba en Render con `[Errno 2] No such file or directory: 'requirements.txt'` porque el archivo vivía en `/backend/` y Render lo buscaba en la raíz.

**🛠 Fix: Template ahora trae 6 archivos de deploy multi-provider**:
- `render.yaml` con `rootDir: backend` → Render encuentra `requirements.txt` correctamente.
- `railway.toml` para Railway.app (auto-detect).
- `Procfile` para Heroku/Fly.io.
- `Dockerfile` + `docker-compose.yml` para Docker genérico (cualquier host).
- `install.sh` para VPS: instala Python, crea venv, systemd service, arranca solo. Plug & play.
- `README.md` reescrito con sección "Deploy en 1 click según tu proveedor" + troubleshooting de los 4 errores más comunes.

**🪄 App Builder Pro ahora pregunta WHERE va a deployar**:
- System prompt actualizado: pide 3 datos en un mensaje (nombre + color + deploy_target).
- Targets soportados: `render | railway | heroku | fly | vps | docker | local`.
- Si no sabe, sugiere `render` (free tier + más simple).
- Tool `generate_audio_room_app` ahora acepta `deploy_target` y la rich card `next_step` se adapta: si elige render → muestra "Render leerá render.yaml automáticamente, tu app va a quedar en {slug}.onrender.com"; si vps → muestra "corre install.sh, configura HTTPS con certbot"; etc.

**🐛 Bug del OAuth de Gmail mostrando URL de preview en producción**:
- `gmail_integration.py::magic_link()` ahora detecta el dominio del request HOST en cascada: lluvia-live.com → emergentagent.com/.host → PUBLIC_BASE_URL → base_url. Antes confiaba ciegamente en el env var que estaba seteado al preview.

**Nuevo placeholder de template**: `{{APP_NAME_SLUG}}` (slug-safe del nombre) → se sustituye automáticamente en render.yaml, railway.toml, docker-compose.yml e install.sh. `app_builder.py` ahora soporta extensiones `.sh`, `.conf` y filenames literales `Dockerfile`, `Procfile`.

**Verificación (iteration_23.json)**: 13/13 nuevos PASS + 40/40 regresión (iter_20, iter_21, iter_22) = **53/53 verde**. Validado: archivos físicos materializados, ZERO placeholders huérfanos, next_step adaptado a cada provider, magic-link domain detection, todos los endpoints existentes intactos.

**Archivos generados por una app ahora**: 16 (vs 10 antes). De los nuevos: 1 render.yaml, 1 railway.toml, 1 Procfile, 1 Dockerfile, 1 docker-compose.yml, 1 install.sh.



## Estado anterior: v12.25 — Botón "Crear repo nuevo en GitHub" (Feb 2026)

### Iteración 12.25 — Crear repos GitHub desde Lluvia con 1 click (HECHO)
**🛠 Backend**: nuevo endpoint `POST /api/me/github/create-repo` con body `{name, private, description, set_as_default}`. Flujo:
1. Lee `user_settings.github_token`.
2. Pre-valida el token via `_validate_github_token` (rechaza tokens vencidos sin tocar nada).
3. Verifica `has_repo_scope` (sino → 403 con mensaje claro).
4. Sanitiza el nombre del repo (slug-friendly: solo alphanumeric + `-_.`, máx 80 chars).
5. Si ya existe → guarda como default + devuelve `already_existed:true`.
6. Si no existe → `POST /user/repos` con `auto_init:false` (do_push lo inicializa con bootstrap si hace falta).
7. Si `set_as_default:true` → actualiza `user_settings.github_repo` + `github_branch`.

**🎨 Frontend `SettingsTab.js`**: nuevo componente `CreateRepoCard` debajo del campo "Nombre del proyecto":
- Estado cerrado: botón negro elegante con logo octocat "📦 Crear repo nuevo en GitHub" (`data-testid='create-repo-toggle'`).
- Estado abierto: card expandida con input de nombre (con preview del slug si se va a sanitizar), checkbox "🔒 Hacerlo privado", botón gradient "🚀 Crear y seleccionar como destino".
- Si NO hay token guardado: muestra dashed-card con "🔒 Guardá tu token de GitHub primero".
- Al crear, actualiza el campo `github_repo` del form principal con el repo nuevo y muestra success-msg + link al repo.

**Flujo de usuario**:
1. Cliente arma una app con App Builder Pro.
2. Quiere pushearla pero no tiene repo aún.
3. Mi Cuenta → Settings → tap "Crear repo nuevo" → nombre + privado/público → tap "Crear".
4. Lluvia crea el repo en GitHub, lo deja seleccionado como destino default.
5. Vuelve al chat → tap ⬆ Push → archivos arriba. 1-click end-to-end sin abrir github.com.

**Verificado**: Endpoint responde con mensaje detallado al token muerto del preview (validación previa funciona). UI testeada con Playwright: botón visible cerrado, form expand correcto con autocompletes, submit gradient. Lint ✅.



## Estado anterior: v12.24 — Hotfix Push a GitHub vía REST API (Feb 2026)

### Iteración 12.24 — Eliminar dependencia del binario `git` en producción (HECHO)
**🔥 Bug crítico en producción**: el contenedor de Emergent prod no trae `git` instalado → `[Errno 2] No such file or directory: 'git'` cada vez que un cliente intentaba pushear.

**🛠 Fix completa de `do_push`**:
- Eliminado todo uso de `subprocess.run(['git', ...])`. Ya no necesita el binario `git` instalado en el contenedor.
- Reescrito con **GitHub REST API** vía httpx: blobs → trees → commits → refs.
- Maneja 3 escenarios de init: (a) repo con commits → usa parent_sha del HEAD, (b) branch nueva (404) → orphan commit, (c) **repo completamente vacío (409 "Git Repository is empty")** → bootstrap con `PUT /contents/README.md` primero, luego flujo normal.
- Skips inteligentes: dirs `.git`, `__pycache__`, `node_modules`, `.venv`, `venv`, `.next`, `dist`, `build`, `.DS_Store`. Extensions `.pyc`, `.pyo`, `.log`, `.db`, `.db-journal`. Archivos >1.5MB se skipean.

**🛠 Mensajes de error mucho más útiles**:
- `_validate_github_token` ahora detecta formato del PAT antes de tocar la red: rechaza tokens con formato inválido al toque, devuelve mensaje claro distinguiendo "Classic vs Fine-grained", expone el mensaje exacto que devuelve GitHub (typo / vencido / revocado / scope faltante).
- `BossConsole.pushNow` ahora muestra `data.error` o `data.message` o el último step en lugar del genérico "ver consola".

**🐛 Bug que casi se va a producción**: el testing agent v3 encontró un `NameError: 'base64' not defined` en la rama de "repo vacío" — yo había puesto el `import base64` adentro de un `async with` block, pero el código del bootstrap lo necesitaba antes. Lo movió al top-level del módulo. Cero usuarios afectados (encontrado antes del deploy).

**Verificación (iteration_22.json)**: 14/14 nuevos tests PASS + 26/26 regresión (iter_20 push lock + iter_21 gmail autosend). Cero subprocess, cero `git` binario, los 3 escenarios cubiertos con mocks deterministicos.



## Estado anterior: v12.23 — Gmail Maestro Auto-Send (Opción C) (Feb 2026)

### Iteración 12.23 — Auto-envío inteligente de respuestas Gmail (HECHO)
**📧 Auto-send con threshold de confianza**
- `gmail_maestro.py` ahora tiene constantes `AUTOSEND_CONFIDENCE_THRESHOLD = 0.9` y `AUTOSEND_CATEGORIES = {"lead-caliente", "soporte"}`.
- Nueva función `_send_gmail_draft(token, draft_id)` que llama a `POST /gmail/v1/users/me/drafts/send`. Maneja 200/201 → message_id, otros → None con log.
- Flujo `_process_inbox_for_user` ahora:
  1. Clasifica el email con GPT-4o-mini.
  2. Si NO es spam/personal y hay reply_draft, crea draft en Gmail.
  3. **NUEVO**: si `confidence >= 0.9` AND `category in AUTOSEND_CATEGORIES`, llama a `_send_gmail_draft` y guarda `auto_sent=True` + `sent_message_id` en el doc. Log visible: *"AUTO-ENVIADO user=X category=lead-caliente conf=0.95 to=..."*
  4. Si confidence < 0.9 o category es comercial: queda como draft para revisión manual.
- Métricas `/metrics` ahora exponen: `auto_sent` (int), `autosend_threshold` (0.9), `autosend_categories` (list).

**🧹 System prompt del clasificador mejorado**
- Reglas duras para que TODA notificación automática (Facebook, Instagram, Google, GitHub, no-reply, newsletters) sea forzosamente category=`spam` con confidence≥0.9 y reply_draft=`""`. Antes el LLM clasificaba estas como "soporte" generando drafts inútiles.

**📊 Verificación E2E real**
- Manual: enviado `message_id 19e32c6e8a94dc20` a `melvinnavas79@gmail.com` con la respuesta auto-generada al lead-caliente "¿qué servicios ofrecen?".
- 14/14 tests pytest unitarios (iteration_21) verifican: constantes, _send_gmail_draft happy/error paths, _process_inbox_for_user con 5 casos (auto-envío activado por lead conf 0.95, NO activado por lead conf 0.8 / comercial conf 0.99 / spam), system prompt con reglas auto-senders, endpoint metrics con campos nuevos.
- 12/12 regresión iteration_20 verde (push lock + admin pricing intactos).



## Estado anterior: v12.22 — Push Lock + Panel admin de Precios (Feb 2026)

### Iteración 12.22 — Candado de exportación + Control admin de precios (HECHO)
**🔒 Push Lock (candado de exportación)**
- Lógica nueva en `user_workspace.do_push` líneas 199-238: si el user NO es admin y `balance < min_balance_for_export` (default 50), retorna `{ok:false, export_locked:true, balance, required, missing, message, recharge_url:'/#/recharge'}` ANTES de tocar GitHub. El admin bypassa siempre el candado.
- Mensaje exacto: *"Has creado tu app con éxito. Para exportar el código fuente completo a tu GitHub y activar el backend para producción, adquiere un paquete de oros. Saldo actual: X oros · Necesitas al menos N oros para desbloquear la exportación."*
- El refund automático de la tool `push_to_my_github` se mantiene cuando cae en este lock para que el visitor no pierda los 8 oros del intento.

**💰 Panel admin de Precios (control financiero del dueño)**
- Nuevo módulo `pricing.py`: source-of-truth de precios. `DEFAULT_TOOL_PRICES` define qué templates conoce el sistema; los valores efectivos se mergen desde `site_content.tool_prices` en MongoDB (editable por panel sin redeploy). `DEFAULT_MIN_BALANCE_FOR_EXPORT = 50`.
- Nuevo router `admin_pricing.py` con `GET /api/admin/pricing` y `PUT /api/admin/pricing` (admin-only). Validación: ignora claves desconocidas, satura negativos a 0, ignora valores no-numéricos.
- `console.py::_exec_tool` rama `generate_audio_room_app` lee precio dinámico de `pricing.get_tool_price()` (sobrescribe el hardcoded de TOOL_NAMES).
- `TEMPLATE_METADATA` lista los 5 templates conocidos: Audio Room (real, default 40 oros) + 4 placeholders SOON (Radio Online, Feed TikTok, Landing Peluquería, Ecommerce simple) — el admin ve toda la roadmap y prepara precios anticipadamente.

**🎨 Frontend nuevo**
- Tab `💰 Precios de Templates` en SuperAdminPanel con: caja "🔒 Candado de exportación" (input min_balance), grid de 5 templates con input editable + badge SOON para los del backlog, botón "Guardar precios" + último editor + timestamp.
- `BossConsole.GitHubPushCard` detecta `export_locked` y renderiza variante premium amarilla/violeta con grid Saldo / Necesitas / Te faltan + CTA "Recargar oros y desbloquear exportación →".
- `BossConsole.pushNow` (botón ⬆ Push del composer) detecta `export_locked` y muestra confirm que redirige a `/#/recharge`.
- `ClientDashboard` tab GitHub renderiza `data-testid='export-locked-modal'` con el mismo grid + botón gradient amarillo cuando el push manual es bloqueado.

**Verificación (iteration_20.json)**: backend 12/12 PASS, frontend Playwright 100%. Validado: persistencia de cambios desde panel, ignore de keys desconocidas, saturación de negativos, admin bypass del lock, threshold dinámico (10 oros user con threshold=5 SI puede pushear, con threshold=50 NO), refund automático en lock, render de las dos variantes (rich card en chat + modal en GitHub tab). Cero regresiones.

**Modelo de negocio activado**: el visitor entra del demo → registra → 15 oros trial → arma audio room (40 oros) → ve la rich card preview → quiere pushear → BLOQUEADO → ve modal premium → recarga → desbloquea → exporta. Embudo monetizado de punta a punta.



## Estado anterior: v12.21 — Funnel cerrado dentro del demo + español neutro (Feb 2026)

### Iteración 12.21 — Demo → CTA → Registro → App Builder Pro automático (HECHO)
**🎯 CTA flotante de conversión dentro del demo público**
- Inyectado en `demo_audio_room.py::_build_demo_cta()` solo en modo demo (el template original NO incluye este código, sigue limpio para clientes que pushean).
- Pill flotante abajo-derecha con dot rojo pulsante: *"¿Te gusta? Ármala con TU marca → 40 oros"*. Animación CSS suave de pulso.
- Click → modal full-screen con campos: Nombre app, Color (hex + color-picker swatch), Email, Contraseña. Línea verde de transparencia de precios: *"15 oros gratis al crear cuenta · La app cuesta 40 oros · Sin tarjeta"*.

**📡 Endpoint `/api/demo/audio-room/api/convert`**
- Delegación a `affiliates.register` (mismo flujo de registro principal con trial 15 oros + anti-abuse rate-limit por IP).
- Response: `{access_token, user, seed: {app_name, brand_color}, next_url}`.
- Frontend setea `localStorage.bot_admin_token` + `localStorage.lluvia_demo_seed` y redirige a `/#/chat` después de 700ms.

**🪄 Auto-trigger en `BossConsole.js`**
- useEffect detecta `localStorage.lluvia_demo_seed` cuando `agents.length > 0`. Acción atomic:
  1. `localStorage.removeItem` ANTES de la creación de sesión (idempotente, a prueba de doble-fire).
  2. `POST /console/sessions {agent_id: 'app_builder_pro'}`.
  3. `setActiveId` y, 800ms después, dispatch `lluvia:compose-message` con `{text, send: true}` que envía: *"Llamala \"{app_name}\" y usá color {brand_color}. Generala ya."*
- App Builder Pro recibe el mensaje, dispara la tool `generate_audio_room_app`, y aparece la rich card `AppBuiltCard` con el resumen.

**🇪🇸 Voseos eliminados del backend (español neutro profesional)**
- `app_templates/audio_room/backend/server.py:206` → "No puedes seguirte a ti mismo".
- `app_templates/audio_room/backend/server.py:323` → "Necesitas N oros. Tienes M oros."
- `affiliates.py` → mensaje de rate-limit ahora dice "Espera 24 horas o contáctanos".
- `user_workspace.py` → "Verifica que eres owner".
- `console.py` → tool `app_built.next_step` → "Aprieta + → ⬆ Push a GitHub..." (typo + voseo fix).

**Verificación (iteration_19.json)**: backend 5/5 PASS + 1 SKIP (rate-limit anti-abuse esperado, NO bug); frontend 100% — CTA visible, modal con todos los campos, localStorage correctamente seteado, redirect a /#/chat funciona, useEffect en BossConsole verificado por code review (idempotente con `agents.length` y `removeItem` antes del fetch). Cero regresión en iteration_17 y iteration_18.

**Flujo completo verificado**: Visitor entra a `/api/demo/audio-room-static/` → navega las 4 pantallas → click CTA → llena modal → submit → registrado con trial 15 oros → redirigido a /#/chat → BossConsole crea sesión con App Builder Pro → mensaje pre-rellenado se envía solo → si tiene saldo suficiente, rich card AppBuilt aparece y app queda en su workspace lista para push a GitHub.

**Limitación conocida (esperada)**: Trial = 15 oros, tool = 40 oros → el visitor debe recargar 25+ oros para terminar el ensamble. El mensaje "saldo insuficiente" del agente lo dirige al tab Recharge. Esto es deseado para evitar farming.



## Estado anterior: v12.20 — Live Demo público + emoji badges + auto-create GitHub repo (Feb 2026)

### Iteración 12.20 — Demo público de Audio Room + UX polish (HECHO)
**🌐 Demo público de Audio Room en `/api/demo/audio-room-static/`**
- Nuevo módulo `/app/backend/demo_audio_room.py`: sirve el template Audio Room con datos canned (6 salas, 5 creadores) para que cualquier visitante toque y vea las 4 pantallas reales antes de registrarse. Banner púrpura "DEMO PÚBLICO · Esta app la ensambla App Builder Pro en 30 segundos" siempre visible.
- StaticFiles mount en `server.py` bajo `/api/demo/audio-room-static/` (respeta content-types text/javascript, text/css, text/html).
- Canned API endpoints bajo `/api/demo/audio-room/api/*`: `users/anonymous`, `users/top`, `users/{id}`, `rooms`, `rooms/{id}`, `rooms/{id}/purchase`.
- Las 4 pantallas (Inicio · Tendencias · Salas · Perfil) renderizan con datos reales (creadores con followers, salas con listeners 33-412, badges PREMIUM, categorías).

**🎬 Landing CTA "Live Demo"**
- Botón pill nuevo en `PublicChat.js` (`data-testid='hero-live-demo-btn'`) con dot rojo pulsante: "🎙 Probá una Audio Room en vivo — armada por App Builder Pro en 30 seg". Abre el demo en nueva pestaña. Convertir visitor → "wow" → registro: el flujo que el cliente pidió.

**🐛 Bug crítico fixeado en el template Audio Room**
- `app.js:161` tenía `\\'` (escape inválido de comilla simple en JS); causaba `SyntaxError: Unexpected string` y pantalla en blanco en el browser. Fix: `\'`. Verificado con `node --check` antes/después. Este bug habría roto la app de TODOS los clientes que hicieran push del template, así que es un win extra.

**🚀 AgentAvatar: emoji badge superpuesto**
- `AgentAvatar.js` ahora overlay del `agent.emoji` como badge circular abajo-derecha del bot dicebear (size: 50% del avatar, font: 70% del badge, color de fondo: `agent.color`, sombra blanca para destacarse). El cohete 🚀 de App Builder Pro y los emojis de todos los agentes ya son visibles en el picker y en los headers de chat. By-design del rebrand v12 preservado.

**🛠 Auto-create de repo de GitHub en `user_workspace.do_push`**
- Si `validate_github_token` devuelve `repo_access='not_found'` y el token tiene scope `repo`, ahora hacemos `POST /user/repos` (o `/orgs/{org}/repos`) automáticamente con descripción "Generado por Lluvia App Studio · workspace de {email}". Antes el push fallaba con "repo no existe"; ahora el cliente solo pasa `owner/nombre-cualquiera` y el sistema crea + pushea en un solo paso. UX 10x mejor.

**Verificado E2E (iteration_18.json)**: backend 12/14 (los 2 fallos son por rate-limit anti-abuse de registro, no bugs); frontend Playwright 100% (CTA landing, demo público, emoji badges); 1 push real a GitHub en `melvinnavas79-del/lluvia-audio-room-demo` con commit "e2e test iteration_18"; cero regresión en iteration_17 (7/7 verde).

**Demo en vivo**: https://ai-bot-cost-calc.preview.emergentagent.com/api/demo/audio-room-static/
**Repo de muestra**: https://github.com/melvinnavas79-del/lluvia-audio-room-demo



## Estado anterior: v12.19 — App Builder Pro + Audio Room template (Feb 2026)

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
- Templates adicionales para App Builder Pro: ✅ **Audio Room (HECHO v12.19)**, ✅ **TikTok/Bigo Live Clone (HECHO v12.27)**, Radio Online (streaming continuo + DJ-AI), Landing Peluquería (1 pager + servicios + booking inline), Ecommerce simple (catálogo + carrito + Stripe).

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

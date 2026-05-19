# 🏗 Blueprint: Réplica de Emergent dentro de Lluvia App Studio

> **Para Claude (en VPS Contabo `207.180.235.220`)**.
> El dueño de Lluvia quiere construir, **dentro de su propio SaaS**, una réplica exacta de la experiencia de Emergent: chat con agente IA que crea apps, tool cards visuales, file tree, terminal embebido, preview en vivo, push a GitHub, deploy a VPS — todo con el mismo look & feel.
>
> Este documento es un **plano de construcción** que vos (Claude) podés ejecutar autónomamente en el VPS, o que el usuario puede llevar al preview de Emergent para que el agente lo construya allá y haga push. **Cualquiera de los dos caminos funciona** — pero recomendamos: tú haces el setup de infra (SSH, systemd, deploy), Emergent hace los cambios de código.

---

## 📑 Índice

1. [Visión general y alcance](#1-visión-general-y-alcance)
2. [Stack técnico (no inventar, reutilizar lo que ya hay)](#2-stack-técnico)
3. [Modelos de datos nuevos](#3-modelos-de-datos-nuevos)
4. [Backend: endpoints a crear](#4-backend-endpoints-a-crear)
5. [Frontend: componentes a crear](#5-frontend-componentes-a-crear)
6. [Agente IA "Emergent Replica" — system prompt + tools](#6-agente-ia-emergent-replica)
7. [Auto-deploy a VPS desde el chat (SSH + systemd)](#7-auto-deploy-a-vps-desde-el-chat)
8. [Fases de implementación (orden estricto)](#8-fases-de-implementación)
9. [Testing y rollback](#9-testing-y-rollback)
10. [Checklist final antes de mostrar al usuario](#10-checklist-final)

---

## 1. Visión general y alcance

### Qué tiene Emergent que queremos replicar

| Feature de Emergent | Réplica en Lluvia | Prioridad |
|---|---|---|
| Chat con agente IA streaming | ✅ Ya existe (`BossConsole.js`) — extender | P0 |
| Tool cards (PayPal, GitHub push, App Built, video Sora) | ✅ Ya existe — agregar nuevas | P0 |
| Sidebar con threads/sesiones | ✅ Ya existe | P0 |
| **File tree del workspace generado** | ❌ Crear | **P0** |
| **Terminal embebido (xterm.js) con SSH al VPS** | ❌ Crear | **P0** |
| **Preview en vivo de la app generada (iframe)** | ❌ Crear | **P1** |
| **Editor de código inline (Monaco)** | ❌ Crear | **P1** |
| **Logs en streaming del deploy** | ❌ Crear | **P1** |
| **Visualizador de diff de cambios** | ❌ Crear | **P2** |
| Push a GitHub + crear repo nuevo | ✅ v12.27 ya lo hace | ✅ |
| Deploy a VPS / Render / Railway | ⚠ Parcial — falta SSH automático | **P0** |
| Screenshots automáticos para validar | ❌ Crear (puppeteer + endpoint) | P2 |
| Rollback de cambios | ❌ Crear | P2 |
| Multi-agente especializado | ✅ Ya existe (Sexólogo, App Builder, etc.) | ✅ |

### Qué NO replicar (consciente)

- Pricing/billing de Emergent (Lluvia tiene su propio sistema de oros + PayPal).
- Workflow de auto-commit cada paso (en su lugar, commits manuales con mensaje).
- El "skill" de Emergent de modificar archivos del propio agente — Lluvia es un SaaS, no debe permitir que clientes editen `console.py`.

---

## 2. Stack técnico

**REGLA DURA**: NO inventar dependencias nuevas. Usar lo que ya está en `package.json` y `requirements.txt` siempre que sea posible. Solo agregar libs si están explícitamente listadas abajo.

### Frontend nuevas dependencias

```bash
cd /opt/lluvia/frontend
yarn add monaco-editor @monaco-editor/react   # editor de código inline
yarn add xterm xterm-addon-fit                 # terminal embebido
yarn add react-resizable-panels                # layout split-pane tipo Emergent
yarn add diff2html                              # visualizador de diff
```

### Backend nuevas dependencias

```bash
cd /opt/lluvia/backend
pip install paramiko==3.5.0       # SSH client (auto-deploy a VPS)
pip install asyncssh==2.18.0      # SSH async (mejor para streaming logs)
pip install cryptography==44.0.0  # cifrado de claves SSH en DB
pip freeze > requirements.txt
```

### Lo que YA está y vamos a aprovechar

- **FastAPI + python-socketio** → para WebSockets (terminal y logs streaming).
- **MongoDB Motor** → para guardar VPS configs cifradas.
- **OpenAI / Claude / Gemini via Emergent Integrations** → ya wired en `console.py`.
- **httpx** → ya se usa para GitHub REST API.

---

## 3. Modelos de datos nuevos

Agregar estas colecciones a Mongo (crear índices en startup como ya se hace en `server.py`):

### `vps_servers`
```python
{
  "_id": ObjectId(...),
  "id": str(uuid.uuid4()),
  "user_id": "...",
  "name": "Contabo Principal",     # alias visible
  "host": "207.180.235.220",
  "port": 22,
  "username": "root",
  "ssh_key_encrypted": "...",       # AES-GCM cifrado con SECRET_KEY del .env
  "auth_method": "ssh_key",         # 'ssh_key' | 'password' (key recomendado)
  "os_distro": "ubuntu_22",         # auto-detectado en test connection
  "status": "connected",            # connected | error | unknown
  "last_check": "2026-02-19T18:00:00Z",
  "created_at": "...",
  "updated_at": "..."
}
```

Índice: `(user_id, host)` único para no duplicar.

### `vps_deployments`
```python
{
  "id": str(uuid.uuid4()),
  "user_id": "...",
  "vps_id": "...",
  "app_slug": "mi-tiktok",
  "repo_url": "https://github.com/user/mi-tiktok",
  "domain": "tiktok.midominio.com",       # opcional
  "status": "running",                    # pending | building | running | failed | stopped
  "port": 8001,                            # puerto interno del systemd service
  "service_name": "lluvia-mi-tiktok",     # nombre del systemd unit
  "https_enabled": False,
  "deploy_log_url": "/api/me/vps/deployments/{id}/logs",   # endpoint streaming
  "started_at": "...",
  "ended_at": "...",
  "error": null
}
```

### `file_edits` (historial de cambios para rollback)
```python
{
  "id": str(uuid.uuid4()),
  "user_id": "...",
  "app_slug": "mi-tiktok",
  "file_path": "backend/server.py",
  "diff": "...",          # unified diff
  "applied_by": "agent",  # agent | user
  "rollback_token": "...", # para deshacer
  "created_at": "..."
}
```

---

## 4. Backend: endpoints a crear

Crear archivo nuevo `/opt/lluvia/backend/vps_manager.py` siguiendo el patrón de `user_workspace.py`:

### 4.1 VPS CRUD

```python
# POST   /api/me/vps                       Crear conexión SSH a un VPS
# GET    /api/me/vps                       Listar mis VPS
# DELETE /api/me/vps/{vps_id}              Borrar
# POST   /api/me/vps/{vps_id}/test         Validar conexión SSH (returns os_distro, free_disk, etc.)
# POST   /api/me/vps/{vps_id}/exec         Ejecutar comando shell (privilegiado, solo admin o owner)
#                                          → devuelve {stdout, stderr, exit_code}
```

### 4.2 Deploy a VPS

```python
# POST /api/me/vps/{vps_id}/deploy-app
# Body: {app_slug, repo_url, domain?, env_vars?}
# Acciones:
#   1. SSH al VPS
#   2. git clone repo_url /opt/lluvia-apps/{app_slug}
#   3. cd /opt/lluvia-apps/{app_slug}/backend && python -m venv venv
#   4. venv/bin/pip install -r requirements.txt
#   5. Crear /etc/systemd/system/lluvia-{app_slug}.service
#   6. systemctl daemon-reload && systemctl enable + start
#   7. Si domain: configurar nginx vhost + certbot
#   8. Guardar registro en vps_deployments
#   9. Devolver {deployment_id, status, url}
```

### 4.3 Streaming de logs (WebSocket)

```python
# WS /api/me/vps/{vps_id}/logs/{service_name}
# Stream de `journalctl -u {service_name} -f` vía SSH
# Cliente recibe líneas en tiempo real
```

### 4.4 Terminal embebido (WebSocket PTY)

```python
# WS /api/me/vps/{vps_id}/terminal
# Abre un PTY interactivo vía SSH (asyncssh.start_session interactive)
# Cliente envía keystrokes, server reenvía a SSH
# Server emite output, cliente lo pinta en xterm.js
```

### 4.5 File operations en el workspace

```python
# GET  /api/me/apps/{app_slug}/files          → tree completo {name, path, type, size}
# GET  /api/me/apps/{app_slug}/file?path=...  → contenido del archivo
# PUT  /api/me/apps/{app_slug}/file           → escribir (body: {path, content})
#                                                Auto-guarda diff en file_edits
# POST /api/me/apps/{app_slug}/preview        → arranca un proceso uvicorn temporal
#                                                en el contenedor del backend
#                                                y devuelve URL de preview (5 min TTL)
```

### 4.6 Screenshot del preview

```python
# POST /api/me/apps/{app_slug}/screenshot
# Body: {url, viewport: {w, h}}
# Backend usa playwright (instalado en el container) para tomar screenshot
# Guarda en /tmp/screenshots/{uuid}.png y devuelve URL temporal
```

---

## 5. Frontend: componentes a crear

Crear nueva ruta `#/studio` que sea la "consola Emergent" de Lluvia.

### 5.1 Layout (`/frontend/src/components/Studio.js`)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Header: agentes, sesión actual, balance oros                        │
├──────────────┬─────────────────────┬────────────────────────────────┤
│              │                     │                                │
│  File Tree   │  Chat (existing     │  Preview iframe                │
│  (collapse)  │  BossConsole panel) │  + Tabs: Preview / Editor /    │
│              │                     │    Terminal / Logs             │
│              │                     │                                │
│ Components:  │  - Tool cards       │  Components:                   │
│ - FileTree   │  - Composer         │  - PreviewIframe               │
│              │  - Push & Deploy    │  - CodeEditor (Monaco)         │
│              │                     │  - VpsTerminal (xterm)         │
│              │                     │  - DeployLogs (stream)         │
└──────────────┴─────────────────────┴────────────────────────────────┘
```

Usa `react-resizable-panels` para que el usuario pueda redimensionar.

### 5.2 Componentes específicos

**`FileTree.js`** — Sidebar de archivos del workspace:
- Llama a `GET /api/me/apps/{slug}/files`
- Recursivo, expand/collapse
- Click en archivo → abre tab "Editor" con el contenido
- Iconos por tipo (`.py` python, `.js` js, `.css` css, etc.)
- Botón "+" para crear archivo nuevo
- Right-click → eliminar, renombrar, descargar

**`CodeEditor.js`** — Wrapper de Monaco:
```jsx
import Editor from "@monaco-editor/react";
<Editor
  height="100%"
  language="python"
  value={fileContent}
  theme="vs-dark"
  options={{ minimap: { enabled: false }, fontSize: 13 }}
  onChange={(v) => saveFile(path, v)}
/>
```
- Auto-save con debounce 1s
- Indicador "guardado / guardando" arriba a la derecha
- Botón "Pedirle al agente que arregle esto" → manda el archivo al chat con prompt

**`VpsTerminal.js`** — Terminal embebido:
```jsx
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";

useEffect(() => {
  const term = new Terminal({ theme: { background: "#0F0F12" } });
  const fit = new FitAddon();
  term.loadAddon(fit);
  term.open(containerRef.current);
  fit.fit();

  const ws = new WebSocket(`${WS_URL}/api/me/vps/${vpsId}/terminal`);
  ws.onmessage = (e) => term.write(e.data);
  term.onData((d) => ws.send(d));
}, [vpsId]);
```

**`DeployLogs.js`** — Logs en streaming:
- WebSocket a `/api/me/vps/{id}/logs/{service_name}`
- Auto-scroll al final
- Filtros: ERROR | WARNING | INFO | DEBUG
- Botón "Pause autoscroll"

**`PreviewIframe.js`** — Vista previa de la app generada:
- Recibe URL del deploy o un preview temporal
- Botón "🔄 Reload" + "📱 Mobile view" (resize a 375px)
- "📸 Tomar screenshot" → llama al endpoint y muestra preview con timestamp
- Indicador "Online | Offline" con health check cada 30s

### 5.3 Nuevas tool cards en `BossConsole.js`

Estas se renderizan dentro del chat cuando el agente las invoca:

**`VpsConnectedCard`** — Confirma conexión SSH OK:
```
🖥 Contabo Principal · root@207.180.235.220 · Ubuntu 22.04
✅ SSH OK · 18 GB libres · Python 3.11 instalado · nginx running
[Configurar] [Test de nuevo] [Borrar]
```

**`DeployToVpsCard`** — Estado del deploy:
```
🚀 Desplegando mi-tiktok a Contabo Principal
[████████░░░░] 60% · Paso 3/5: pip install
└─ Streaming en tiempo real (click para expandir logs)
```

**`FileChangeCard`** — Cada vez que el agente edita un archivo:
```
✏ Editado backend/server.py
+12 −3 líneas · Hace 2 segundos
[Ver diff] [Deshacer] [Aceptar]
```

**`ScreenshotCard`** — Pruebas visuales del agente:
```
📸 Screenshot de https://tiktok.midominio.com
[Imagen del preview]
✅ El feed vertical carga correctamente · 6 videos visibles
```

---

## 6. Agente IA "Emergent Replica"

Crear un agente nuevo en `agents_catalog.py`:

```python
"lluvia_studio": {
    "id": "lluvia_studio",
    "name": "Lluvia Studio (Beta)",
    "emoji": "🛠",
    "color": "#5B8DEF",
    "voice": "onyx",
    "tagline": "Tu agente de desarrollo full-stack — chat, edita, deploya",
    "system": (
        "Eres Lluvia Studio, el agente full-stack de Lluvia App Studio. "
        "Trabajas dentro de un IDE web que tiene file tree, editor Monaco, "
        "terminal SSH al VPS del usuario y preview en vivo. Tu objetivo es "
        "construir, modificar y deployar apps del usuario.\n\n"
        "**REGLAS**:\n"
        "1. Antes de editar código, leelo con read_file. NO inventes.\n"
        "2. Ediciones pequeñas: usa search_replace. Ediciones grandes: write_file.\n"
        "3. Después de cambios al backend, recordá al usuario reiniciar el "
        "   servicio (o llamá restart_vps_service si tiene VPS conectado).\n"
        "4. Antes de hacer push, corré los tests automáticos disponibles.\n"
        "5. Toda acción destructiva (borrar archivo, drop DB) requiere "
        "   confirmación EXPLÍCITA del usuario en el chat.\n"
        "6. Tono: técnico, conciso, sin floritura. Máximo 3 frases fuera de tool cards."
    ),
    "tools": [
        # Reusables existentes:
        "push_to_my_github",
        # Nuevas:
        "read_workspace_file",
        "write_workspace_file",
        "search_replace_in_file",
        "list_workspace_files",
        "delete_workspace_file",
        "run_vps_command",
        "deploy_app_to_vps",
        "restart_vps_service",
        "tail_vps_logs",
        "screenshot_url",
        "create_systemd_service",
        "configure_nginx_vhost",
        "request_certbot_https",
    ],
}
```

Cada tool nueva se define en `console.py` siguiendo el patrón de `push_to_my_github` (línea 186 actualmente).

---

## 7. Auto-deploy a VPS desde el chat

Este es el flujo end-to-end completo que debe quedar funcionando:

### Setup inicial (una vez por VPS)

1. Usuario va a Settings → tab "Mis Servidores" → "+ Agregar VPS".
2. Ingresa: alias, IP, port, user, clave SSH (textarea con su `id_rsa` privada).
3. Backend cifra la clave con AES-GCM (clave maestra en `.env::VPS_ENCRYPTION_KEY`).
4. Click "Probar conexión":
   - Backend hace `asyncssh.connect()` → ejecuta `uname -a && df -h /opt`.
   - Devuelve OS detectado, disco libre, presencia de python3/node/nginx.
   - Si falta algo, ofrece comando para instalarlo.
5. Si todo OK, status = "connected" y aparece la `VpsConnectedCard` en el chat.

### Deploy de una app generada

Flujo en el chat después de generar una app TikTok:

```
Usuario: "Deploy a mi VPS Contabo"

Agente IA: [invoca deploy_app_to_vps(app_slug="mi-tiktok", vps_id="...")]

Tool ejecuta:
  1. SSH al VPS Contabo
  2. mkdir -p /opt/lluvia-apps/mi-tiktok
  3. git clone {repo_url} /opt/lluvia-apps/mi-tiktok  (streaming output)
  4. cd /opt/lluvia-apps/mi-tiktok/backend
  5. python3 -m venv venv
  6. venv/bin/pip install -r requirements.txt  (streaming)
  7. Generar /etc/systemd/system/lluvia-mi-tiktok.service:
       [Unit] Description=Lluvia App: mi-tiktok
       [Service] WorkingDirectory=/opt/lluvia-apps/mi-tiktok/backend
                 ExecStart=.../venv/bin/uvicorn server:app --host 0.0.0.0 --port 8042
                 Restart=on-failure
                 EnvironmentFile=/opt/lluvia-apps/mi-tiktok/backend/.env
       [Install] WantedBy=multi-user.target
  8. systemctl daemon-reload && systemctl enable lluvia-mi-tiktok
  9. systemctl start lluvia-mi-tiktok
  10. systemctl status (verificar Active: active (running))
  11. Devolver DeployToVpsCard con: {url_interna, logs_url, deployment_id}

Agente IA después de la card: "Tu app está corriendo en http://207.180.235.220:8042.
Para HTTPS con dominio, decime cuál querés usar (ej: tiktok.midominio.com) y
configuro nginx + certbot automáticamente."
```

### Asignación de puerto

Para evitar colisiones cuando el cliente deploya N apps:
- Mantener una colección `vps_ports` con `{vps_id, port, app_slug}`.
- Función `assign_port(vps_id) → int` que devuelve el siguiente libre en `8040-8999`.

### HTTPS automático con certbot

Tool `configure_nginx_vhost(vps_id, domain, port)`:
1. SSH al VPS.
2. Generar `/etc/nginx/sites-available/{domain}`:
   ```nginx
   server {
       listen 80;
       server_name {domain};
       location / {
           proxy_pass http://localhost:{port};
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```
3. `ln -s /etc/nginx/sites-available/{domain} /etc/nginx/sites-enabled/`
4. `nginx -t && systemctl reload nginx`
5. `certbot --nginx -d {domain} --non-interactive --agree-tos --email {user_email}`
6. Devolver `https://{domain}` como URL final.

---

## 8. Fases de implementación

**Ejecutar en este orden estricto**. No saltar.

### Fase 1 — Infra VPS (Backend) ⏱ 2-3h

Objetivo: que el agente del chat pueda ejecutar comandos en el VPS y deployar apps.

- [ ] `vps_manager.py` con CRUD + test connection (paramiko/asyncssh).
- [ ] Cifrado AES-GCM de la clave SSH (`backend/crypto_utils.py`).
- [ ] Endpoint `POST /api/me/vps/{id}/exec` (admin/owner only).
- [ ] Endpoint `POST /api/me/vps/{id}/deploy-app`.
- [ ] WebSocket `/api/me/vps/{id}/logs/{service}` (streaming journalctl).
- [ ] Tools en `console.py`: `run_vps_command`, `deploy_app_to_vps`, `tail_vps_logs`.
- [ ] Test con curl + admin desde una sesión de chat: pedirle al agente "lista los archivos en /opt de mi VPS".

### Fase 2 — UI Settings de VPS ⏱ 1h

- [ ] Nueva tab "Mis Servidores" en `SettingsTab.js`.
- [ ] Form para agregar VPS (alias, IP, port, user, ssh_key textarea).
- [ ] Botón "Probar conexión" con feedback visual.
- [ ] Lista de VPS conectados con badge de status.

### Fase 3 — File Tree + Editor inline ⏱ 3-4h

- [ ] Endpoints `/api/me/apps/{slug}/files` (tree) y `/file` (read/write).
- [ ] Componente `FileTree.js` recursivo en sidebar izquierdo.
- [ ] Componente `CodeEditor.js` con Monaco.
- [ ] Auto-save con debounce + indicador.
- [ ] Tools en `console.py`: `read_workspace_file`, `write_workspace_file`, `search_replace_in_file`.

### Fase 4 — Terminal embebido (xterm) ⏱ 2h

- [ ] WebSocket `/api/me/vps/{id}/terminal` con PTY (`asyncssh.start_session`).
- [ ] Componente `VpsTerminal.js` con xterm + FitAddon.
- [ ] Tab "Terminal" en el panel derecho.

### Fase 5 — Preview iframe + Screenshot ⏱ 2h

- [ ] Endpoint `POST /api/me/apps/{slug}/preview` (arranca uvicorn temporal en :8500-8999).
- [ ] Endpoint `POST /api/me/apps/{slug}/screenshot` (usa playwright).
- [ ] Componente `PreviewIframe.js` con reload + mobile view.
- [ ] Tab "Preview" en el panel derecho.

### Fase 6 — Logs streaming + nginx/certbot ⏱ 2-3h

- [ ] Componente `DeployLogs.js` con WebSocket.
- [ ] Tools: `configure_nginx_vhost`, `request_certbot_https`.
- [ ] Tab "Logs" en el panel derecho.

### Fase 7 — Agente "Lluvia Studio" + system prompt ⏱ 1h

- [ ] Agregar el agente en `agents_catalog.py`.
- [ ] Asignarle todas las tools nuevas.
- [ ] System prompt completo (ver sección 6).
- [ ] Hacer que aparezca primero en `agents_catalog` para visibilidad.

### Fase 8 — Refinamiento UX (look & feel Emergent) ⏱ 2-3h

- [ ] `react-resizable-panels` para el layout split.
- [ ] Animaciones de tool cards (slide-in desde la derecha).
- [ ] Skeleton loaders mientras carga.
- [ ] Iconografía con Lucide (ya está en deps).
- [ ] Dark mode coherente con el resto de la app.

**Total estimado**: 14-20 horas de trabajo de Claude (o agente de Emergent) si vas en paralelo.

---

## 9. Testing y rollback

### Tests automáticos a crear

Ubicar en `/opt/lluvia/backend/tests/`:

- `test_vps_manager.py` — crear/test/borrar VPS con mock SSH (sin tocar VPS real).
- `test_deploy_flow.py` — flujo completo: materialize template → push GitHub → deploy VPS.
- `test_terminal_ws.py` — abrir terminal y escribir comando, verificar output.
- `test_file_edits.py` — read/write/diff/rollback de archivos en workspace.

Correr con: `cd /opt/lluvia/backend && PYTHONPATH=. pytest tests/ -v`

### Rollback de cambios

Si Claude edita un archivo y rompe algo:

```bash
# Cada edit guarda diff en file_edits collection.
# Endpoint para revertir:
POST /api/me/file-edits/{edit_id}/rollback
# Aplica diff inverso al archivo.
```

UI: en la `FileChangeCard` hay siempre un botón "Deshacer".

### Snapshots de VPS antes de deploy

Antes de un deploy grande:
```bash
# Tool: snapshot_vps(vps_id)
# 1. SSH al VPS
# 2. tar -czf /opt/lluvia-snapshots/{timestamp}.tar.gz /opt/lluvia-apps/{app_slug}
# 3. Guardar metadata en Mongo
# Restore: tar -xzf {snapshot} -C /
```

---

## 10. Checklist final

Antes de declarar "Réplica de Emergent completa", verificar TODOS estos casos:

- [ ] **Usuario nuevo** se registra → recibe 15 oros trial → puede usar el agente "Lluvia Studio" → genera una app Audio Room.
- [ ] **Agente edita archivo** → aparece `FileChangeCard` con diff → click "Deshacer" → archivo vuelve al estado anterior.
- [ ] **Usuario conecta VPS** Contabo → status pasa a `connected` → aparece en el sidebar.
- [ ] **Agente deploya** la app al VPS → systemd service running → URL accesible.
- [ ] **Configurar HTTPS** con un dominio → certbot OK → URL `https://...` funciona.
- [ ] **Editor Monaco** modifica `backend/server.py` → auto-guarda → restart del service desde el chat → cambios aplicados sin downtime > 5s.
- [ ] **Terminal** xterm conecta al VPS, `ls -la /opt` muestra archivos.
- [ ] **Preview iframe** muestra la app local antes de deployar.
- [ ] **Screenshot** captura la app deployada y la muestra en el chat.
- [ ] **Logs streaming** muestra `journalctl -u lluvia-mi-tiktok -f` en vivo.
- [ ] **Push & Deploy** card (v12.27) sigue funcionando (regresión).
- [ ] **Tests pytest** verdes (mínimo 90% pass).
- [ ] **Mobile responsive** del Studio (collapse de paneles en <768px).

---

## 11. Cosas que probablemente Claude se va a encontrar y cómo manejarlas

### "asyncssh no se puede instalar en el VPS porque falta cryptography"
```bash
sudo apt-get install -y build-essential libssl-dev libffi-dev python3-dev
pip install --upgrade pip
pip install asyncssh==2.18.0
```

### "El uvicorn de la app deployada conflictea con el puerto 8001 del backend principal"
Asignar puertos `8042+` para apps de clientes. Backend de Lluvia siempre en `8001`.

### "El nginx vhost choca con el de lluvia-app-studio.lluvia-live.com"
- Confirmar que `server_name` es específico (subdominio o dominio diferente).
- NO tocar `/etc/nginx/sites-enabled/lluvia-app-studio.lluvia-live.com`.

### "El certbot falla porque DNS no apunta al VPS"
- Tool debe validar antes con `dig +short {domain}` → IP debe ser `207.180.235.220`.
- Si no, devolver mensaje claro: "Apuntá el A record de {domain} a 207.180.235.220 y volvé a intentar".

### "El usuario quiere borrar una app deployada"
- Tool `undeploy_app_from_vps(vps_id, app_slug)`:
  1. `systemctl stop lluvia-{app_slug}`
  2. `systemctl disable lluvia-{app_slug}`
  3. `rm /etc/systemd/system/lluvia-{app_slug}.service`
  4. `systemctl daemon-reload`
  5. `rm -rf /opt/lluvia-apps/{app_slug}`
  6. Si tenía nginx vhost: removerlo y `nginx -s reload`
  7. Update `vps_deployments` status = "removed"

---

## 12. Variables de entorno nuevas en `.env`

Agregar a `/opt/lluvia/backend/.env`:

```bash
# Master key para cifrar SSH keys de VPS (generar con: openssl rand -hex 32)
VPS_ENCRYPTION_KEY=...

# Puerto base para apps deployadas por clientes
VPS_APP_PORT_BASE=8042
VPS_APP_PORT_MAX=8999

# Path donde se clonan apps en VPS remotos
VPS_APPS_BASE_PATH=/opt/lluvia-apps

# Path en este backend donde se guardan workspaces de clientes
LLUVIA_HOME=/app                     # ya existe

# Para playwright (screenshots)
PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
```

---

## 13. Cómo Claude reporta progreso al usuario

Después de cada fase completada, generar un mini-reporte con este formato:

```markdown
## ✅ Fase {N} completada — {Nombre fase}

**Cambios**:
- {bullet 1}
- {bullet 2}

**Archivos nuevos/modificados**:
- backend/vps_manager.py (+340 líneas)
- frontend/src/components/Studio.js (NUEVO)

**Tests**:
- 12/12 PASS en tests/test_vps_manager.py

**Próximo paso**: Fase {N+1} — {Nombre}.

**Verificación manual recomendada para el usuario**:
- Andar a Settings → "Mis Servidores" → agregar Contabo y probar conexión.
```

---

## 14. Recursos adicionales

- **Docs xterm.js**: https://xtermjs.org/docs/
- **Monaco Editor + React**: https://github.com/suren-atoyan/monaco-react
- **asyncssh examples**: https://asyncssh.readthedocs.io/en/latest/api.html
- **paramiko vs asyncssh**: usar asyncssh para anything streaming, paramiko solo si necesitás compatibilidad sync.
- **systemd template units**: https://www.freedesktop.org/software/systemd/man/systemd.unit.html
- **certbot automation**: https://eff-certbot.readthedocs.io/en/stable/using.html#automated-renewals

---

## 15. ⚠ Lo que NO debes hacer

- ❌ Editar archivos del backend de Lluvia (`/opt/lluvia/backend/*`) directamente sin avisar al usuario. Si los cambios se hacen en el VPS, hay que sincronizar con el preview de Emergent o se pierden en el siguiente `git pull`.
- ❌ Reusar el mismo `JWT_SECRET` de Lluvia para las apps deployadas. Cada app deployada genera el suyo.
- ❌ Permitir comandos shell arbitrarios desde clientes (solo admin/owner del VPS).
- ❌ Guardar passwords SSH en plano. SIEMPRE cifrar.
- ❌ Hacer push automático al GitHub del usuario sin que él lo apriete. Es destructivo.
- ❌ Modificar nginx en producción sin backup previo del archivo de config.

---

**Última actualización**: v12.27 (Feb 2026)
**Stack actual confirmado**: FastAPI + Motor + python-socketio + React + MongoDB
**Tiempo estimado de construcción**: 14-20 horas en paralelo
**Resultado esperado**: clon funcional de la experiencia Emergent dentro de Lluvia App Studio, vendible como diferencial del SaaS.

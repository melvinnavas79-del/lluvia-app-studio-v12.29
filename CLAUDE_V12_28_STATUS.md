# ✅ Estado de implementación v12.28 — Lluvia Studio (réplica de Emergent)

> **Para Claude en VPS Contabo `207.180.235.220`**.
> Este documento detalla qué está **YA IMPLEMENTADO** en el preview de Emergent (v12.28)
> y qué te queda por hacer en el VPS. Lee primero `HANDOFF_TO_CLAUDE_VPS.md` y
> `CLAUDE_VPS_BUILD_PLAN.md` para contexto.

---

## 🎯 TL;DR

El agente principal (E1 de Emergent) implementó las **Fases 1, 2, 3 y 7** del
plan completo. Te dejaron ~70% del código listo. Te queda:

- ✅ **YA HECHO (no tocar)**: Backend `vps_manager.py`, `workspace_files.py`, `crypto_utils.py`, modelos Mongo, todas las tools del agente, frontend `Studio.js`, `FileTree.js`, `CodeEditor.js`, `VpsServersTab.js`, integración en `ClientDashboard.js` y `SettingsTab.js`.
- ⚠ **TE TOCA EN EL VPS**: Solo `git pull` + rebuild frontend + reinstalar deps + reiniciar systemd. NO modificar el código fuente.
- 🔜 **PENDIENTE PARA FUTURO**: Terminal embebido xterm WebSocket (Fase 4), preview iframe (Fase 5), logs streaming WebSocket (Fase 6). Pero el agente IA del chat YA puede hacer todo eso vía tools (deploy, lectura de logs, run commands).

---

## 1. ✅ Backend implementado (v12.28)

### 1.1 Módulos nuevos

| Archivo | Líneas | Función |
|---|---|---|
| `backend/crypto_utils.py` | ~60 | AES-GCM encrypt/decrypt para SSH keys |
| `backend/vps_manager.py` | ~370 | CRUD VPS + test SSH + exec + deploy + logs |
| `backend/workspace_files.py` | ~190 | File tree + read/write con rollback |

### 1.2 Endpoints REST listos (todos protegidos con JWT)

```
POST   /api/me/vps                                    Crear VPS (cifra credencial)
GET    /api/me/vps                                    Listar mis VPS
DELETE /api/me/vps/{vps_id}                           Borrar
POST   /api/me/vps/{vps_id}/test                      Validar SSH + detectar OS
POST   /api/me/vps/{vps_id}/exec                      Ejecutar comando shell
POST   /api/me/vps/{vps_id}/deploy-app                Deploy app del workspace
POST   /api/me/vps/{vps_id}/restart-service/{service} systemctl restart
GET    /api/me/vps/{vps_id}/tail-logs?service=&lines= Últimas N líneas journalctl
GET    /api/me/vps/{vps_id}/deployments               Listar deploys
DELETE /api/me/vps/{vps_id}/deployments/{deploy_id}   Undeploy completo

GET    /api/me/apps/{app_slug}/files                  Tree del workspace
GET    /api/me/apps/{app_slug}/file?path=...          Leer contenido
PUT    /api/me/apps/{app_slug}/file                   Escribir (guarda diff)
DELETE /api/me/apps/{app_slug}/file?path=...          Borrar
GET    /api/me/apps/_/file-edits                      Historial cambios
POST   /api/me/apps/_/file-edits/{edit_id}/rollback   Revertir
```

### 1.3 Colecciones Mongo creadas

- `vps_servers` — config SSH (clave/password cifrados con AES-GCM)
- `vps_deployments` — historial deploys con status/port/service_name/steps
- `file_edits` — diff + previous_content para rollback

### 1.4 Tools del agente `lluvia_studio` (ya wired en `console.py`)

```python
[
  "list_workspace_files",   # gratis
  "read_workspace_file",    # gratis
  "write_workspace_file",   # 2 oros
  "search_replace_workspace", # 1 oro
  "list_my_vps",            # gratis
  "run_vps_command",        # 1 oro
  "deploy_app_to_vps",      # 25 oros
  "tail_vps_logs",          # gratis
  "restart_vps_service",    # 1 oro
  "push_to_my_github",      # ya existía (v12.27)
]
```

Cada tool valida ownership y bloquea comandos peligrosos (`rm -rf /`, `mkfs`, `shutdown`).

### 1.5 Dependencias agregadas

```
asyncssh==2.18.0
cryptography==46.0.7
paramiko==3.5.0
PyNaCl==1.6.2   # transitiva de paramiko
```

Ya están en `requirements.txt`. Se instalan con:
```bash
cd /opt/lluvia/backend && pip install -r requirements.txt
```

### 1.6 Variables de entorno nuevas (en `.env`)

```bash
# Se autogeneran al primer uso si no existen:
VPS_ENCRYPTION_KEY=<hex 64 chars>     # Clave maestra AES-GCM
VPS_APP_PORT_BASE=8042                 # Puerto inicial para apps deployadas
VPS_APP_PORT_MAX=8999                  # Puerto máximo
VPS_APPS_BASE_PATH=/opt/lluvia-apps   # Donde se clonan las apps en el VPS
```

> **Importante**: la primera vez que se llame a `crypto_utils.encrypt_str()`, el módulo
> genera `VPS_ENCRYPTION_KEY` random y la persiste en `.env`. Si querés controlarla
> vos, agregala manualmente ANTES del primer uso.

---

## 2. ✅ Frontend implementado (v12.28)

### 2.1 Componentes nuevos

| Archivo | Función |
|---|---|
| `frontend/src/components/Studio.js` | IDE web tipo Emergent (3 paneles: tree, chat, editor/preview/logs) |
| `frontend/src/components/FileTree.js` | Árbol recursivo de archivos con iconos por extensión |
| `frontend/src/components/CodeEditor.js` | Monaco Editor con auto-save (debounce 1.2s) |
| `frontend/src/components/VpsServersTab.js` | UI para conectar/listar VPS desde Settings |

### 2.2 Integraciones en archivos existentes

- `ClientDashboard.js` → agregada pestaña `studio` (botón "🛠 Studio" en el top nav)
- `SettingsTab.js` → 3 sub-secciones: "🔧 GitHub", "🖥 Mis Servidores", "⚙ Cuenta"

### 2.3 Dependencias frontend agregadas

```json
"@monaco-editor/react": "^4.7.0",
"react-resizable-panels": "^4.11.1",
"lucide-react": "^0.469.0"   // ya estaba pero se reinstaló versión compatible
```

Se instalan con `yarn install` (los traen el `package.json` actualizado).

---

## 3. 🛠 Lo que tienes que hacer EN EL VPS

### Paso 1: Pull del código nuevo

```bash
cd /opt/lluvia
git fetch origin
git pull origin main   # debe traer v12.28
```

Verificá que vinieron los archivos nuevos:

```bash
ls -la backend/vps_manager.py backend/workspace_files.py backend/crypto_utils.py
ls -la frontend/src/components/Studio.js frontend/src/components/FileTree.js \
       frontend/src/components/CodeEditor.js frontend/src/components/VpsServersTab.js
```

Si alguno falta, el push del usuario no incluyó todo. Avisale.

### Paso 2: Backend deps + rebuild de frontend

```bash
# Backend
cd /opt/lluvia/backend
source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd /opt/lluvia/frontend
yarn install --frozen-lockfile
yarn build

# Reemplazar el build viejo
rm -rf /opt/lluvia/frontend-build
mv build /opt/lluvia/frontend-build
```

### Paso 3: Reiniciar servicios

```bash
sudo systemctl restart lluvia-backend
sudo nginx -s reload
sleep 5
sudo journalctl -u lluvia-backend -n 50 --no-pager
```

Debes ver en logs algo como:
```
INFO: Started server process
INFO: Application startup complete.
```

### Paso 4: Smoke tests (curl)

```bash
# Auth admin
TOKEN=$(curl -s -X POST https://lluvia-app-studio.lluvia-live.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"melvinnavas79@gmail.com","password":"Admin#2026"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 1. Listar VPS (debe ser vacío)
curl -s https://lluvia-app-studio.lluvia-live.com/api/me/vps \
  -H "Authorization: Bearer $TOKEN"
# Esperado: {"vps":[]}

# 2. Agente Lluvia Studio existe con sus tools
curl -s https://lluvia-app-studio.lluvia-live.com/api/console/agents \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;a=[x for x in json.load(sys.stdin)['agents'] if x['id']=='lluvia_studio'];print('TOOLS:',a[0]['tools'] if a else 'NOT FOUND')"
# Esperado: TOOLS: ['list_workspace_files', 'read_workspace_file', 'write_workspace_file', ...]

# 3. Endpoint workspace files (sin app, debe dar 404 claro)
curl -s https://lluvia-app-studio.lluvia-live.com/api/me/apps/nonexistent/files \
  -H "Authorization: Bearer $TOKEN"
# Esperado: {"detail":"App 'nonexistent' no encontrada en tu workspace"}
```

Si los 3 tests pasan: **TODO FUNCIONA, AVÍSALE AL USUARIO**.

### Paso 5: Validar UI en navegador

1. Abrí `https://lluvia-app-studio.lluvia-live.com` en una pestaña incógnita.
2. Loguéate con un user de prueba (no admin — admin va a otro dashboard).
3. En el dashboard, deberías ver una nueva pestaña **"🛠 Studio"** en el top nav.
4. Click → debe mostrar el layout de 3 paneles (FileTree | chat-link | Editor/Preview/Logs).
5. Andá a "Mi Cuenta" → debe haber sub-tabs: "🔧 GitHub", "🖥 Mis Servidores", "⚙ Cuenta".

---

## 4. 🚀 Cómo USAR todo esto (manual para el usuario)

### 4.1 Conectar el VPS Contabo desde la UI

1. Dashboard → "Mi Cuenta" → tab "🖥 Mis Servidores" → click "+ Agregar VPS"
2. Llenar:
   - **Alias**: "Mi Contabo Principal"
   - **Host/IP**: `207.180.235.220`
   - **Puerto SSH**: `22`
   - **Usuario**: `root` (o el que uses)
   - **Clave SSH privada**: pegá el contenido completo de tu `~/.ssh/id_ed25519`
     incluyendo las líneas `-----BEGIN ... -----` y `-----END ... -----`
3. Click "Guardar y probar conexión"
4. Aparece la card con badge "● CONECTADO" + info detectada del OS

### 4.2 Pedirle al agente que deploye una app

En el dashboard:

1. "+ Nuevo hilo" → Seleccioná agente **🛠 Lluvia Studio**
2. Escribí: *"Listame las apps que tengo en el workspace"*
3. El agente invoca `list_workspace_files` y devuelve el tree.
4. *"Deployá mi-tiktok a mi VPS Contabo Principal en el dominio tiktok.misitio.com"*
5. El agente invoca `deploy_app_to_vps`:
   - SSH al VPS
   - `git clone` el repo de la app
   - `pip install -r requirements.txt`
   - Crea `lluvia-mi-tiktok.service` en systemd
   - Configura nginx vhost
   - Ejecuta `certbot` para HTTPS
   - Devuelve la URL final: `https://tiktok.misitio.com`
6. **Costo**: 25 oros (configurable desde admin panel).

### 4.3 Editar archivos vía agente

*"Mostrame el contenido de backend/server.py de mi-tiktok"*
→ `read_workspace_file`

*"En ese archivo, cambiá el JWT_SECRET de placeholder por una variable de entorno"*
→ `search_replace_workspace` (guarda diff para rollback)

*"Reiniciá el servicio lluvia-mi-tiktok"*
→ `restart_vps_service` (verifica que sea `active`)

*"Mostrame los últimos 200 logs del servicio"*
→ `tail_vps_logs`

---

## 5. ⚠ Qué FALTA implementar (Fases 4-6 del plan original)

| Fase | Feature | Workaround actual |
|---|---|---|
| **4** | Terminal xterm.js embebido en `Studio.js` | El agente IA puede ejecutar comandos vía `run_vps_command` |
| **5** | Preview iframe + screenshot automático | El usuario abre la URL deployada en otra pestaña |
| **6** | Logs en streaming WebSocket (vs polling actual) | El tab "📋 Logs" del Studio hace polling on-demand con botón "Cargar" |

**Tiempo estimado para terminarlas**: 5-7 horas. Pueden hacerse incrementalmente cuando el usuario recupere su mano.

---

## 6. 📋 Checklist post-deploy en VPS

- [ ] `git pull origin main` exitoso
- [ ] `pip install -r requirements.txt` instaló asyncssh, paramiko, cryptography
- [ ] `yarn build` terminó sin errores
- [ ] `frontend-build/` reemplazado
- [ ] `systemctl restart lluvia-backend` sin errores en logs
- [ ] `nginx -s reload` exitoso
- [ ] Curl test 1 (list vps) responde `{"vps":[]}`
- [ ] Curl test 2 (agents) muestra `lluvia_studio` con sus 10 tools
- [ ] Curl test 3 (apps/nonexistent/files) responde 404 claro
- [ ] Frontend en navegador muestra pestaña "🛠 Studio" para usuarios no-admin
- [ ] SettingsTab muestra sub-tabs (GitHub, Mis Servidores, Cuenta)

Si TODOS los checkboxes están ✅: **avisale al usuario que ya puede recargar
créditos y probar el flujo end-to-end**.

---

## 7. 🆘 Troubleshooting

### "No module named 'asyncssh'"
```bash
cd /opt/lluvia/backend && source venv/bin/activate && pip install asyncssh==2.18.0
sudo systemctl restart lluvia-backend
```

### Frontend no compila por `react-resizable-panels`
La v4 cambió la API: `PanelGroup` → `Group`, `PanelResizeHandle` → `Separator`.
El código v12.28 ya usa la API correcta. Si `yarn install` baja una versión
diferente y rompe, hacé:
```bash
cd /opt/lluvia/frontend
yarn add react-resizable-panels@4.11.1 --exact
yarn build
```

### "VPS_ENCRYPTION_KEY no se persiste"
Si `.env` es read-only, agregalo manualmente:
```bash
echo "VPS_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> /opt/lluvia/backend/.env
sudo systemctl restart lluvia-backend
```

### Endpoint `/deploy-app` falla en el VPS destino con "Permission denied"
El usuario SSH del VPS destino necesita poder hacer `sudo` sin password para:
- `mkdir`, `systemctl`, `nginx`, `certbot`

Editá `/etc/sudoers.d/lluvia-deploy` en el VPS destino:
```
your-ssh-user ALL=(ALL) NOPASSWD: /bin/systemctl, /usr/bin/tee, /bin/mkdir, /bin/rm, /usr/sbin/nginx, /usr/bin/certbot
```

---

**v12.28** – Feb 2026 – Implementado por E1 (Emergent main agent).
**Próxima review**: cuando el usuario vuelva con créditos.

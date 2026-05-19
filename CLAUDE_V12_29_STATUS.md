# ✅ v12.29 — Réplica de Emergent 100% completa

> **Para Claude en VPS Contabo `207.180.235.220`**.
> Las Fases 4, 5 y 6 del plan original están **TERMINADAS Y TESTEADAS**.
> Esto reemplaza/actualiza `CLAUDE_V12_28_STATUS.md`.

---

## 🎯 TL;DR

El usuario tiene ahora el clon completo de Emergent dentro de Lluvia App Studio:

| Feature | Estado | Archivo |
|---|---|---|
| Auto-deploy a VPS via SSH | ✅ v12.28 | `vps_manager.py` |
| File tree + Monaco editor | ✅ v12.28 | `Studio.js`, `CodeEditor.js`, `FileTree.js` |
| Settings VPS (cifrado AES-GCM) | ✅ v12.28 | `VpsServersTab.js` |
| Agente IA "Lluvia Studio" | ✅ v12.28 | `agents_catalog.py` |
| **Terminal xterm.js via WebSocket** | ✅ **v12.29** | `VpsTerminal.js` + `ws_streams.py` |
| **Preview iframe + Playwright screenshots** | ✅ **v12.29** | `PreviewIframe.js` + `workspace_preview.py` |
| **Logs WebSocket streaming en vivo** | ✅ **v12.29** | `DeployLogs.js` + `ws_streams.py` |

---

## 1. ✅ Lo que se implementó en v12.29

### 1.1 Backend nuevos módulos

| Archivo | Líneas | Función |
|---|---|---|
| `backend/ws_streams.py` | ~220 | WebSocket: terminal PTY interactivo + journalctl -f streaming |
| `backend/workspace_preview.py` | ~250 | Preview uvicorn temporal + proxy HTTP + Playwright screenshots |

### 1.2 Endpoints nuevos (v12.29)

```
# Preview
POST   /api/me/apps/{slug}/preview               Arranca uvicorn en puerto 9100-9300
POST   /api/me/apps/{slug}/preview/stop          Detiene preview activo
GET    /api/me/apps/{slug}/preview/status        Estado + heartbeat (refresca TTL)
*      /api/me/apps/{slug}/preview/proxy/{path}  Proxy HTTP al uvicorn temporal

# Screenshots (Playwright)
POST   /api/me/apps/{slug}/screenshot            Body: {url, viewport_width, viewport_height, wait_ms, full_page}
GET    /api/me/apps/_/screenshots/{shot_id}.png  Sirve la imagen guardada

# WebSocket (auth con ?token=... query param porque navegadores no soportan headers en WS)
WS     /api/me/vps/{vps_id}/terminal             PTY interactivo (xterm.js)
WS     /api/me/vps/{vps_id}/logs/{service}       journalctl -u {service} -f streaming
```

### 1.3 Frontend nuevos componentes

| Archivo | Función |
|---|---|
| `frontend/src/components/VpsTerminal.js` | xterm.js + WebSocket + FitAddon + resize handling |
| `frontend/src/components/DeployLogs.js` | WebSocket streaming + filtros (ALL/ERROR/WARN/INFO/DEBUG) + autoscroll + colorizado por nivel |
| `frontend/src/components/PreviewIframe.js` | Iframe del preview + toggle desktop/mobile + reload + screenshot 1-click |
| `frontend/src/components/Studio.js` | **REESCRITO**: 4 tabs (Editor / Preview / Terminal / Logs) integrando todos los componentes |

### 1.4 Dependencias agregadas

**Backend** (en `requirements.txt`):
```
playwright==1.49.1
pyee==12.0.0
greenlet==3.1.1
```

**Frontend** (en `package.json`):
```json
"@xterm/xterm": "^6.0.0",
"@xterm/addon-fit": "^0.11.0"
```

### 1.5 Variables de entorno nuevas (en `.env`)

```bash
PLAYWRIGHT_BROWSERS_PATH=/pw-browsers   # o /root/.cache/ms-playwright si usas default
PREVIEW_PORT_BASE=9100
PREVIEW_PORT_MAX=9300
SCREENSHOTS_DIR=/tmp/lluvia_screenshots  # opcional
```

### 1.6 Mongo: nueva colección

- `screenshots` — metadata de capturas (no la imagen, esa va a disco en `SCREENSHOTS_DIR`)

---

## 2. 🛠 Pasos en tu VPS Contabo

### Paso 1: Pull v12.29

```bash
cd /opt/lluvia
git fetch origin
git pull origin main
```

Verificá los archivos nuevos:
```bash
ls -la backend/ws_streams.py backend/workspace_preview.py
ls -la frontend/src/components/VpsTerminal.js \
       frontend/src/components/DeployLogs.js \
       frontend/src/components/PreviewIframe.js
```

### Paso 2: Backend deps

```bash
cd /opt/lluvia/backend
source venv/bin/activate
pip install -r requirements.txt

# CRITICAL: instalar el browser de Playwright
playwright install chromium --with-deps
# Si pide sudo: sudo $(which playwright) install-deps chromium
```

> Esto descarga ~280MB de chromium headless. Tarda ~1-2 min con buena red.
> Si tu VPS es small (1-2GB RAM), considerá agregar swap antes:
> ```bash
> sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
> sudo mkswap /swapfile && sudo swapon /swapfile
> ```

### Paso 3: Frontend deps + rebuild

```bash
cd /opt/lluvia/frontend
yarn install --frozen-lockfile
yarn build
rm -rf /opt/lluvia/frontend-build
mv build /opt/lluvia/frontend-build
```

### Paso 4: Nginx — habilitar WebSockets (CRÍTICO)

Si todavía no tenés WebSocket habilitado en tu nginx vhost de Lluvia, agregalo:

```nginx
# /etc/nginx/sites-available/lluvia-app-studio.lluvia-live.com

server {
    listen 443 ssl http2;
    server_name lluvia-app-studio.lluvia-live.com;

    # ... tu config SSL existente ...

    # API + WebSocket
    location /api/ {
        proxy_pass http://localhost:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;      # ← CRÍTICO para WS
        proxy_set_header Connection "upgrade";       # ← CRÍTICO para WS
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;                    # ← terminal sin timeout
        proxy_send_timeout 86400;
    }

    location / {
        root /opt/lluvia/frontend-build;
        try_files $uri $uri/ /index.html;
    }
}
```

Validar y recargar:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Paso 5: Reiniciar backend

```bash
sudo systemctl restart lluvia-backend
sleep 5
sudo journalctl -u lluvia-backend -n 30 --no-pager
```

### Paso 6: Smoke tests

```bash
TOKEN=$(curl -s -X POST https://lluvia-app-studio.lluvia-live.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"melvinnavas79@gmail.com","password":"Admin#2026"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Test 1: preview status
curl -s "https://lluvia-app-studio.lluvia-live.com/api/me/apps/test/preview/status" \
  -H "Authorization: Bearer $TOKEN"
# Esperado: {"running":false}

# Test 2: screenshot a una URL externa (valida que chromium funciona)
curl -s -X POST "https://lluvia-app-studio.lluvia-live.com/api/me/apps/test/screenshot" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","wait_ms":1000}'
# Esperado: {"ok":true,"screenshot_id":"...","image_url":"...","size_bytes":15000+}

# Test 3: WebSocket (necesita wscat o similar)
# Sin wscat, validá desde el navegador: Studio → tab Terminal con un VPS conectado.
```

### Paso 7: Validación UI completa

1. Login con un usuario no-admin en `https://lluvia-app-studio.lluvia-live.com`
2. Dashboard → tab **"🛠 Studio"**
3. Deberías ver 4 tabs en el panel derecho: ✏ Editor · 👁 Preview · 🖥 Terminal · 📋 Logs
4. **Test Editor**: clic en un archivo del FileTree → Monaco abre y permite editar con auto-save.
5. **Test Preview**: tab "Preview" → "▶ Iniciar preview" → debe arrancar uvicorn y mostrar el iframe.
6. **Test Screenshot**: con el preview corriendo → "📸 Screenshot" → aparece la imagen abajo.
7. **Test Terminal**: tab "Terminal" → si hay un VPS conectado, debe abrir la shell remota.
8. **Test Logs**: tab "Logs" → ingresá el nombre de un service (ej `lluvia-mi-app`) → "▶ Stream en vivo" → llegan líneas.

---

## 3. 🎬 Flujo end-to-end (demo para el usuario)

1. **Settings → Mis Servidores** → agregar VPS Contabo con SSH key.
2. **Chat → Lluvia Studio** → "Listame las apps de mi workspace".
3. Agente invoca `list_workspace_files` → muestra `mi-tiktok`.
4. **Studio → tab Editor** → edita `backend/server.py`. Auto-save funciona.
5. **Studio → tab Preview** → "▶ Iniciar preview" → tu app arranca local. "📸 Screenshot" guarda PNG.
6. **Chat → Lluvia Studio** → "Deployá mi-tiktok a mi VPS Contabo en tiktok.midominio.com".
7. Agente invoca `deploy_app_to_vps` (25 oros) → SSH → git clone → systemd → nginx → certbot.
8. **Studio → tab Terminal** → shell remota al VPS Contabo, ejecutá lo que quieras.
9. **Studio → tab Logs** → entrá `lluvia-mi-tiktok` → ves logs en vivo via WebSocket.

---

## 4. ⚠ Troubleshooting

### "WebSocket connection failed" en el navegador
- Verificá que nginx tenga las directivas `proxy_set_header Upgrade $http_upgrade` y `Connection "upgrade"` en el `location /api/`.
- Si usás Cloudflare frente a nginx, andá a Network → "WebSockets" → ON.
- Test desde curl: `curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" https://...` debe responder `101 Switching Protocols`.

### "Playwright Executable doesn't exist"
```bash
cd /opt/lluvia/backend
source venv/bin/activate
PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright playwright install chromium
# O configurá PLAYWRIGHT_BROWSERS_PATH en el .env apuntando a donde se descargó.
sudo systemctl restart lluvia-backend
```

### "Preview arranca pero no se ve el iframe"
- El preview corre en localhost:9100-9300 del backend → solo accesible via el proxy `/api/me/apps/{slug}/preview/proxy/`.
- Si el iframe da CORS error, el sandbox del iframe ya tiene `allow-same-origin` que debería bastar. Probá quitar el `sandbox` momentáneamente para debug.
- Si el preview crashea, mirá logs del backend: `sudo journalctl -u lluvia-backend -n 100`.

### "Terminal se conecta pero no responde"
- Verificá que el usuario SSH tenga `bash` o `sh` como shell por defecto en el VPS destino.
- Si conectás como `root` y no funciona, probá con un user normal + `sudo -i` después.

### Logs no llegan en streaming
- Verificá que el service exista: `sudo systemctl status lluvia-mi-app`.
- El usuario SSH necesita permisos `sudo journalctl` sin password (agregalo a sudoers):
  ```
  your-user ALL=(ALL) NOPASSWD: /bin/journalctl
  ```

### Frontend no compila por @xterm
- Si yarn baja una versión incompatible: `yarn add @xterm/xterm@6.0.0 @xterm/addon-fit@0.11.0 --exact`.

---

## 5. 📋 Checklist final post-deploy

- [ ] `git pull origin main` exitoso (v12.29)
- [ ] `pip install -r requirements.txt` instaló playwright + asyncssh + paramiko
- [ ] `playwright install chromium --with-deps` exitoso
- [ ] `yarn install` + `yarn build` sin errores
- [ ] `frontend-build/` reemplazado
- [ ] nginx config tiene directivas WebSocket (Upgrade / Connection upgrade)
- [ ] `systemctl restart lluvia-backend` sin tracebacks
- [ ] Test 1 (preview/status) → `{"running":false}`
- [ ] Test 2 (screenshot example.com) → PNG válido devuelto
- [ ] Test 3 (UI Studio) → tabs Editor, Preview, Terminal, Logs cargan
- [ ] WebSocket terminal abre shell remota cuando hay VPS conectado
- [ ] WebSocket logs muestra streaming de journalctl

Si TODOS los checks pasan: **avísale al usuario que ya tiene el 100% del clon de Emergent**.

---

## 6. 🚀 Listo para Play Store

El backend expone una API REST + WebSocket completa. Para hacer la app en Play Store:

- **Opción A (rápida)**: Wrappear el frontend con [Capacitor](https://capacitorjs.com/) o [Trusted Web Activity](https://developer.chrome.com/docs/android/trusted-web-activity/) — la PWA actual ya funciona, solo necesita un `manifest.json` y service worker.
- **Opción B**: App React Native que consume los mismos endpoints `/api/*`.

El backend no necesita cambios. Solo asegurate de:
- Tener HTTPS válido (certbot).
- Headers de CORS permisivos para tu app Android (ya están).
- Service worker para PWA offline (no implementado todavía, P2).

---

**v12.29** – Feb 2026 – Listo para producción.

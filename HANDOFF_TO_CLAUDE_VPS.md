# 🤖 Handoff técnico: Lluvia App Studio en VPS Contabo (207.180.235.220)

> **Para Claude (corriendo en `/opt/lluvia/` del VPS Contabo del usuario)**.
> Este documento describe el estado actual del código en el preview de Emergent
> (la "fuente de verdad") y los puntos que necesitás revisar/arreglar en la
> producción del VPS.

---

## 1. Contexto del proyecto

**Lluvia App Studio** — SaaS multi-agente que genera apps deployables (Audio Room, TikTok/Bigo Live clone, etc.) y bots IA con tools reales (PayPal, Telegram, Gmail, GitHub, Sora 2, Whisper, Nano Banana).

- **Backend**: FastAPI + Motor (MongoDB) + python-socketio. Vive en `/opt/lluvia/backend` (en el VPS).
- **Frontend**: React (build estático). Vive en `/opt/lluvia/frontend-build/` (en el VPS).
- **Stack runtime**: Python 3.11+, Node 18+, MongoDB local o Atlas, supervisor.
- **Dominio prod**: `https://lluvia-app-studio.lluvia-live.com` (apuntado al VPS Contabo).

---

## 2. 🚨 Hallazgo crítico: Firebase NO existe en el código actual

En tu sesión vi que estabas buscando en `/opt/lluvia/frontend-build/static/js/main.48a73c03.js`:

```
try{return A(e(t))}catch(n){}
...Firebase not configured...
Please be sure to call initializeAuth or getAuth before starting any other Firebase SDK
```

**Diagnóstico**:
- Ejecuté `grep -rn "firebase\|getAuth\|initializeApp" /app/frontend/src` en el código actual del preview → **CERO resultados**.
- `package.json` y `yarn.lock` actuales **no contienen Firebase** como dependencia.

**Conclusión**: el bundle `main.48a73c03.js` que tenés deployado es un **build viejo** de cuando había Firebase. La auth actual usa **JWT propio** (`/api/auth/login`, `/api/auth/register`) — no Firebase Auth.

**Acción recomendada**: en lugar de parchear el bundle minificado, **rebuildea el frontend desde cero** con el código más reciente. El bundle viejo desaparece y el error de Firebase también.

```bash
cd /opt/lluvia/frontend
git pull origin main           # asegúrate de tener el código v12.27 mas reciente
yarn install --frozen-lockfile
yarn build                     # genera /opt/lluvia/frontend/build/
# Reemplazar el build viejo:
rm -rf /opt/lluvia/frontend-build
mv /opt/lluvia/frontend/build /opt/lluvia/frontend-build
# Reload nginx para invalidar caché:
sudo nginx -s reload
```

> Si después del build seguís viendo Firebase en el nuevo bundle, hacé:
> `grep -l "firebase" /opt/lluvia/frontend/node_modules/*/package.json` para
> ubicar la dep transitiva, y eliminala con `yarn remove`. **No debería haber
> ninguna** según el estado actual del código.

---

## 3. Lo que está nuevo en v12.27 (Feb 2026) — Cambios que tenés que sincronizar

Acabamos de mergear estos fixes críticos. Asegurate de hacer `git pull` antes de cualquier otra cosa:

### 3.1 Nuevo endpoint backend: `POST /api/me/github/push-app`
- Permite pushear UNA app del workspace a un **repo dedicado por app** (resuelve bug "todas las apps van al mismo repo").
- Acepta: `{app_slug, repo_name, create_new, target_owner_repo?, set_as_default?, private?}`.
- Crea el repo en GitHub vía REST API si `create_new=true`. Idempotente: si ya existe lo usa.
- Implementación: `backend/user_workspace.py` ~líneas 685-810.

### 3.2 Nuevo template: TikTok / Bigo Live clone
- Ruta: `backend/app_templates/tiktok_clone/`.
- 13 archivos (4 frontend + 2 backend + 7 deploy/docs).
- Stack: FastAPI + python-socketio + SQLite + Vanilla JS.
- Features: feed vertical, likes, comments en vivo, follows, regalos virtuales con cobro de credits.
- Tool del chat: `generate_tiktok_app` (50 oros default, editable desde panel admin).

### 3.3 AppBuiltCard rediseñado (frontend)
- Después de generar una app, aparece sección "Push & Deploy" con:
  - Input editable para nombre del repo (sugerido: `{app-slug}-{random4chars}`).
  - Botón "⬆ Push & Deploy" → llama a `push-app` con `create_new=true`.
  - Después del push: botón **"⚡ Deploy a Render (1-click)"** con URL `https://render.com/deploy?repo=...`.
- Implementación: `frontend/src/components/BossConsole.js` ~líneas 1235-1430.

### 3.4 `render.yaml` del Audio Room simplificado
- Removido el override de `PORT=10000` que causaba conflicto con `$PORT` de Render.

---

## 4. Arquitectura de directorios en el VPS

Para que Claude se ubique rápido:

```
/opt/lluvia/
├── backend/                # Código FastAPI (sincronizar con git pull)
│   ├── server.py           # ASGI entry
│   ├── console.py          # Tools del chat (>1200 líneas, refactor pendiente)
│   ├── user_workspace.py   # GitHub push REST API (v12.27 = multi-repo)
│   ├── app_builder.py      # Materializa templates
│   ├── app_templates/      # Templates: audio_room/, tiktok_clone/
│   ├── pricing.py          # Precios dinámicos editables desde admin panel
│   ├── agents_catalog.py   # Catálogo de agentes IA
│   ├── gmail_*.py          # Gmail Maestro (auto-reply con confianza > 0.9)
│   └── .env                # Variables (MONGO_URL, JWT_SECRET, etc.)
├── frontend-build/         # Build estático servido por nginx
└── user_apps/{user_id}/    # Workspaces generados por cada cliente
```

**Servicios systemd recomendados**:
- `lluvia-backend.service` → uvicorn server:app en :8001
- `nginx` → reverse proxy + static serve del frontend-build

---

## 5. 🛠 Issues que Claude puede arreglar AHORA en el VPS

Estos son problemas conocidos o sugerencias que tienen alta prioridad:

### A) Verificar que el rebuild del frontend tomó los cambios v12.27
Después de `yarn build`, validá:
```bash
grep -o "push-app" /opt/lluvia/frontend-build/static/js/main.*.js | head -1
# Debe imprimir "push-app". Si no, el rebuild no incluyó v12.27.
grep -o "generate_tiktok_app" /opt/lluvia/frontend-build/static/js/main.*.js | head -1
# Debe imprimir "generate_tiktok_app".
```

### B) Confirmar que el backend NO tiene el binario `git` instalado o NO lo necesita
La v12.27 usa **GitHub REST API** (httpx) — no necesita `git` instalado en el host.
Validá:
```bash
cd /opt/lluvia/backend
python -c "from user_workspace import _validate_github_token; print('OK, REST API listo')"
# No debe fallar con ImportError.
```

### C) Test smoke del nuevo endpoint
Con un token de admin:
```bash
TOKEN=$(curl -s -X POST https://lluvia-app-studio.lluvia-live.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"melvinnavas79@gmail.com","password":"Admin#2026"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Verificar que el endpoint existe (debe responder 404, no 401 ni 405):
curl -s -X POST https://lluvia-app-studio.lluvia-live.com/api/me/github/push-app \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"app_slug":"nonexistent","repo_name":"test","create_new":true}'
# Esperado: {"detail":"La app 'nonexistent' no existe en tu workspace. Generá una primero."}
```

### D) Confirmar que el template TikTok existe en producción
```bash
ls /opt/lluvia/backend/app_templates/tiktok_clone/
# Debe listar: backend/  frontend/  README.md  render.yaml  railway.toml
#              Dockerfile  Procfile  docker-compose.yml  install.sh
```

### E) Reiniciar el backend para que cargue los cambios del módulo `pricing.py`
```bash
sudo systemctl restart lluvia-backend
sleep 3
sudo journalctl -u lluvia-backend -n 30 --no-pager
# Verificar que no haya tracebacks. Debe decir:
# "Startup OK: indices creados, admin seeded"
```

### F) (Opcional) Health check del template TikTok materializado
Si querés validar end-to-end:
```bash
cd /tmp && python3 -c "
import sys; sys.path.insert(0, '/opt/lluvia/backend')
from pathlib import Path
import shutil, app_builder
target = Path('/tmp/test_tt')
if target.exists(): shutil.rmtree(target)
r = app_builder.materialize_template('tiktok_clone', target, app_name='Test', brand_color='#FF0050')
print('OK' if r['ok'] else 'FAIL:', r.get('error'))
print('Files:', r['files_written'])
"
```

---

## 6. Cosas que SÍ es seguro que Claude haga (no rompen producción)

✅ Hacer `git pull origin main` en `/opt/lluvia/backend` (hot reload con uvicorn `--reload`).
✅ Reconstruir el frontend (`yarn build`) y reemplazar `frontend-build/`.
✅ Reiniciar `lluvia-backend.service` con `systemctl restart`.
✅ Limpiar logs viejos (`/var/log/lluvia/*.log` si están grandes).
✅ Validar la conexión a Mongo (`mongosh $MONGO_URL --eval 'db.runCommand({ping:1})'`).
✅ Renovar el certbot si vence pronto (`sudo certbot renew --dry-run`).

## 7. Cosas que NO debe hacer Claude sin avisar al usuario

❌ Editar archivos en `/opt/lluvia/backend/` directamente (los cambios se pierden en el próximo `git pull`). Si encuentra bugs, anotarlos y avisar al usuario para fixearlos en el preview de Emergent.
❌ Dropear colecciones de Mongo (`db.users.drop()` etc).
❌ Cambiar `MONGO_URL` o `JWT_SECRET` sin coordinar.
❌ Borrar `/opt/lluvia/user_apps/{user_id}/` — son los workspaces de los clientes.
❌ Hacer `git push` desde el VPS al repo principal (el flujo es: editar en Emergent preview → push desde ahí → pull en VPS).

---

## 8. Credenciales para tests

- **Admin**: `melvinnavas79@gmail.com` / `Admin#2026`
- **MongoDB**: revisa `/opt/lluvia/backend/.env` → `MONGO_URL=mongodb://...`
- **Emergent LLM Key**: variable `EMERGENT_LLM_KEY` en `.env` (universal, para OpenAI/Claude/Gemini vía Emergent Integrations).
- **GitHub PAT del cliente**: lo configura cada usuario desde su panel "Mi Cuenta → Settings". El backend lo guarda cifrado en Mongo (`user_settings.github_token`).

---

## 9. Roadmap inmediato (próximas tareas)

| Prioridad | Tarea |
|-----------|-------|
| **P0** | Confirmar que el rebuild eliminó Firebase del bundle deployado. |
| **P0** | Validar smoke test de `/api/me/github/push-app` en producción. |
| **P1** | Refactor `console.py` (>1200 líneas) → mover tools a `backend/tools/`. |
| **P1** | Templates nuevos: Radio Online, Landing Peluquería, Ecommerce. |
| **P2** | **Auto-deploy a VPS desde el chat** (próxima feature pendiente — el usuario quiere que el agente IA pueda hacer SSH al Contabo y correr el `install.sh` automáticamente al final del Push). Modelo de DB `vps_servers` con SSH key cifrada. |
| **P2** | WhatsApp Cloud API channel. |
| **P3** | Stripe Connect para split payments con afiliados. |

---

## 10. Cómo Claude debe reportar issues al usuario

Si Claude encuentra un bug en el código, NO lo arregla directamente en el VPS (porque se pierde en el siguiente git pull). En su lugar, deja la observación con:

1. **Archivo y línea** afectados (path relativo a `/opt/lluvia/`).
2. **Síntoma observado** (con logs si es posible).
3. **Fix sugerido** en formato diff.
4. **Severidad** (P0 / P1 / P2).

El usuario lleva esa nota al preview de Emergent, el agente la aplica, hace test, push a GitHub, y Claude en el VPS hace `git pull` para sincronizar.

---

**Última actualización**: v12.27 (Feb 2026)
**Generado por**: E1 (Emergent main agent)
**Para**: Claude Code instance en VPS Contabo `207.180.235.220`

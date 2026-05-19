# {{APP_NAME}} — Feed Vertical de Videos en Vivo (TikTok / Bigo Live clone)

App full-stack lista para producción generada por **Lluvia App Studio · App Builder Pro**.

White-label, monetizable, deployable en 1 click en Render / Railway / Heroku / Fly.io / VPS / Docker.

## Stack
- **Backend**: FastAPI + python-socketio (ASGI) + SQLite. Cero dependencias externas obligatorias.
- **Frontend**: HTML5 + CSS3 + Vanilla JS (SPA con hash router, sin build).
- **Tiempo real**: Socket.IO para comentarios en vivo, viewer count, regalos.
- **Auth**: JWT propio. Registro anónimo en 1 click.

## 4 pantallas incluidas
1. **Feed Vertical** — Scroll snap full-screen, autoplay, double-tap heart, mute, like/comment/gift/share, bottom drawer.
2. **Descubrir** — Top creadores + grid de videos trending.
3. **Subir Video** — Form para publicar (URL mp4/HLS, caption, tags, thumbnail).
4. **Perfil** — Stats, follow, recarga de créditos, grid de videos del creador.

Bonus: **Regalos virtuales** con cobro automático en créditos (Rosa 5cr, Corazón 10cr, Cohete 50cr, Diamante 200cr, Corona 500cr). 70% del valor va al creador.

## 🚀 Deploy en 1 click

### ▶ Render.com (recomendado — free tier)
1. Pushea este repo a GitHub.
2. https://dashboard.render.com → **New → Blueprint** → conectá tu repo.
3. Render lee `render.yaml` automáticamente. Apretás **Apply**.
4. Tu app queda en `https://{{APP_NAME_SLUG}}.onrender.com` en ~5 min.

> **1-click deploy:** desde Lluvia App Studio podés apretar el botón "Deploy to Render" en el chat, que abre Render con el repo pre-cargado.

### ▶ Railway.app
1. https://railway.app → New project → Deploy from GitHub.
2. Railway detecta `railway.toml` automáticamente.
3. Listo en ~3 min.

### ▶ Heroku / Fly.io
- `Procfile` listo. `heroku create && git push heroku main` o `fly launch`.

### ▶ VPS propio (Ubuntu/Debian)
```bash
ssh tu-usuario@tu-vps.com
cd /opt && sudo git clone https://github.com/TU-USUARIO/{{APP_NAME_SLUG}}
cd {{APP_NAME_SLUG}} && sudo bash install.sh
```
Instala Python + venv + systemd + arranca en :8001. Después `sudo certbot --nginx -d tu-dominio.com` para HTTPS.

### ▶ Docker
```bash
docker compose up -d
```
La app queda en `http://localhost:8001`.

## Variables de entorno

| Variable | Default | Obligatorio |
|---|---|---|
| `JWT_SECRET` | random | Recomendado: setear uno fijo de 64 chars |
| `PORT` | 8001 | Render lo setea automáticamente |
| `DB_PATH` | ./data.db | Solo si querés cambiar ubicación |

## Correr localmente
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python server.py
```
Abrí http://localhost:8001 — el backend sirve el frontend desde la misma URL.

## Monetización ya cableada
- **Regalos virtuales** con cobro en créditos (Stripe / PayPal: extender `POST /api/users/{id}/topup`).
- **Creator share 70%** automático.
- **Premium follower paywall** opcional (extiende endpoint `/api/users/{id}/follow` con check de credits).

## Próximos pasos recomendados
- [ ] Reemplazar SQLite por Postgres cuando el tráfico crezca.
- [ ] Persistir Socket.IO en Redis para escalar horizontalmente.
- [ ] Integrar RTMP/HLS real para LIVE (Nginx-RTMP / Mux Live / Cloudflare Stream).
- [ ] Subida directa de videos a S3 / Cloudinary (este template asume URL ya hosteada).
- [ ] Conectar PayPal / Stripe a `/api/users/{id}/topup` para recarga real.

## 🆘 Troubleshooting

**Render: "Could not open requirements file"** → Asegurate de que `render.yaml` tiene `rootDir: backend`. Si lo deployaste como Web Service manual (sin Blueprint), poné `Root Directory: backend` en la config.

**Build OK pero el server crashea** → revisá los logs (Logs tab de Render). Lo más probable: olvidaste `JWT_SECRET`.

**Los videos no cargan** → tu URL debe ser **CORS-friendly y HTTPS**. Para test usá los samples de Google (ya incluidos en el seed inicial).

**Socket.IO no conecta detrás de un proxy** → asegurate de que el proxy NO bloquee WebSocket. En Nginx: `proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";`

---

Generado por [Lluvia App Studio](https://lluvia-app-studio.lluvia-live.com) — Plataforma SaaS de bots IA + apps deployables.

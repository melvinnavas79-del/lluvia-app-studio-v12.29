# {{APP_NAME}} — Salas de Audio en Vivo

App full-stack lista para producción generada por **Lluvia App Studio · App Builder Pro**.

Tipo Clubhouse / Twitter Spaces / Bigo Live, white-label, monetizable.

## Stack
- **Backend**: FastAPI + python-socketio (ASGI) + SQLite. Cero dependencias externas obligatorias.
- **Frontend**: HTML5 + CSS3 + Vanilla JS (SPA con hash router, sin build).
- **Tiempo real**: Socket.IO para signaling. WebRTC (P2P) para el audio.
- **Auth**: JWT propio. Registro anónimo en 1 click.

## 4 pantallas incluidas
1. **Inicio** — Hero CTA + categorías + salas en vivo.
2. **Tendencias** — Top creadores + salas más escuchadas.
3. **Sala Activa** — Hosts/Speakers/Listeners en vivo, mute, raise hand, reacciones.
4. **Perfil** — Stats, follow, suscripción premium, próximas salas.

Bonus: **Crear sala** (formulario con monetización gratis o premium con cobro de créditos).

## 🚀 Deploy en 1 click según tu proveedor

Elegí UNO de estos archivos (ya están en el repo, ignorá los otros):

### ▶ Render.com (recomendado para principiantes — free tier)
1. Pushea este repo a tu GitHub.
2. Andá a https://dashboard.render.com → New → Blueprint → conectá tu repo.
3. Render lee `render.yaml` automáticamente y configura todo. Solo apretás "Apply".
4. Tu app queda en `https://{{APP_NAME_SLUG}}.onrender.com` en ~5 min.

### ▶ Railway.app (más rápido, paga por uso)
1. https://railway.app → New project → Deploy from GitHub.
2. Railway detecta `railway.toml` o `Procfile` automáticamente.
3. Listo en ~3 min.

### ▶ Fly.io / Heroku (con Procfile)
- `Procfile` + `requirements.txt` ya están listos.
- En Fly: `fly launch` (te genera el `fly.toml`).
- En Heroku: `heroku create` + `git push heroku main`.

### ▶ VPS propio (Ubuntu/Debian — DigitalOcean, Hetzner, Contabo, etc)
Tenés 2 opciones según tu nivel técnico:

**Opción A — Script automático** (recomendado):
```bash
ssh tu-usuario@tu-vps.com
cd /opt
sudo git clone https://github.com/TU-USUARIO/{{APP_NAME_SLUG}}
cd {{APP_NAME_SLUG}}
sudo bash install.sh
```
Esto instala Python + crea venv + configura systemd + arranca la app en :8001.
Después: `sudo certbot --nginx -d tu-dominio.com` para HTTPS.

**Opción B — Docker** (si ya usás Docker):
```bash
docker compose up -d
```
La app queda en `http://tu-vps:8001`. Configurá nginx reverse-proxy aparte.

### ▶ Cualquier provider con Docker
- `Dockerfile` y `docker-compose.yml` listos en la raíz.
- Build: `docker build -t {{APP_NAME_SLUG}} .`
- Run: `docker run -p 8001:8001 -e JWT_SECRET=$(openssl rand -hex 32) {{APP_NAME_SLUG}}`

## Variables de entorno mínimas

| Variable | Default | Obligatorio |
|---|---|---|
| `JWT_SECRET` | (random si no se setea) | Recomendado: setear uno fijo de 64 chars |
| `PORT` | 8001 | Render lo setea automáticamente |
| `DB_PATH` | ./data.db | Solo si querés cambiar la ubicación |

## Cómo correr localmente

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python server.py
```

Abrí http://localhost:8001 — el backend sirve el frontend desde la misma URL.

> **HTTPS obligatorio para el micrófono.** En producción usá un reverse proxy (Caddy/Nginx) o un host como Railway/Render que dan HTTPS gratis. En local, `localhost` está whitelisteado por los browsers.

## Monetización ya cableada

- **Salas premium** con cobro en créditos (`price_credits`). El acceso se valida server-side.
- **Followers / suscripción al creador** (campo `followers` ya tracking, UI lista).
- **Modelo de créditos** in-app fácil de conectar a Stripe / PayPal extendiendo `POST /api/users/{id}/topup`.

## Próximos pasos recomendados

- [ ] Reemplazar SQLite por Postgres cuando el tráfico crezca.
- [ ] Persistir estado de salas en Redis para escalar Socket.IO horizontalmente.
- [ ] TURN server (Coturn) para usuarios detrás de NAT estricto.
- [ ] Notificaciones push cuando un creador que seguís inicia una sala.
- [ ] Grabación de salas con Liveblocks / AWS Chime.

## 🆘 Troubleshooting

**Render: "Could not open requirements file"** → Asegurate de que `render.yaml` tiene `rootDir: backend`. Si lo deployaste como Web Service manual (sin Blueprint), poné `Root Directory: backend` en la config de Render.

**Build OK pero el server crashea al arrancar** → revisá los logs (`Logs` tab de Render). Lo más probable: olvidaste setear `JWT_SECRET` o algún env var custom.

**WebRTC no conecta entre usuarios detrás de NAT** → necesitás un TURN server. Para tests, usá los STUN gratis (ya configurados en webrtc.js). Para producción real, alquilá Twilio TURN o instalá Coturn en un VPS.

**El micrófono no pide permiso** → la app TIENE que estar en HTTPS. localhost también funciona.

---

Generado por [Lluvia App Studio](https://lluvia-app-studio.lluvia-live.com) — Plataforma SaaS de bots IA + apps deployables.

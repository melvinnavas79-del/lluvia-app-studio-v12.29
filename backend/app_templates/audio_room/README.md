# {{APP_NAME}} — Salas de Audio en Vivo

App full-stack lista para producción generada por **Lluvia App Studio · App Builder Pro**.

Pensada como base de un producto tipo **Clubhouse / Twitter Spaces / Bigo Live** pero blanca y monetizable.

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

## Cómo correr localmente

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
python server.py
```

Abrí http://localhost:8001 — el backend sirve el frontend desde la misma URL.

> **HTTPS obligatorio para el micrófono.** En producción usá un reverse proxy (Caddy/Nginx) o un host como Railway/Render que dan HTTPS gratis. En local, `localhost` está whitelisteado por los browsers.

## Deploy en Railway / Render / Fly (5 min)

1. Pushear este repo a tu GitHub.
2. Crear servicio nuevo apuntando a `/backend`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python server.py`
5. Setear las variables del `.env.example` (mínimo `JWT_SECRET` con un string random).
6. Listo: tu app está online.

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

---

Generado por [Lluvia App Studio](https://lluvia-app-studio.lluvia-live.com) — Plataforma SaaS de bots IA + apps deployables. Hecho con cariño 💙.

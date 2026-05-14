# Lluvia App Studio — Blindaje de Seguridad (v10)

Documento tecnico del sistema de seguridad. Resumen de protecciones
implementadas y su ubicacion en el codigo.

## 1. Autenticacion JWT

- **Archivo**: `backend/auth.py`
- Bearer token en header `Authorization`
- Algoritmo HS256, secreto en `JWT_SECRET` (obligatorio).
- Expiracion: 8 horas
- Hash passwords con `bcrypt` (cost 12 por defecto)
- `seed_admin()` migra el admin si cambia el email o password en `.env`,
  evitando duplicados o admins huerfanos.

## 2. Roles y gates de admin

- `auth.require_admin` dependency exige `role == "admin"` (HTTP 403)
- Endpoints protegidos por admin:
  - `POST /api/affiliates` (crear afiliados)
  - `PUT /api/branding`, `POST /api/branding/reset`
  - `POST /api/console/credits/topup` (regalar oros)
  - `POST /api/promos`, `DELETE /api/promos/{id}`
  - `GET /api/proposals`, `POST /api/proposals/{id}/approve|reject`
- En Telegram: `actions/admin_link.py` verifica `chat_id` vinculado
  via password antes de ejecutar acciones privilegiadas (shell, github,
  provision).

## 3. Rate limiting (slowapi)

- **Archivo**: `backend/rate_limit.py`
- Key function: `X-Forwarded-For` (cuando hay Caddy/Nginx) o IP directa.
- Limites aplicados:
  - `POST /api/auth/login` -> 8/minuto/IP
  - `POST /api/paypal/create-order` -> 15/hora/IP
  - `POST /api/paypal/webhook` -> 60/minuto/IP
  - `POST /api/voice/transcribe` -> 30/minuto/IP
  - `POST /api/voice/tts` -> 30/minuto/IP
  - `POST /api/voice/call-center/turn` -> 20/minuto/IP
- Respuesta 429 con mensaje en castellano.

## 4. Validacion de webhook PayPal

- **Archivo**: `backend/paypal_integration.py` (`_verify_paypal_signature`)
- Llama a `https://api-m.paypal.com/v1/notifications/verify-webhook-signature`
  con los headers `paypal-*` y el body crudo recibido.
- Si la firma NO es valida -> HTTP 403 (no acredita oros).
- Si `PAYPAL_WEBHOOK_ID` no esta configurado -> rechaza todo el trafico
  por defecto. Bloqueo total hasta que se configure.
- Acreditacion idempotente: si la orden ya fue procesada, no duplica oros.

## 5. Comandos shell seguros

- **Archivo**: `backend/security.py` (`is_command_safe`)
- Blacklist anti-catastrofe: `rm -rf /`, `mkfs`, `dd if=`, etc.
- Solo `actions/server.py:run_command` ejecuta, y siempre detras del
  gate `is_admin_chat()`.
- Las tools de OpenAI tampoco ejecutan shell sin admin
  (`console.py:_exec_tool` chequea `is_admin`).

## 6. Aislamiento por cliente

- Cada cliente desplegado por `setup-cliente.sh` recibe:
  - Container Docker independiente
  - `JWT_SECRET` unico (32 bytes random)
  - MongoDB con DB nombrada `bot_<slug>` (no comparte data)
  - `ADMIN_PASSWORD` propio
  - Caddyfile dedicado en `Caddyfile.d/<slug>.conf`
- Imposible que un cliente acceda a la data de otro (network bridge
  separado + volumen Mongo aislado).

## 7. CORS

- `allow_origins=["*"]` permite el panel publico, **pero**
  `allow_credentials=False` impide ataques CSRF basados en cookies.
- El frontend envia el token via `Authorization: Bearer`, no via cookies.

## 8. Carga de logos

- `branding.py`: limite 2 MB en `logo_data_url` (base64)
- Validacion de tipo: cualquier `image/*` aceptado por el navegador,
  rechazo en server si peso excede.

## 9. Voz y creditos

- Cada turno de voz cobra antes de procesar:
  `credits.charge(user, cost)` retorna `False` si no hay saldo y aborta.
- Pricing real por minuto (`voice.py`, `call_center.py`).
- Logs detallados con `agent_id`, `session_id`, `voice` para auditoria.

## 10. Backups y disaster recovery

- Recomendado: cron diario `mongodump` -> S3 / Backblaze.
- Snapshot del volumen Docker del cliente (`/var/lib/docker/volumes/<slug>_mongo-data`).
- Disponibilidad: `restart: always` en `docker-compose.yml.tmpl`,
  healthchecks `15s` para auto-recovery.

## 11. Rotacion de secretos

Antes de cada venta o despliegue nuevo:

```bash
openssl rand -hex 32           # JWT_SECRET
openssl rand -base64 24        # ADMIN_PASSWORD
```

Cambiar tambien:
- `OPENAI_API_KEY` (uno por cliente o uno compartido con limite)
- `PAYPAL_CLIENT_ID/SECRET/WEBHOOK_ID` (cuenta propia del cliente o tuya)
- `TELEGRAM_TOKEN` (un bot por cliente)
- `GITHUB_TOKEN` (token con scope minimo: `repo`, sin `admin:*`)

## 12. Auditoria

Toda accion privilegiada queda en logs (`/var/log/supervisor/backend.*.log`):
- Vinculaciones admin (chat_id + timestamp)
- Comandos shell ejecutados (texto del comando)
- Tools ejecutadas por OpenAI (`tool_calls_made` persiste en mongo)
- Aprobaciones de propuestas (`proposals.approved_by`, `applied_at`)
- Compras PayPal completadas (`paypal_orders.completed_at`, `via_webhook`)

---

## Reportar vulnerabilidades

Email: melvinnavas79@gmail.com — usa la palabra "SECURITY" en el asunto.
Tiempo de respuesta objetivo: 48h.

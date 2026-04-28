# PRD - Bot Multiplataforma IA + Modo Afiliado

## Problema original (verbatim del usuario)
> "Cuanto cuesta crear un bot inteligente" → derivó en bot multiplataforma con webhooks (Telegram/WhatsApp/Instagram), GitHub, generación de apps, ejecución de comandos, IA conversacional. Iteración 2: white-label completo (sin branding externo) + Modo Afiliado MANUAL con auth propia.

## Arquitectura

```
backend/
├── server.py          FastAPI - webhooks + /api/command + /api/status + startup seed
├── auth.py            JWT (HS256) + bcrypt + dependencies (get_current_user, require_admin)
├── models.py          Pydantic: LoginIn, AffiliateCreateIn, SaleCreateIn, etc.
├── affiliates.py      Routers: /auth, /affiliates, /sales, /stats
├── config.py          Carga .env, expone credentials_status()
├── security.py        Blacklist comandos peligrosos
├── memory.py          Historial conversacional por usuario (RAM)
├── ai.py              OpenAI SDK directo (AsyncOpenAI) — sin emergentintegrations
├── agent.py / executor.py
└── actions/           github.py, server.py, apps.py, business.py

frontend/src/
├── App.js             Switch: Login | AdminDashboard | AffiliateDashboard
├── api.js             axios + Bearer interceptor + helpers
├── AuthContext.js     login/logout/me + persistencia localStorage
├── App.css            Tema dark + amber + JetBrains Mono
└── components/
    ├── Login.js
    ├── AdminDashboard.js   (3 tabs: Overview / Afiliados / Ventas)
    └── AffiliateDashboard.js  (vista personal — solo sus datos)
```

## Personas
- **Admin (owner)**: 1 cuenta. Configura .env, gestiona afiliados, registra ventas, ve toda la red, marca pagos.
- **Afiliado**: N cuentas. Login personal. Ve solo sus ventas y comisiones (filtrado a nivel API + UI separado).
- **Cliente final**: chatea con el bot por WhatsApp/Telegram/Instagram, sin acceso al panel.

## Estado actual de implementación

### ✅ Iteración 1 (2026-01-28) — Bot core
- Estructura completa según especificación del usuario
- Webhooks Telegram/WhatsApp/Instagram + `/api/command`
- IA conversacional con memoria por usuario
- Acciones: GitHub create_repo/list_repos, generador de landings HTML, comandos shell con security
- Dashboard React inicial con estado de plataformas
- 16/16 pytest backend + 6/6 UI

### ✅ Iteración 2 (2026-01-28) — White-label + Modo Afiliado
**White-label completo:**
- Eliminado badge "Made with Emergent" (de index.html)
- Eliminado script `emergent-main.js` y PostHog
- Eliminada librería `emergentintegrations` (Python) → reemplazada por `openai` SDK directo
- Eliminada dependencia `@emergentbase/visual-edits` (frontend)
- IA usa la `OPENAI_API_KEY` propia del usuario en `.env`
- 0 referencias residuales a "emergent" en el código de usuario

**Modo Afiliado (manual):**
- Auth JWT propia (HS256 + bcrypt, Bearer token, 8h)
- Admin seed idempotente (ADMIN_EMAIL / ADMIN_PASSWORD)
- 2 roles: `admin`, `affiliate`
- CRUD completo de afiliados (crear, listar, activar/desactivar)
- CRUD de ventas con cálculo automático de comisión = amount × commission_pct
- Stats personales (`/api/stats/me`) y de red (`/api/stats/network`, admin only)
- Filtrado por rol: afiliados solo ven `affiliate_id == su id`
- Dashboard admin con 3 tabs (Overview/Afiliados/Ventas) + ranking de afiliados
- Dashboard afiliado con KPIs personales y tabla de sus ventas
- Marcado manual de comisiones pagadas
- Defensa adicional: `/api/sales` rechaza ventas a afiliados desactivados (400)
- 25/25 pytest + 9/9 UI passed

## Backlog priorizado

### P0 (próximas tareas)
- Comando `/mi-rendimiento` en Telegram: cuando el afiliado escribe en Telegram con su `telegram_chat_id` registrado, el bot responde con sus stats personales
- Persistencia de memoria conversacional en MongoDB (hoy es RAM)
- Endpoint para que el afiliado cambie su propia password
- Generación de PDF/CSV de liquidación por período (período mensual)

### P1
- Brute-force protection: 5 fallos de login → lock de 15 min
- Refresh tokens (hoy hay solo access token de 8h)
- Servir landings generadas por HTTP (`/api/apps/{filename}`)
- Aggregation pipeline para `/api/stats/network` (hoy hace N+1 query)
- Permitir que el admin reasigne ventas (cambiar afiliado de una venta)
- Filtros de fecha en dashboard admin (mes actual, último mes, etc.)

### P2
- Pagos automáticos vía Stripe Connect / MercadoPago Payouts
- Tracking de clicks: links cortos firmados `/r/{code}/{producto}` con cookie de atribución
- Multi-idioma del bot (auto-detect)
- Webhook signed HMAC validation para Meta
- Editor visual de prompts del system message desde el dashboard

## Próximas acciones inmediatas (si el usuario las solicita)
1. Cambiar password admin desde `.env` (cambiar ADMIN_PASSWORD y reiniciar)
2. Crear el primer afiliado real desde el panel
3. Configurar tokens reales de WhatsApp/Telegram/Instagram para empezar a recibir ventas
4. Implementar comando `/mi-rendimiento` para que afiliados consulten desde Telegram

# PRD - Bot Multiplataforma IA + Modo Afiliado + Branding

## Problema original (verbatim del usuario)
> "Cuanto cuesta crear un bot inteligente" → bot multiplataforma con webhooks (Telegram/WhatsApp/Instagram), GitHub, generación de apps, IA conversacional. White-label completo. Iteración 3: pantalla Branding personalizable + verificación de persistencia + migración automática de admin al cambiar `ADMIN_EMAIL`.

## Arquitectura

```
backend/
├── server.py          FastAPI - webhooks + /api/command + /api/status + startup seed + indices
├── auth.py            JWT + bcrypt + dependencies + seed_admin (con migración auto)
├── models.py          Pydantic: LoginIn, AffiliateCreateIn, SaleCreateIn
├── affiliates.py      Routers: /auth, /affiliates, /sales, /stats
├── branding.py        Router: /branding GET (público), PUT (admin), POST /reset
├── config.py / security.py / memory.py / ai.py / agent.py / executor.py
└── actions/           github.py, server.py, apps.py, business.py

frontend/src/
├── App.js             Switch: Login | AdminDashboard | AffiliateDashboard
├── api.js             axios + Bearer interceptor + fmt helpers
├── AuthContext.js     login/logout/me + persistencia localStorage
├── BrandingContext.js carga /api/branding al montar, aplica CSS vars + document.title
├── App.css            Tema dark + amber (vars CSS personalizables)
└── components/
    ├── Login.js                   (lee branding para mostrar logo y product_name)
    ├── AdminDashboard.js          (4 tabs: Overview / Afiliados / Ventas / Branding)
    ├── AffiliateDashboard.js      (vista personal del afiliado)
    └── BrandingTab.js             (form admin con color pickers, logo upload, preview en vivo)
```

## Personas
- **Admin (owner)**: configura .env, gestiona afiliados, registra ventas, personaliza branding.
- **Afiliado**: login propio, ve solo sus ventas y comisiones.
- **Cliente final**: chatea con el bot por WhatsApp/Telegram/Instagram.

## Estado de implementación

### ✅ Iteración 1 (2026-01-28) — Bot core + IA conversacional
- Webhooks Telegram/WhatsApp/Instagram + `/api/command`
- IA con memoria, GitHub, generador de landings, comandos shell con security
- 16/16 pytest + 6/6 UI

### ✅ Iteración 2 (2026-01-28) — White-label + Modo Afiliado MANUAL
- Removido todo el branding externo (badge, scripts, librerías)
- IA con OpenAI SDK directo (key del usuario)
- Auth JWT propia (HS256 + bcrypt, Bearer 8h, admin seed)
- CRUD afiliados + ventas + cálculo de comisión + 2 dashboards (admin/afiliado)
- 25/25 pytest + 9/9 UI

### ✅ Iteración 3 (2026-01-28) — Branding white-label + persistencia + hardenings
- **Pantalla Branding** (4ta tab del admin):
  - Cambio de `product_name`, `tagline`, 4 colores (primary/accent/bg/text), `company_name`, `support_email`
  - Upload de logo (max 600KB, base64 data URL)
  - Preview en vivo a la derecha del form (sin guardar)
  - Validación hex `^#[0-9a-fA-F]{6}$` en backend (422 para colores inválidos)
  - Aplicación inmediata: CSS variables + document.title
  - Login refleja product_name y logo dinámicamente
  - Botón Restablecer con confirmación
- **Persistencia validada**: tras `supervisorctl restart backend`, admin/afiliados/ventas/branding sobreviven
- **`seed_admin` mejorado**: si cambias `ADMIN_EMAIL` en `.env` y reinicias, el admin existente migra a ese email automáticamente (no crea duplicado, no requiere tocar Mongo)
- **Defensa adicional**: `POST /api/sales` rechaza ventas a afiliados con `active:false` (HTTP 400)
- 41/41 pytest backend + 14/14 UI = **55/55 checks**

## Total acumulado: 82 backend tests + 29 UI tests = **111 checks, 100% verde**

## Backlog priorizado

### P0
- Comando `/mi-rendimiento` en Telegram para que el afiliado consulte sus stats por chat
- Persistir memoria conversacional del bot en MongoDB (hoy es RAM)
- Endpoint para que el afiliado cambie su propia password

### P1
- Brute-force protection (5 fallos = lock 15 min)
- Refresh tokens
- Rate limit en `PUT /api/branding`
- Generación de PDF/CSV de liquidación mensual de comisiones
- Aggregation pipeline para `/api/stats/network` (hoy N+1)
- Dividir AdminDashboard.js en archivos separados (>400 líneas)

### P2
- Pagos automáticos (Stripe Connect / MercadoPago Payouts)
- Tracking de clicks con links cortos firmados + cookie de atribución
- Multi-idioma del bot (auto-detect)
- Webhook signed HMAC validation para Meta
- Sistema de logo de uploads en filesystem en lugar de base64

## Acciones inmediatas que el usuario puede hacer
1. **Cambiar el email del admin**: editar `ADMIN_EMAIL` en `/app/backend/.env`, luego `sudo supervisorctl restart backend`. El admin se migrará automáticamente al nuevo email manteniendo todos sus permisos. La misma password (`Admin#2026`) o cambiarla simultáneamente con `ADMIN_PASSWORD`.
2. Personalizar marca desde la tab **Branding** del panel admin.
3. Crear afiliados reales y empezar a registrar ventas.
4. Configurar tokens reales de WhatsApp/Telegram/Instagram para recibir mensajes en vivo.

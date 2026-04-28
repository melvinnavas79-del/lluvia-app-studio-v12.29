# PRD - Lluvia App Studio Bot (Bot Multiplataforma IA)

## Problema original (verbatim del usuario)
> "Cuanto cuesta crear un bot inteligente" → bot multiplataforma con webhooks (Telegram/WhatsApp/Instagram), GitHub, generación de apps, IA conversacional, white-label completo, modo afiliado y branding personalizable.

## Cliente final
**Lluvia App Studio** — agencia de Melvin Navas (`melvinnavas79@gmail.com`) que vende copias del bot a sus clientes.

## Arquitectura

```
backend/
├── server.py              FastAPI - webhooks + /api/command + /api/status + startup
├── auth.py                JWT + bcrypt + seed_admin (con migración auto)
├── models.py              Pydantic models
├── affiliates.py          Routers: /auth, /affiliates, /sales, /stats
├── branding.py            Routers: /branding GET (público), PUT/RESET (admin)
├── config.py              Carga .env, expone credentials_status()
├── security.py            Blacklist comandos peligrosos
├── memory.py              Historial conversacional por usuario (RAM)
├── ai.py                  OpenAI SDK directo (AsyncOpenAI)
├── agent.py               Intent dispatcher (incluye /mi-rendimiento)
├── executor.py
└── actions/
    ├── github.py
    ├── server.py
    ├── apps.py
    ├── business.py        help_text, status_text, auto_reply
    └── affiliate_stats.py /mi-rendimiento → resumen del afiliado por chat_id

frontend/src/
├── App.js                 Switch: Login | AdminDashboard | AffiliateDashboard
├── api.js                 axios + Bearer + helpers
├── AuthContext.js         login/logout/me + persistencia localStorage
├── BrandingContext.js     carga branding, aplica CSS vars + document.title
├── App.css                Tema dark con CSS variables (theme-able)
└── components/
    ├── Login.js           Refleja product_name, tagline, support_email
    ├── AdminDashboard.js  4 tabs: Overview / Afiliados / Ventas / Branding
    ├── AffiliateDashboard.js
    └── BrandingTab.js     Form admin + preview en vivo
```

## Estado de implementación

### ✅ Iter 1 — Bot core (16 backend + 6 UI)
Webhooks, IA, GitHub, generador landings, comandos shell.

### ✅ Iter 2 — White-label + Modo Afiliado MANUAL (25 + 9)
Removido todo branding externo. OpenAI directo. Auth JWT propia. CRUD afiliados/ventas. Dashboards separados por rol.

### ✅ Iter 3 — Pantalla Branding + Persistencia + Hardenings (16 + 14)
Branding personalizable (nombre, colores, logo, soporte). Migración auto de admin. Validación hex de colores. Defensa de venta a afiliado desactivado.

### ✅ Iter 4 — Cierre Lluvia App Studio (18 + 12)
- Admin migrado a `melvinnavas79@gmail.com` (admin@admin.com elimnado, mismo UUID preservado)
- Telegram bot @LluviaAppStudioBot activo con webhook y comando `/mi-rendimiento` funcional
- Branding por defecto = Lluvia App Studio (azul lluvia #5fb4ff)
- CSS variables aplicadas: `--brand-primary`, `--brand-accent`, `--brand-bg`, `--brand-text`
- 0 referencias a Emergent en código de producto (solo URL preview de infraestructura)
- Bug fix `/status` (KeyError 'provider' pre-existente)

## Total acumulado: **129/129 verde** (75 backend + 54 UI)

## URL de acceso
- **Panel**: https://ai-bot-cost-calc.preview.emergentagent.com
- **Bot Telegram**: https://t.me/LluviaAppStudioBot

## Backlog priorizado
- P0: deployment a producción con dominio propio (eliminar `*.preview.emergentagent.com` de cara al cliente)
- P0: rotar TELEGRAM_TOKEN + JWT_SECRET (compartidos en chat)
- P1: Cambio de password por el propio afiliado, brute-force protection, refresh tokens
- P1: Dividir AdminDashboard.js (>400 líneas)
- P2: Pagos automáticos, tracking de clicks por afiliado, multi-idioma del bot

## Acciones inmediatas para Melvin
1. **Rotar token de Telegram**: `/revoke` en @BotFather → nuevo token → `TELEGRAM_TOKEN=` en `.env` → `setWebhook` con la URL nueva
2. **Cambiar password admin** desde `.env` (`ADMIN_PASSWORD`)
3. **Subir logo de Lluvia App Studio** desde tab Branding del panel
4. **Crear afiliados reales** desde tab Afiliados
5. **Vincular `telegram_chat_id` a cada afiliado** para que puedan usar `/mi-rendimiento`

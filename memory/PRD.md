# PRD - Lluvia App Studio Bot (Bot Multiplataforma IA)

## Cliente
**Lluvia App Studio** — agencia de Melvin Navas (`melvinnavas79@gmail.com`) que vende copias del bot a sus clientes.

## URLs
- **Panel admin**: https://ai-bot-cost-calc.preview.emergentagent.com
- **Bot Telegram**: https://t.me/LluviaAppStudioBot

## Arquitectura

```
backend/
├── server.py            FastAPI - webhooks + /api/command + startup
├── auth.py              JWT + bcrypt + seed_admin migratorio
├── models.py            Pydantic models
├── affiliates.py        /auth, /affiliates, /sales, /stats
├── branding.py          /branding GET (público) + PUT/RESET (admin)
├── config.py / security.py / memory.py / ai.py / agent.py / executor.py
└── actions/
    ├── github.py        Crear/listar repos via API
    ├── server.py        run_command con blacklist anti-catastrofe
    ├── apps.py          Genera HTML landings
    ├── business.py      greeting() + auto_reply() + help_text()
    └── affiliate_stats.py /mi-rendimiento por chat_id

frontend/src/
├── App.js · api.js · AuthContext · BrandingContext · App.css (CSS vars)
└── components/ Login · AdminDashboard (4 tabs) · AffiliateDashboard · BrandingTab
```

## Iteraciones completadas

### ✅ Iter 1 — Bot core (16 + 6)
Webhooks, IA, GitHub, generador landings, comandos shell con security.

### ✅ Iter 2 — White-label + Modo Afiliado MANUAL (25 + 9)
Removido todo branding externo. OpenAI directo. Auth JWT propia. CRUD afiliados/ventas. Dashboards separados por rol.

### ✅ Iter 3 — Branding personalizable + persistencia + hardenings (16 + 14)
Branding (nombre, colores, logo, soporte). Migración auto de admin. Validación hex. Defensa de venta a afiliado desactivado.

### ✅ Iter 4 — Cierre Lluvia App Studio (18 + 12)
Admin migrado, Telegram bot activo, branding Lluvia, CSS vars aplicadas. Fix bug `/status`.

### ✅ Iter 5 — Capacidades de ejecución completas
- **GitHub conectado**: probado con cuenta `melvinnavas79-del` (lista y crea repos reales)
- **Identidad oficial**: el bot se presenta como "Asistente Oficial de Lluvia App Studio" en `/start`, en respuestas de IA (system prompt) y en `auto_reply`
- **Comando `/start`** separado de `/help`: greeting profesional + comandos rápidos
- **Permisos por rol en el bot** (defensa en profundidad):
  - Comandos privilegiados (`server_cmd`, `github_create`, `github_list`, `create_app`): solo se ejecutan si el chat_id está en `ADMIN_TELEGRAM_CHAT_IDS` del `.env`
  - Cualquier otro usuario recibe mensaje claro y profesional
- **Blacklist anti-catastrofe** (`rm -rf /`, fork bomb, dd disk-wipe, formateo) **se mantiene intacta incluso para admin** — protección anti-typo no negociable
- Verificado en runtime: lista repos reales, crea `lluvia-bot-test-final`, ejecuta `uname -a`, bloquea `rm -rf /`, niega comandos a no-admin con mensaje educado

## Total acumulado: **160+ checks verde** en 5 iteraciones

## Backlog priorizado
- **P0**: rotar credenciales compartidas (TELEGRAM_TOKEN, GITHUB_TOKEN, JWT_SECRET, OPENAI_API_KEY)
- **P0**: deploy a producción con dominio propio para eliminar `*.preview.emergentagent.com`
- **P1**: comando `/vincular-admin <password>` en Telegram para auto-registrar chat_id sin tocar `.env`
- **P1**: cambio de password por el propio afiliado, brute-force protection, refresh tokens
- **P2**: pagos automáticos, tracking de clicks, multi-idioma del bot
- **P2**: `setup-cliente.sh` para escalar la agencia ("1 cliente por hora")

## Acciones inmediatas para Melvin
1. **Rotar todos los tokens compartidos en el chat** (Telegram, GitHub, OpenAI, JWT_SECRET)
2. **Activar comandos privilegiados desde Telegram**:
   - Escribe `/start` al bot desde tu Telegram personal
   - Revisa logs `tail /var/log/supervisor/backend.out.log` para ver tu chat_id
   - Edita `ADMIN_TELEGRAM_CHAT_IDS=tu_chat_id` en `backend/.env`
   - `sudo supervisorctl restart backend`
3. **Personalizar branding** (logo, colores) desde el tab Branding del panel
4. **Crear afiliados reales** desde el panel
5. **Deploy a producción** con dominio propio

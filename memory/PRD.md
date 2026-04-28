# PRD - Bot Multiplataforma IA

## Problema original (verbatim del usuario)
> "Cuanto cuesta crear un bot inteligente" → derivó en:
> "Un bot que use mi servidor que pegue comandos que entre a mi GitHub que pueda crear app y redes sociales y páginas web"
>
> Estructura solicitada: bot/main.py, agent.py, executor.py, config.py, security.py, ai.py, memory.py, actions/(github, server, apps, business). Webhooks Telegram + WhatsApp + Instagram. Puerto 8080 (adaptado a 8001 por Emergent), PM2 (adaptado a supervisor), OpenAI GPT.

## Arquitectura

```
backend/
├── server.py          FastAPI - webhooks Telegram/WhatsApp/Instagram + /api/command + /api/status
├── config.py          Lee .env, expone credentials_status()
├── security.py        Blacklist de comandos peligrosos (rm -rf /, fork bombs, etc.)
├── memory.py          Historial conversacional por usuario (RAM, MAX_HISTORY=20)
├── ai.py              LlmChat de emergentintegrations -> gpt-5.2 vía Emergent LLM Key
├── agent.py           interpret() + process_command()
├── executor.py        Despacha intents a actions/
└── actions/
    ├── github.py      crear repo / listar repos vía GitHub API
    ├── server.py      run_command (con security check)
    ├── apps.py        Genera HTML landing en backend/generated_apps/
    └── business.py    auto_reply, help_text, status_text

frontend/src/
├── App.js             Dashboard: status plataformas + consola en vivo + URLs webhook
└── App.css            Tema oscuro con acentos ámbar (Outfit + JetBrains Mono)
```

## Personas
- **Owner del bot**: edita .env, monitorea desde dashboard, configura tokens Meta/Telegram/GitHub.
- **Usuario final**: cliente que escribe en Telegram/WhatsApp/Instagram y recibe respuestas IA o ejecuta acciones.

## Requisitos centrales (estáticos)
1. Webhooks operativos para Telegram, WhatsApp e Instagram (verify + receive).
2. IA conversacional con memoria por usuario.
3. Acciones: GitHub (crear/listar repos), apps (generar landings HTML), servidor (comandos seguros).
4. Frontend de monitoreo y prueba directa de comandos.
5. Adaptación a entorno Emergent (puerto 8001 + prefijo /api).

## Implementado (2026-01-28)
- ✅ Estructura completa de archivos según especificación del usuario
- ✅ FastAPI con `/api/` prefix para todas las rutas
- ✅ Webhooks GET/POST para WhatsApp, POST con token para Telegram, GET/POST para Instagram
- ✅ `/api/command` (POST) para integración directa
- ✅ `/api/status` (GET) con credenciales y stats
- ✅ Motor IA con `gpt-5.2` vía `emergentintegrations` + Emergent LLM Key
- ✅ Memoria conversacional en RAM con historial por usuario
- ✅ `security.py` con blacklist de comandos peligrosos
- ✅ Generador de landings HTML (backend/generated_apps/)
- ✅ GitHub: create_repo, list_repos vía API REST
- ✅ Dashboard React: tema oscuro, consola en vivo, copiar URLs de webhook, sugerencias de comandos, polling de estado cada 15s
- ✅ Tested: 16/16 pytest backend + 6/6 flujos UI críticos

## Backlog priorizado
### P0 (próximas tareas si el usuario lo pide)
- Persistir memoria conversacional en MongoDB (sobrevive a reinicios y a múltiples replicas)
- Login con Google (Emergent-managed) para proteger el dashboard
- Publicación real en redes sociales (Twitter/X, Threads, Facebook)

### P1
- Modelo Pydantic `CommandIn` para `/api/command` (mejor validación + docs)
- Timeout/retry alrededor de `chat.send_message` en ai.py
- Allow-list de comandos en lugar de blacklist en security.py
- Servir las landings generadas por HTTP en `/api/apps/{filename}`
- Métricas / observabilidad de webhooks (contadores Prometheus)

### P2
- Editor visual de prompts del sistema desde el dashboard
- Multi-idioma del bot (auto-detect)
- Webhook firmado HMAC para Meta (validación de signature `x-hub-signature-256`)
- Plantillas de landing más variadas y elección de tema

## Próximas acciones inmediatas (si el usuario las solicita)
1. Cargar tus tokens reales de Telegram/WhatsApp/Instagram/GitHub en `backend/.env`
2. Probar webhooks en producción configurando las URLs en cada plataforma
3. Decidir si quieres autenticación Google en el dashboard

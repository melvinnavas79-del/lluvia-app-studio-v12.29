# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **Backend**: FastAPI (Python 3.11), Motor (async MongoDB), Uvicorn on port 8001
- **Database**: MongoDB 7 — db name controlled by `DB_NAME` env var (production: `lluvia_admin`)
- **Frontend**: Pre-built React SPA served by Nginx on port 3000
- **Infra**: Docker Compose — services: `mongo`, `backend`, `frontend`, `social-backend`
- **LLM routing**: `llm_router.py` — console tool-calling uses `get_console_client()` → gpt-4o-mini; simple tasks use `get_client("low")` → Groq llama-3.1-8b-instant

## Common Commands

```bash
# Start everything
cd /opt/lluvia && docker compose up -d

# Rebuild backend after code changes (required — no hot reload in production)
cd /opt/lluvia && docker compose build --no-cache backend && docker compose up -d backend

# Logs
docker logs lluvia_backend -f --tail 50

# Run tests (integration — needs live backend at localhost:8001)
cd /opt/lluvia/backend && python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_bot_multiplataforma.py -v

# Lint
cd /opt/lluvia/backend && flake8 . --max-line-length=120 --exclude=generated_apps,uploads,app_templates

# Health check
curl -s http://localhost:8001/api/ | python3 -m json.tool

# Verify E1 console provider
docker exec lluvia_backend python3 -c "from llm_router import get_console_client; c,m=get_console_client(); print(m, c.base_url)"
```

## Architecture

### Request Flow

```
HTTPS (Caddy/Nginx reverse proxy)
  → /api/*  → lluvia_backend:8001  (FastAPI)
  → /*      → lluvia_frontend:3000 (Nginx → React SPA)
```

### Backend Module Map

`server.py` is the entry point. It creates the FastAPI app, connects to MongoDB, seeds the admin user, starts background services (Telegram poller, job scheduler, Gmail scheduler), then mounts all routers under `/api`.

Key modules and their `/api` prefixes:

| Module | Prefix | Role |
|--------|--------|------|
| `console.py` | `/console` | **E1 orchestrator** — chat sessions, tool-calling loop, all 91 tools |
| `auth.py` / `affiliates.py` | `/auth` | JWT auth (8h tokens), user registration, login |
| `agents_catalog.py` | — | Static catalog of agents + tool cost map (`TOOL_NAMES`) |
| `llm_router.py` | — | LLM provider selection; `get_console_client()` for tool-calling |
| `credits.py` | — | "Oros" credit system — admin is exempt, users pay per tool |
| `e2_infra.py`…`e11_gmail_support.py` | `/e2`…`/e11` | Specialist sub-orchestrators |
| `job_scheduler.py` | `/jobs` | Background job queue |
| `vps_manager.py` | — | VPS provisioning for client apps |
| `user_workspace.py` | `/me` | Per-user file workspace |
| `e7_billing.py` | `/e7` | PayPal + subscription billing |

### `console.py` — E1 Orchestrator (3900+ lines)

This is the largest file and the core of the product. Key sections:

1. **`OPENAI_TOOLS` list** (line ~53): All tool schemas sent to the LLM
2. **`_filter_tools()`** (line ~1007): Filters tools by agent's allowed list + admin flag
3. **`_exec_tool()`** (line ~1357): Dispatches tool calls; admin users skip credit charges (`if cost > 0 and not is_admin`)
4. **`_select_tools_for_message()`** (line ~3507): Token-optimization — selects ≤15 relevant tools using `_TOOL_BUNDLES` + keyword matching. Tools named explicitly in the message are **pinned** and never trimmed.
5. **`send_message()`** (line ~3714): Main chat endpoint — builds message history, runs LLM tool-calling loop (max 5 turns), charges credits, persists to MongoDB

### Agent System

Agents are defined in `agents_catalog.py` as a dict. `lluvia_studio` is the main E1 agent with 91 tools. Each agent has:
- `id`, `name`, `system` (system prompt), `tools` (list of tool name strings)
- `TOOL_NAMES` dict maps tool name → oros cost (admin exempt)

Custom agents are stored in MongoDB `custom_agents` collection and merged via `_get_agent_any()`.

### Credit System ("Oros")

- Stored in MongoDB `credits` collection
- Admin: 10,000 oros initial, free tool execution
- Users: trial oros on register, depleted per tool call
- `credits.charge()` is called inside `send_message()` — returns `False` if insufficient, causing tool to return error JSON instead of executing

### LLM Routing

```python
# For E1 tool-calling (reliable function calling required)
get_console_client()  # → OpenAI gpt-4o-mini → OpenRouter → Groq 70b fallback

# For simple text generation inside tools
get_client("low")     # → Groq llama-3.1-8b-instant → OpenRouter → OpenAI mini
get_client("high")    # → Groq → OpenRouter → OpenAI gpt-4o
```

`CONSOLE_LLM_PROVIDER` env var overrides automatic selection (`"openai"` | `"groq"` | `"openrouter"`).

### Database Collections (MongoDB)

- `users` — auth, roles (`admin`/`affiliate`/`user`), profile
- `credits` — oros balance per user
- `chat_sessions` — E1 conversation history
- `custom_agents` — user-created agents
- `appointments`, `leads`, `audit_log`, `jobs`, `promo_codes`

### Key Invariants

- **Admin check pattern**: `is_admin = user.get("role") == "admin"` — set from DB, not from JWT token
- **Tool selection**: max 15 tools per LLM call (`_MAX_TOOLS_PER_REQUEST = 15`); explicitly-named tools are pinned and protected from trimming
- **No hot reload**: code changes require `docker compose build && up` — or `docker cp file container:/app/file && docker restart container` for quick iteration
- **`/opt/lluvia` vs `/opt/lluvia-studio`**: `/opt/lluvia` is the production build directory (docker-compose lives here). `/opt/lluvia-studio` is the working copy. Always sync changes with `cp /opt/lluvia-studio/backend/<file> /opt/lluvia/backend/<file>` before rebuilding.

## Environment Variables (`.env`)

Critical vars in `backend/.env`:

| Var | Purpose |
|-----|---------|
| `MONGO_URL` | `mongodb://mongo:27017` inside Docker |
| `DB_NAME` | `lluvia_admin` (production) |
| `OPENAI_API_KEY` | Primary LLM — gpt-4o-mini for console |
| `GROQ_API_KEY` | Fast/cheap LLM for simple tasks |
| `JWT_SECRET` | Token signing — never rotate without migrating sessions |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Seeded on every startup via `seed_admin()` |
| `LLUVIA_HOME` | `/opt/lluvia` — used by VPS provisioning tools |
| `CONSOLE_LLM_PROVIDER` | Optional override: `openai`\|`groq`\|`openrouter` |
| `GROQ_CONSOLE_MODEL` | Override Groq model for console (default: `llama-3.3-70b-versatile`) |

## Tests

Tests in `backend/tests/` are **integration tests** that hit a live HTTP server. Set `REACT_APP_BACKEND_URL` to point at the target backend (default tries a preview URL — override with `http://localhost:8001` for local runs).

```bash
REACT_APP_BACKEND_URL=http://localhost:8001 python -m pytest tests/test_bot_multiplataforma.py -v
```

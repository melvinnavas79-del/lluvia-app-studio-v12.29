# Architecture

## System Overview

```
                      Internet
                         │
              ┌──────────▼──────────┐
              │   Caddy / Nginx     │  HTTPS + SSL termination
              │   (reverse proxy)   │
              └──────┬──────┬───────┘
                     │      │
              /api/* │      │ /*
                     │      │
         ┌───────────▼──┐ ┌─▼──────────────┐
         │  FastAPI      │ │  Nginx         │
         │  :8001        │ │  :3000         │
         │  (backend)    │ │  (React SPA)   │
         └───────┬───────┘ └────────────────┘
                 │
         ┌───────▼──────────────────────────────┐
         │  E1 Orchestrator (console.py)         │
         │  91 tools · gpt-4o-mini               │
         │  tool-calling loop (max 5 turns)      │
         ├──────────────────────────────────────┤
         │  E2  E3  E4  E5  E6  E7  E8  E9      │
         │  E10  E11  (specialist agents)        │
         └───────────────┬──────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  MongoDB 7          │
              │  lluvia_admin       │
              └─────────────────────┘
```

## Backend Module Responsibilities

### Entry Point: `server.py`
- Creates FastAPI app, configures CORS, rate limiting
- `startup()`: connects MongoDB, seeds admin, starts background services
  (Telegram poller, job scheduler, Gmail scheduler)
- Mounts all routers under `/api`

### Orchestration: `console.py` (3900+ lines)
The heart of the product. Key sections:

| Section | Lines | Role |
|---------|-------|------|
| `OPENAI_TOOLS` | ~53–1006 | Tool schemas for LLM function calling |
| `_filter_tools()` | ~1007 | Filters by agent's allowed list + admin flag |
| `_exec_tool()` | ~1357–1984 | Dispatches all 91 tool implementations |
| `_web_search/browse` | ~1985–2031 | DuckDuckGo + Playwright web tools |
| Tool handlers | ~2032–3500 | Individual `_tool_*()` functions |
| `_select_tools_for_message()` | ~3507 | Token-aware tool selection (≤15 tools) |
| `send_message()` | ~3714 | Main endpoint: LLM loop, credit charge, persist |

### Routing: `agents_catalog.py`
- `AGENTS` dict — all built-in agent definitions
- `TOOL_NAMES` dict — tool name → oros cost (admin exempt via `credits.charge()`)
- `get_agent(id)` — lookup, falls back to MongoDB `custom_agents`

### LLM Selection: `llm_router.py`
```
get_console_client()  → OpenAI gpt-4o-mini (tool-calling)
                      → OpenRouter fallback
                      → Groq llama-3.3-70b-versatile (last resort)

get_client("low")     → Groq llama-3.1-8b-instant (text generation)
get_client("high")    → Groq → OpenRouter → OpenAI gpt-4o
```

Override via `CONSOLE_LLM_PROVIDER` env var.

### Credit System: `credits.py`
- MongoDB `credits` collection: `{ user_id, balance, lifetime_topup, lifetime_spent }`
- Admin: 10,000 oros initial, always free in tool execution
- `charge(user_id, amount, reason)` → `False` if insufficient (tool returns error JSON)
- Trial oros assigned at registration via `topup()`

## Database Collections

| Collection | Purpose |
|------------|---------|
| `users` | Auth, roles, profile, balance_oros |
| `credits` | Oros ledger per user |
| `chat_sessions` | E1 conversation history + tool calls |
| `custom_agents` | User-created agents (agent-builder) |
| `appointments` | Booking system |
| `leads` | CRM leads |
| `audit_log` | Admin action history |
| `jobs` | Background job queue |
| `promo_codes` | Discount codes |
| `site_content` | CMS content blocks |

## Tool Calling Flow

```
POST /api/console/sessions/{id}/messages
  ↓
1. Load session + agent from DB
2. Check credits balance (non-admin)
3. Filter tools: agent.tools → OPENAI_TOOLS → is_admin gate
4. Select ≤15 relevant tools (keyword bundles + pinned explicit names)
5. LLM call (gpt-4o-mini)
6. For each tool_call in response:
   a. _exec_tool(name, args, user_id, is_admin)
   b. if cost > 0 and not is_admin: credits.charge()
   c. append tool result to messages
7. Repeat up to 5 turns
8. Persist user_msg + assistant_msg to MongoDB
9. Return full response with tool_calls, cost, balance
```

## Scalability Notes

- **E1 console.py** is the main scaling bottleneck at 3900+ lines. Planned split:
  - `console/tools_devops.py` — shell, VPS, Docker tools
  - `console/tools_generators.py` — landing pages, social, code generators
  - `console/tools_cto.py` — architecture, rollback, diagnostics
  - `console/router.py` — HTTP endpoints only
  - `console/executor.py` — `_exec_tool()` dispatcher
- **MongoDB** — add replica set for HA; indexes on `chat_sessions.session_id`, `users.email`
- **Multi-tenant** — `setup-cliente.sh` provisions isolated Docker instances per client
- **Job queue** — `job_scheduler.py` handles async tasks; scale workers via env var

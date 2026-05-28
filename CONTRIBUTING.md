# Contributing to Lluvia App Studio

## Branch Strategy

```
main        ← production — only merge from develop via PR
develop     ← integration branch — merge features here first
feature/*   ← new features  (e.g. feature/e12-payments)
fix/*       ← bug fixes     (e.g. fix/tool-selection-trim)
chore/*     ← maintenance   (e.g. chore/update-deps)
```

**Rules:**
- Never push directly to `main`
- All merges to `main` require a passing CI check
- Tag `main` with a version after each release

## Commit Convention

```
[type] short description — details

Types: feat | fix | chore | docs | test | refactor | perf
```

Examples from this project:
```
[feat] E1 — add analyze_architecture CTO tool
[fix] console — admin tool charge bypass (cost > 0 and not is_admin)
[chore] gitignore — exclude uploads/ and generated_apps/
```

## Adding a New Tool to E1

1. **Define schema** in `console.py` → `OPENAI_TOOLS` list (line ~53)
2. **Set cost** in `agents_catalog.py` → `TOOL_NAMES` dict
3. **Add to agent** in `agents_catalog.py` → `AGENTS["lluvia_studio"]["tools"]`
4. **Add bundle** — add tool name to the appropriate set in `_TOOL_BUNDLES`
5. **Add keywords** — add trigger words to `_BUNDLE_KEYWORDS`
6. **Implement** — add `elif name == "your_tool":` in `_exec_tool()` (line ~1357)
7. **Write handler** — `async def _tool_your_tool(args: dict) -> dict:`
8. **Test**: `curl -X POST /api/console/sessions/{id}/messages -d '{"text":"usa tu_tool"}'`

## Adding a New Agent

1. Add entry to `agents_catalog.py → AGENTS` dict with `id`, `name`, `system`, `tools`
2. Or use the `POST /api/agent-builder/` endpoint (persists to MongoDB `custom_agents`)

## Deploy After Code Changes

```bash
# Full production rebuild (no hot reload in production)
make deploy-local

# Or manually:
cd /opt/lluvia && docker compose build --no-cache backend && docker compose up -d
```

## Environment Setup (Local Dev)

```bash
cp backend/.env.example backend/.env
# Fill in OPENAI_API_KEY, GROQ_API_KEY, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up -d
```

## Running Tests

```bash
# Integration tests (needs running backend)
REACT_APP_BACKEND_URL=http://localhost:8001 python -m pytest backend/tests/ -v

# Single test file
python -m pytest backend/tests/test_bot_multiplataforma.py -v

# Lint
make lint
```

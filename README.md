# Lluvia App Studio

**White-label AI Agency Platform** — Deploy AI agents for your clients in minutes.

Build and sell AI-powered assistants, booking systems, CRM automations, and full-stack apps using a single multi-agent platform with 91+ integrated tools.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     HTTPS (Caddy/Nginx)                  │
├──────────────────┬──────────────────────────────────────┤
│  /api/*          │  /*                                   │
│  FastAPI (8001)  │  React SPA (Nginx:3000)               │
└────────┬─────────┘                                       │
         │
    ┌────▼──────────────────────────────────────────────┐
    │  E1 Orchestrator (console.py)                     │
    │  91 tools · gpt-4o-mini · tool-calling loop       │
    ├───────────────────────────────────────────────────┤
    │  E2 Infra · E3 Builder · E4 Sales · E5 Whitelabel │
    │  E6 Legal · E7 Billing · E8 Support · E9 Analytics│
    │  E10 Social · E11 Gmail                           │
    └────────────────────────┬──────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   MongoDB 7     │
                    │   lluvia_admin  │
                    └─────────────────┘
```

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 · FastAPI · Motor (async MongoDB) |
| Frontend | React 18 · TailwindCSS · shadcn/ui |
| Database | MongoDB 7 |
| LLM | OpenAI gpt-4o-mini (console) · Groq llama-3.1-8b (tools) |
| Infra | Docker Compose · Nginx · Caddy (SSL) |
| Messaging | Telegram · WhatsApp (Meta) · Instagram |

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Domain with DNS pointing to your VPS

### 1. Clone and configure
```bash
git clone https://github.com/your-org/lluvia-app-studio.git
cd lluvia-app-studio
cp backend/.env.example backend/.env
# Edit backend/.env with your API keys
```

### 2. Build and run
```bash
docker compose up -d
```

### 3. Verify
```bash
curl http://localhost:8001/api/
# → {"service":"Bot Multiplataforma","status":"running",...}
```

Admin console: `https://yourdomain.com` — login with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`

## Development

```bash
# Full rebuild after backend changes
docker compose build --no-cache backend && docker compose up -d backend

# Logs
docker logs lluvia_backend -f --tail 50

# Run tests (needs live backend)
cd backend
REACT_APP_BACKEND_URL=http://localhost:8001 python -m pytest tests/ -v

# Lint
flake8 backend/ --max-line-length=120 --exclude=backend/generated_apps,backend/uploads
```

## Agents

The platform ships with **E1 (lluvia_studio)** as the main orchestrator with 91 tools:

- **DevOps**: shell, Docker, VPS provisioning, deploy, checkpoints
- **Workspace**: file read/write, GitHub push, code search
- **Business**: appointments, PayPal invoices, CRM, proposals
- **Generators**: landing pages, social posts, video scripts, CRUD/API scaffolding
- **CTO Layer**: architecture analysis, smart rollback, security scan, self-diagnostic
- **Comms**: Telegram, email, webhooks

Custom agents are built via `/api/agent-builder` and stored in MongoDB.

## Credits ("Oros")

Users pay in Oros per tool invocation (costs in `agents_catalog.py → TOOL_NAMES`). Admins are fully exempt. Trial oros are assigned on registration.

## Environment Variables

See [`backend/.env.example`](backend/.env.example) for all required variables.

Critical:
- `OPENAI_API_KEY` — required for E1 console tool-calling (gpt-4o-mini)
- `GROQ_API_KEY` — fast generation tasks (llama-3.1-8b-instant)
- `JWT_SECRET` — rotate with care (invalidates all active sessions)
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — seeded on every startup

## Deployment

GitHub Actions in `.github/workflows/`:
- `ci.yml` — lint + tests + docker build check on every PR/push
- `deploy.yml` — SSH deploy to VPS on push to `main`

Required GitHub secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`

## Project Structure

```
lluvia-app-studio/
├── backend/
│   ├── server.py          # FastAPI entry point, router registration
│   ├── console.py         # E1 orchestrator: sessions, tool-calling, 91 tools
│   ├── agents_catalog.py  # Agent definitions + tool cost map
│   ├── llm_router.py      # LLM provider selection (OpenAI/Groq/OpenRouter)
│   ├── auth.py            # JWT auth + bcrypt
│   ├── credits.py         # Oros credit system
│   ├── e[2-11]_*.py       # Specialist sub-orchestrators
│   ├── actions/           # Shared utilities (GitHub, shell, provisioning)
│   ├── tests/             # Integration tests
│   ├── Dockerfile
│   └── .env.example
├── frontend/              # React SPA source
├── .github/workflows/     # CI/CD pipelines
├── docker-compose.yml
├── nginx.conf
├── CLAUDE.md
└── README.md
```

## License

Proprietary — Lluvia App Studio © 2026

# Changelog

All notable changes to Lluvia App Studio are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.0.0] — 2026-05-28

### Added
- **E1 Orchestrator** — Supreme Orchestrator with 91 tools across 10 categories
- **CTO Layer** (12 tools): `analyze_architecture`, `smart_rollback`, `self_diagnostic`,
  `auto_fix_build`, `dependency_audit`, `security_scan_basic`, `audit_log_search`,
  `service_health_check`, `queue_monitor`, `git_diff_summary`, `process_manager`, `inspect_config`
- **`get_console_client()`** in `llm_router.py` — dedicated client for tool-calling sessions;
  uses OpenAI gpt-4o-mini → OpenRouter → Groq 70b fallback (Groq 8b is unreliable for tools)
- **Tool pinning** in `_select_tools_for_message()` — tools named explicitly in the user message
  are protected from `_MAX_TOOLS_PER_REQUEST` trimming
- **Admin tool charge bypass** — `if cost > 0 and not is_admin:` prevents admin from hitting
  "saldo insuficiente" on tool execution
- `GROQ_CONSOLE_MODEL` env var to override Groq console model (default: `llama-3.3-70b-versatile`)
- `CONSOLE_LLM_PROVIDER` env var to force a specific LLM provider for the console
- `CLAUDE.md` — architecture guide for Claude Code AI assistant sessions
- `Makefile` with targets: `up`, `down`, `build`, `restart`, `logs`, `test`, `lint`, `status`, `deploy-local`
- `.github/workflows/ci.yml` — lint + integration tests + docker build on PR/push
- `.github/workflows/deploy.yml` — SSH deploy to VPS on push to `main`
- `backend/.env.example` — complete environment variable template
- `CHANGELOG.md`, `CONTRIBUTING.md`

### Changed
- `_MAX_TOOLS_PER_REQUEST` reduced 20 → 15 (Groq 6000 TPM limit was exceeded with 17 CTO tools)
- `.gitignore` rewritten: excludes `backend/uploads/`, `backend/generated_apps/`, binaries, `.env`
- `README.md` replaced with enterprise-level documentation including architecture diagram, stack table, quickstart, and project structure

### Removed
- 31 tracked binary/generated files: uploads (AI images, videos), generated HTML apps
- Legacy internal documents: `CLAUDE_V12_28/29_STATUS.md`, `CLAUDE_VPS_BUILD_PLAN.md`, `HANDOFF_TO_CLAUDE_VPS.md`, `test_result.md`

### Fixed
- Admin users were incorrectly charged oros for tool execution despite being exempt
- `analyze_architecture` and other explicitly-named tools were dropped when tool list exceeded 15
- Groq `llama-3.1-8b-instant` used for console tool-calling (replaced with gpt-4o-mini)
- Groq 413 error: request with 17 admin tools exceeded 6000 TPM limit

---

## [0.12.29] — 2026-05-20

### Added
- **smart_rollback** tool with full rollback + forward cycle (docker cp + sync + healthcheck)
- **self_diagnostic** real metrics from `/proc` (CPU, RAM, disk)
- E1 expanded to 79 tools: Master Console + advanced generators + Comms layer
- E1 expanded to 64 tools: Senior Architect AI + Dynamic Tool Selector
- Dynamic tool selector (`_select_tools_for_message`) — keyword-based bundle matching
  to stay within Groq 8B token limits

### Changed
- E1 system prompt updated to reflect full 79-tool catalog
- Token optimization: `_MAX_TOOLS_PER_REQUEST = 20`, bundle-based selection

---

## [0.12.0] — 2026-05-15

### Added
- E2–E11 enterprise sub-orchestrators (Infra, Builder, Sales, Whitelabel, Legal, Billing, Support, Analytics, Social, Gmail)
- Per-module `create_indexes()` for all collections
- VPS provisioning: `vps_manager.py`, `setup-cliente.sh`
- Multi-platform messaging: Telegram, WhatsApp (Meta), Instagram webhooks
- Credit system ("Oros") with per-tool cost map in `agents_catalog.py`
- PayPal billing integration
- App templates: Audio Room, TikTok clone
- User workspace with file read/write/search
- Agency view for multi-tenant management

---

[Unreleased]: https://github.com/melvinnavas79-del/lluvia-app-studio-v12.29/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/melvinnavas79-del/lluvia-app-studio-v12.29/compare/v0.12.29...v1.0.0
[0.12.29]: https://github.com/melvinnavas79-del/lluvia-app-studio-v12.29/compare/v0.12.0...v0.12.29
[0.12.0]: https://github.com/melvinnavas79-del/lluvia-app-studio-v12.29/releases/tag/v0.12.0

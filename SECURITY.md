# Security

## Reporting a Vulnerability

Email: lluviaappstudio@gmail.com  
Response time: 48 hours. Include description, reproduction steps, and impact assessment.

---

## Architecture

### Authentication
- **JWT Bearer tokens** — HS256, 8-hour expiry, signed with `JWT_SECRET`
- **bcrypt** password hashing (cost 12)
- `seed_admin()` runs on every startup — migrates admin credentials from `.env` without duplicates
- Roles: `admin` | `affiliate` | `user`

### Authorization
- `auth.require_admin` dependency — HTTP 403 if `role != "admin"`
- Admin role is read from MongoDB on every request (not trusted from JWT payload alone)
- Tool-level gates in `_exec_tool()`: admin-only tools return error JSON for non-admins

### Shell Safety
`security.py → is_command_safe()` blocks destructive patterns before any shell execution (rm -rf, credential exfiltration, direct DB wipes).

### Rate Limiting
`slowapi` middleware: 8/min on login, 6/min on register, per-endpoint limits on public routes.

### Secret Management
- All secrets in `backend/.env` — never committed (`.gitignore` enforced)
- `backend/.env.example` contains only placeholder values
- API keys loaded via `os.getenv()` — never hardcoded in source

### Key Variables (rotate carefully)

| Variable | Effect of rotation |
|----------|--------------------|
| `JWT_SECRET` | Invalidates **all** active user sessions |
| `ADMIN_PASSWORD` | Takes effect on next startup via `seed_admin()` |
| `MASTER_KEY` | Affects VPS encrypted storage |
| `VPS_ENCRYPTION_KEY` | Re-encryption required for existing client configs |

### Infrastructure
- MongoDB on private Docker network — not exposed externally
- Ports bound to `127.0.0.1` only — external access via reverse proxy (Caddy/Nginx)
- `/var/run/docker.sock` mounted in backend container — required for VPS provisioning; only accessible via admin-gated tools

### Production Checklist
- [ ] Unique `JWT_SECRET` (`openssl rand -hex 32`)
- [ ] Unique `MASTER_KEY`
- [ ] Strong `ADMIN_PASSWORD` (not default)
- [ ] HTTPS via Caddy auto-SSL or manual cert
- [ ] `TELEGRAM_POLLING=0` — use webhooks in production
- [ ] Rotate all placeholder API keys
- [ ] Restrict `CORS_ORIGINS` to your domain

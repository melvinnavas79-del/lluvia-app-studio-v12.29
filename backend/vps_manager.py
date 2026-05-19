"""
vps_manager.py - VPS multi-tenant: cada usuario conecta sus VPS (Contabo, Hetzner, etc)
y el agente IA puede ejecutar comandos, deployar apps, abrir terminales, ver logs.

Endpoints:
  POST   /api/me/vps                       Crear conexion SSH a un VPS (cifra la key)
  GET    /api/me/vps                       Listar mis VPS
  DELETE /api/me/vps/{vps_id}              Borrar
  POST   /api/me/vps/{vps_id}/test         Validar conexion SSH (returns os_distro, free_disk)
  POST   /api/me/vps/{vps_id}/exec         Ejecutar comando shell (privilegiado, owner only)
  POST   /api/me/vps/{vps_id}/deploy-app   Desplegar una app del workspace al VPS
  GET    /api/me/vps/{vps_id}/deployments  Listar deploys hechos en ese VPS
  POST   /api/me/vps/{vps_id}/restart-service/{service}  systemctl restart
  GET    /api/me/vps/{vps_id}/tail-logs    Trae las ultimas N lineas del journal de un service

Modelo Mongo:
  vps_servers      - configs de SSH (ssh_key cifrada con AES-GCM)
  vps_deployments  - historial de apps deployadas
  vps_ports        - assignment de puertos para evitar colision
"""

import os
import re
import uuid
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from crypto_utils import encrypt_str, decrypt_str

logger = logging.getLogger("vps_manager")
router = APIRouter(prefix="/me/vps", tags=["vps_manager"])

_db_ref: dict = {"db": None}

# Rango de puertos disponibles para apps deployadas
PORT_BASE = int(os.environ.get("VPS_APP_PORT_BASE", "8042"))
PORT_MAX = int(os.environ.get("VPS_APP_PORT_MAX", "8999"))
APPS_BASE_PATH = os.environ.get("VPS_APPS_BASE_PATH", "/opt/lluvia-apps")


def set_db(db) -> None:
    _db_ref["db"] = db


# ============================================================
# Modelos
# ============================================================
class VpsIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    host: str = Field(..., min_length=3, max_length=120)
    port: int = Field(22, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=60)
    ssh_key: Optional[str] = Field(None, max_length=8000)  # PEM privado
    password: Optional[str] = Field(None, max_length=200)  # alternativo a ssh_key


class ExecIn(BaseModel):
    command: str = Field(..., min_length=1, max_length=4000)
    timeout_sec: int = Field(60, ge=1, le=600)


class DeployIn(BaseModel):
    app_slug: str = Field(..., min_length=1, max_length=80)
    repo_url: str = Field(..., min_length=10, max_length=400)
    domain: Optional[str] = Field(None, max_length=200)
    env_vars: Optional[dict] = None


# ============================================================
# SSH helpers (asyncssh)
# ============================================================
async def _connect_ssh(vps: dict):
    """Devuelve un asyncssh connection abierto. Caller debe cerrarlo con `async with`."""
    import asyncssh
    kwargs = {
        "host": vps["host"],
        "port": int(vps.get("port") or 22),
        "username": vps["username"],
        "known_hosts": None,  # confiar - en produccion deberias pinear hosts
        "connect_timeout": 10,
    }
    if vps.get("ssh_key_encrypted"):
        key_pem = decrypt_str(vps["ssh_key_encrypted"])
        kwargs["client_keys"] = [asyncssh.import_private_key(key_pem)]
    elif vps.get("password_encrypted"):
        kwargs["password"] = decrypt_str(vps["password_encrypted"])
    else:
        raise HTTPException(400, "VPS no tiene credencial configurada (ssh_key o password)")
    return await asyncssh.connect(**kwargs)


async def _ssh_run(vps: dict, command: str, timeout: int = 60) -> dict:
    """Ejecuta un comando via SSH y devuelve {stdout, stderr, exit_code}."""
    try:
        async with await _connect_ssh(vps) as conn:
            r = await asyncio.wait_for(conn.run(command, check=False), timeout=timeout)
            return {
                "stdout": (r.stdout or "")[:50000],
                "stderr": (r.stderr or "")[:10000],
                "exit_code": r.exit_status if r.exit_status is not None else -1,
            }
    except asyncio.TimeoutError:
        return {"stdout": "", "stderr": f"Timeout despues de {timeout}s", "exit_code": -124}
    except Exception as e:
        return {"stdout": "", "stderr": f"SSH error: {e}", "exit_code": -1}


# ============================================================
# CRUD VPS
# ============================================================
@router.post("")
async def create_vps(data: VpsIn, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    if not data.ssh_key and not data.password:
        raise HTTPException(400, "Debes enviar ssh_key o password (recomendado: ssh_key).")
    vps_id = str(uuid.uuid4())
    doc = {
        "id": vps_id,
        "user_id": user["id"],
        "name": data.name.strip(),
        "host": data.host.strip(),
        "port": data.port,
        "username": data.username.strip(),
        "ssh_key_encrypted": encrypt_str(data.ssh_key) if data.ssh_key else None,
        "password_encrypted": encrypt_str(data.password) if data.password else None,
        "auth_method": "ssh_key" if data.ssh_key else "password",
        "os_distro": "unknown",
        "status": "unknown",
        "last_check": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Upsert: si mismo host+user_id existe, lo actualizamos
    await db.vps_servers.update_one(
        {"user_id": user["id"], "host": doc["host"]},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True, "vps_id": vps_id, "name": doc["name"], "host": doc["host"]}


@router.get("")
async def list_my_vps(user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    cur = db.vps_servers.find(
        {"user_id": user["id"]},
        {"_id": 0, "ssh_key_encrypted": 0, "password_encrypted": 0},
    ).sort("created_at", -1)
    items = [d async for d in cur]
    return {"vps": items}


@router.delete("/{vps_id}")
async def delete_vps(vps_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    r = await db.vps_servers.delete_one({"id": vps_id, "user_id": user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "VPS no encontrado")
    return {"ok": True}


# ============================================================
# Test connection
# ============================================================
@router.post("/{vps_id}/test")
async def test_vps(vps_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    if not vps:
        raise HTTPException(404, "VPS no encontrado")
    probe = await _ssh_run(vps, "uname -srm && python3 --version 2>/dev/null && df -BG /opt 2>/dev/null | tail -1 && which nginx git", timeout=15)
    ok = probe["exit_code"] == 0
    os_info = (probe["stdout"] or "").splitlines()
    detected = {
        "uname": os_info[0] if os_info else "unknown",
        "python": next((line for line in os_info if "Python" in line), "no python3"),
        "disk": next((line for line in os_info if "G" in line and "/" in line), "?"),
        "has_nginx": any("nginx" in line for line in os_info),
        "has_git": any("/git" in line for line in os_info),
    }
    await db.vps_servers.update_one(
        {"id": vps_id},
        {"$set": {
            "status": "connected" if ok else "error",
            "os_distro": detected["uname"],
            "last_check": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {
        "ok": ok,
        "exit_code": probe["exit_code"],
        "detected": detected,
        "stdout": probe["stdout"][:2000],
        "stderr": probe["stderr"][:1000],
    }


# ============================================================
# Exec
# ============================================================
@router.post("/{vps_id}/exec")
async def exec_on_vps(vps_id: str, data: ExecIn, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    if not vps:
        raise HTTPException(404, "VPS no encontrado")
    # Bloqueo de comandos suicidas obvios
    blocked = ["rm -rf /", "mkfs", ":(){:|:&};:", "> /etc/passwd", "shutdown", "reboot"]
    if any(b in data.command for b in blocked):
        raise HTTPException(400, f"Comando bloqueado por seguridad: '{data.command[:40]}'")
    result = await _ssh_run(vps, data.command, timeout=data.timeout_sec)
    return result


# ============================================================
# Port assignment
# ============================================================
async def _next_free_port(db, vps_id: str) -> int:
    """Asigna el siguiente puerto libre en [PORT_BASE, PORT_MAX]."""
    used = set()
    async for d in db.vps_deployments.find(
        {"vps_id": vps_id, "status": {"$ne": "removed"}}, {"_id": 0, "port": 1}
    ):
        if d.get("port"):
            used.add(int(d["port"]))
    for p in range(PORT_BASE, PORT_MAX + 1):
        if p not in used:
            return p
    raise HTTPException(500, "No hay puertos libres en este VPS")


# ============================================================
# Deploy app
# ============================================================
def _safe_slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (s or "").lower()).strip("-")
    return s[:60] or "app"


@router.post("/{vps_id}/deploy-app")
async def deploy_app_to_vps(vps_id: str, data: DeployIn, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    if not vps:
        raise HTTPException(404, "VPS no encontrado")

    app_slug = _safe_slug(data.app_slug)
    service_name = f"lluvia-{app_slug}"
    port = await _next_free_port(db, vps_id)
    deploy_id = str(uuid.uuid4())
    app_path = f"{APPS_BASE_PATH}/{app_slug}"

    # Pre-crear registro
    await db.vps_deployments.insert_one({
        "id": deploy_id,
        "user_id": user["id"],
        "vps_id": vps_id,
        "app_slug": app_slug,
        "repo_url": data.repo_url,
        "domain": data.domain,
        "status": "building",
        "port": port,
        "service_name": service_name,
        "https_enabled": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "error": None,
        "steps": [],
    })

    steps = []

    async def _step(label: str, cmd: str, timeout: int = 120):
        r = await _ssh_run(vps, cmd, timeout=timeout)
        steps.append({"step": label, "exit_code": r["exit_code"], "out": (r["stdout"] or "")[:500]})
        return r["exit_code"] == 0, r

    # 1. Crear path base
    ok, _ = await _step("mkdir", f"sudo mkdir -p {APPS_BASE_PATH} && sudo chown -R $USER {APPS_BASE_PATH}")
    if not ok:
        return await _fail_deploy(db, deploy_id, "No pude crear el path base", steps)

    # 2. Clone (con fallback a pull si ya existe)
    ok, _ = await _step("git", f"if [ -d {app_path}/.git ]; then cd {app_path} && git pull; else git clone {data.repo_url} {app_path}; fi", timeout=180)
    if not ok:
        return await _fail_deploy(db, deploy_id, "git clone fallo", steps)

    # 3. venv + deps
    ok, _ = await _step("venv", f"cd {app_path}/backend && python3 -m venv venv && ./venv/bin/pip install --upgrade pip", timeout=120)
    if not ok:
        return await _fail_deploy(db, deploy_id, "venv create fallo", steps)

    ok, _ = await _step("pip", f"cd {app_path}/backend && ./venv/bin/pip install -r requirements.txt", timeout=300)
    if not ok:
        return await _fail_deploy(db, deploy_id, "pip install fallo", steps)

    # 4. .env con JWT_SECRET random
    env_lines = [f"PORT={port}", "JWT_SECRET=$(openssl rand -hex 32)"]
    if data.env_vars:
        for k, v in (data.env_vars or {}).items():
            if re.match(r"^[A-Z_][A-Z0-9_]*$", str(k)):
                env_lines.append(f"{k}={str(v)[:500]}")
    env_content = "\n".join(env_lines)
    ok, _ = await _step("env", f"cd {app_path}/backend && (echo '{env_content}') > .env && sed -i 's|JWT_SECRET=.*|JWT_SECRET='\"$(openssl rand -hex 32)\"'|' .env")
    if not ok:
        return await _fail_deploy(db, deploy_id, ".env crear fallo", steps)

    # 5. systemd unit
    unit = f"""[Unit]
Description=Lluvia App: {app_slug}
After=network.target

[Service]
Type=simple
WorkingDirectory={app_path}/backend
EnvironmentFile={app_path}/backend/.env
ExecStart={app_path}/backend/venv/bin/uvicorn server:app --host 0.0.0.0 --port {port}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    # Escapar comillas para echo
    unit_b64 = unit.encode("utf-8").hex()
    ok, _ = await _step(
        "systemd",
        f"echo '{unit_b64}' | xxd -r -p | sudo tee /etc/systemd/system/{service_name}.service > /dev/null"
        f" && sudo systemctl daemon-reload"
        f" && sudo systemctl enable {service_name}"
        f" && sudo systemctl restart {service_name}",
        timeout=30,
    )
    if not ok:
        return await _fail_deploy(db, deploy_id, "systemd unit creation fallo", steps)

    # 6. Verificar que arranco
    await asyncio.sleep(3)
    ok, status_check = await _step("status", f"sudo systemctl is-active {service_name} && curl -s --max-time 5 http://localhost:{port}/api/health || echo 'no-health-endpoint'")
    running = "active" in (status_check.get("stdout", "") if isinstance(status_check, dict) else "")

    # 7. Opcional: nginx + certbot
    nginx_configured = False
    https_enabled = False
    if data.domain:
        nginx_conf = f"""server {{
    listen 80;
    server_name {data.domain};
    location / {{
        proxy_pass http://localhost:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
        conf_b64 = nginx_conf.encode("utf-8").hex()
        ok_nginx, _ = await _step(
            "nginx",
            f"echo '{conf_b64}' | xxd -r -p | sudo tee /etc/nginx/sites-available/{data.domain} > /dev/null"
            f" && sudo ln -sf /etc/nginx/sites-available/{data.domain} /etc/nginx/sites-enabled/{data.domain}"
            f" && sudo nginx -t && sudo systemctl reload nginx",
            timeout=20,
        )
        nginx_configured = ok_nginx

        if nginx_configured:
            ok_ssl, _ = await _step(
                "certbot",
                f"sudo certbot --nginx -d {data.domain} --non-interactive --agree-tos --email {user.get('email','admin@lluvia.app')} --redirect || true",
                timeout=120,
            )
            https_enabled = ok_ssl

    await db.vps_deployments.update_one(
        {"id": deploy_id},
        {"$set": {
            "status": "running" if running else "failed",
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "https_enabled": https_enabled,
            "nginx_configured": nginx_configured,
            "steps": steps,
        }},
    )

    return {
        "ok": running,
        "deploy_id": deploy_id,
        "service_name": service_name,
        "port": port,
        "url_local": f"http://{vps['host']}:{port}",
        "url_https": f"https://{data.domain}" if https_enabled else None,
        "url_http": f"http://{data.domain}" if (nginx_configured and not https_enabled) else None,
        "steps": steps,
    }


async def _fail_deploy(db, deploy_id: str, error: str, steps: list):
    await db.vps_deployments.update_one(
        {"id": deploy_id},
        {"$set": {"status": "failed", "error": error, "steps": steps,
                  "ended_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": False, "deploy_id": deploy_id, "error": error, "steps": steps}


# ============================================================
# Service management
# ============================================================
@router.post("/{vps_id}/restart-service/{service}")
async def restart_service(vps_id: str, service: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    if not vps:
        raise HTTPException(404, "VPS no encontrado")
    safe = re.sub(r"[^a-z0-9._-]", "", service)
    if not safe.startswith("lluvia-"):
        raise HTTPException(400, "Solo podes reiniciar servicios que empiecen con 'lluvia-'")
    r = await _ssh_run(vps, f"sudo systemctl restart {safe} && sudo systemctl is-active {safe}", timeout=30)
    return {"ok": r["exit_code"] == 0, **r}


@router.get("/{vps_id}/tail-logs")
async def tail_logs(vps_id: str, service: str, lines: int = 100,
                    user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    if not vps:
        raise HTTPException(404, "VPS no encontrado")
    safe = re.sub(r"[^a-z0-9._-]", "", service)
    n = max(10, min(int(lines or 100), 1000))
    r = await _ssh_run(vps, f"sudo journalctl -u {safe} -n {n} --no-pager", timeout=15)
    return r


@router.get("/{vps_id}/deployments")
async def list_deployments(vps_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    cur = db.vps_deployments.find(
        {"vps_id": vps_id, "user_id": user["id"]},
        {"_id": 0, "steps": 0},
    ).sort("started_at", -1).limit(50)
    return {"deployments": [d async for d in cur]}


@router.delete("/{vps_id}/deployments/{deploy_id}")
async def undeploy(vps_id: str, deploy_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    vps = await db.vps_servers.find_one({"id": vps_id, "user_id": user["id"]})
    dep = await db.vps_deployments.find_one({"id": deploy_id, "user_id": user["id"]})
    if not vps or not dep:
        raise HTTPException(404, "VPS o deploy no encontrado")
    svc = dep["service_name"]
    slug = dep["app_slug"]
    cmd = (
        f"sudo systemctl stop {svc} 2>/dev/null; "
        f"sudo systemctl disable {svc} 2>/dev/null; "
        f"sudo rm -f /etc/systemd/system/{svc}.service; "
        f"sudo systemctl daemon-reload; "
        f"sudo rm -rf {APPS_BASE_PATH}/{slug}; "
        f"echo 'removed'"
    )
    r = await _ssh_run(vps, cmd, timeout=30)
    await db.vps_deployments.update_one(
        {"id": deploy_id},
        {"$set": {"status": "removed", "ended_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": r["exit_code"] == 0, **r}

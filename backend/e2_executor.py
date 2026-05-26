"""
============================================================
E2 EXECUTOR — Execution layer real para E2 infra
STATUS: REAL (requiere VPS configurado vía env vars o db)

Conecta los tools de E2 a ejecución real via SSH (asyncssh).
Additive: no modifica vps_manager.py ni server.py.

Variables de entorno (platform VPS):
  E2_VPS_HOST      — host del VPS de la plataforma
  E2_VPS_USER      — usuario SSH (default: root)
  E2_VPS_PASSWORD  — contraseña SSH
  E2_VPS_SSH_KEY   — clave privada SSH (PEM completo, alternativo a password)
  E2_VPS_PORT      — puerto SSH (default: 22)

Funciones públicas:
  run_shell(command, timeout)            — ejecuta bash en el VPS de plataforma
  run_docker(action, container, ...)     — docker ps/restart/logs/inspect
  run_deploy(repo_url, service, branch)  — git pull + restart
  run_ssl(domain, action)                — certbot renew/status
  service_status(service)               — systemctl status
  system_metrics()                       — CPU/RAM/disk del VPS
============================================================
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("e2_executor")

# ── VPS platform config from env ───────────────────────────────────────────────
_VPS_HOST     = os.environ.get("E2_VPS_HOST", "")
_VPS_USER     = os.environ.get("E2_VPS_USER", "root")
_VPS_PASSWORD = os.environ.get("E2_VPS_PASSWORD", "")
_VPS_SSH_KEY  = os.environ.get("E2_VPS_SSH_KEY", "")
_VPS_PORT     = int(os.environ.get("E2_VPS_PORT", "22"))

# ── Command blocklist — never execute these regardless of context ───────────────
_BLOCKED = frozenset({
    "rm -rf /", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:",
    "shutdown", "reboot", "halt", "poweroff",
    "chmod 777 /", "chown root /",
})


def _platform_vps_doc() -> Optional[dict]:
    """Construye un pseudo-doc VPS desde las env vars del servidor."""
    if not _VPS_HOST:
        return None
    doc: dict = {
        "host": _VPS_HOST,
        "port": _VPS_PORT,
        "username": _VPS_USER,
    }
    if _VPS_PASSWORD:
        doc["password_encrypted"] = None
        doc["_raw_password"] = _VPS_PASSWORD
    if _VPS_SSH_KEY:
        doc["_raw_ssh_key"] = _VPS_SSH_KEY
    return doc


async def _ssh_run_raw(host: str, port: int, username: str,
                       password: Optional[str], ssh_key: Optional[str],
                       command: str, timeout: int = 60) -> dict:
    """Executes command via SSH. Returns {stdout, stderr, exit_code}."""
    try:
        import asyncssh
    except ImportError:
        return {"stdout": "", "stderr": "asyncssh not installed", "exit_code": -1,
                "status": "error"}

    kwargs: dict = {
        "host":             host,
        "port":             port,
        "username":         username,
        "known_hosts":      None,
        "connect_timeout":  10,
    }
    if ssh_key:
        kwargs["client_keys"] = [asyncssh.import_private_key(ssh_key)]
    elif password:
        kwargs["password"] = password
    else:
        return {"stdout": "", "stderr": "No credentials configured for E2_VPS",
                "exit_code": -1, "status": "no_credentials"}

    try:
        async with await asyncssh.connect(**kwargs) as conn:
            r = await asyncio.wait_for(conn.run(command, check=False), timeout=timeout)
            return {
                "stdout":    (r.stdout or "")[:50000],
                "stderr":    (r.stderr or "")[:10000],
                "exit_code": r.exit_status if r.exit_status is not None else -1,
                "status":    "ok" if (r.exit_status == 0) else "error",
            }
    except asyncio.TimeoutError:
        return {"stdout": "", "stderr": f"Timeout after {timeout}s", "exit_code": -124, "status": "timeout"}
    except Exception as exc:
        return {"stdout": "", "stderr": f"SSH error: {exc}", "exit_code": -1, "status": "ssh_error"}


async def run_shell(command: str, timeout: int = 60) -> dict:
    """
    STATUS: REAL (si E2_VPS_HOST configurado)
    Ejecuta un comando bash en el VPS de la plataforma.
    """
    for blocked in _BLOCKED:
        if blocked in command:
            return {"stdout": "", "stderr": f"Blocked command: {blocked!r}",
                    "exit_code": -403, "status": "blocked"}

    vps = _platform_vps_doc()
    if not vps:
        return {"stdout": "", "stderr": "E2_VPS_HOST not configured",
                "exit_code": -1, "status": "not_configured"}

    result = await _ssh_run_raw(
        host=vps["host"],
        port=vps.get("port", 22),
        username=vps.get("username", "root"),
        password=vps.get("_raw_password"),
        ssh_key=vps.get("_raw_ssh_key"),
        command=command,
        timeout=timeout,
    )
    logger.info(f"[e2] shell_run exit={result['exit_code']} cmd={command[:80]!r}")
    return result


async def service_status(service: str) -> dict:
    """
    STATUS: REAL (si E2_VPS_HOST configurado)
    Retorna status de un systemd service.
    """
    r = await run_shell(f"systemctl is-active {service} 2>&1 && systemctl status {service} --no-pager -l | head -30", timeout=15)
    active = "active" in r.get("stdout", "").lower()
    return {
        "service":   service,
        "active":    active,
        "stdout":    r.get("stdout", ""),
        "exit_code": r.get("exit_code", -1),
        "ts":        datetime.now(timezone.utc).isoformat(),
        "status_detail": "REAL" if _VPS_HOST else "not_configured",
    }


async def run_docker(action: str, container: str = "", extra: str = "") -> dict:
    """
    STATUS: REAL (si E2_VPS_HOST configurado)
    Operaciones Docker: ps, restart, logs, inspect, stop, start.
    """
    safe_actions = {
        "ps":      "docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'",
        "inspect": f"docker inspect {container} 2>&1 | head -100" if container else "docker ps",
        "logs":    f"docker logs --tail 100 {container} 2>&1" if container else "",
        "restart": f"docker restart {container} 2>&1" if container else "",
        "stop":    f"docker stop {container} 2>&1" if container else "",
        "start":   f"docker start {container} 2>&1" if container else "",
        "stats":   "docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'",
    }
    cmd = safe_actions.get(action)
    if not cmd:
        return {"ok": False, "error": f"Unknown docker action: {action!r}"}

    r = await run_shell(cmd, timeout=30)
    return {
        "ok":        r.get("exit_code", -1) == 0,
        "action":    action,
        "container": container,
        "stdout":    r.get("stdout", ""),
        "stderr":    r.get("stderr", ""),
        "ts":        datetime.now(timezone.utc).isoformat(),
    }


async def run_deploy(repo_url: str, service: str, branch: str = "main") -> dict:
    """
    STATUS: REAL (si E2_VPS_HOST configurado)
    git pull + supervisor/systemctl restart.
    Asume que el servicio ya está deployado en /opt/{service}/.
    """
    steps = []
    service_safe = service.replace("..", "").replace("/", "").strip()[:50]
    svc_path     = f"/opt/{service_safe}"

    cmds = [
        ("git_pull",   f"cd {svc_path} && git fetch origin && git reset --hard origin/{branch}", 60),
        ("restart",    f"supervisorctl restart {service_safe} 2>&1 || systemctl restart {service_safe} 2>&1", 30),
        ("status",     f"supervisorctl status {service_safe} 2>&1 || systemctl is-active {service_safe} 2>&1", 10),
    ]

    ok_overall = True
    for step_name, cmd, timeout in cmds:
        r = await run_shell(cmd, timeout=timeout)
        step = {
            "step":      step_name,
            "exit_code": r.get("exit_code", -1),
            "stdout":    r.get("stdout", "")[:1000],
        }
        steps.append(step)
        if r.get("exit_code", -1) != 0:
            ok_overall = False
            logger.error(f"[e2] deploy step {step_name} failed: {r.get('stderr','')[:200]}")
            break

    return {
        "ok":      ok_overall,
        "service": service,
        "branch":  branch,
        "steps":   steps,
        "ts":      datetime.now(timezone.utc).isoformat(),
    }


async def run_ssl(domain: str, action: str = "status") -> dict:
    """
    STATUS: REAL (si E2_VPS_HOST configurado y certbot instalado)
    action: status | renew | issue
    """
    cmds = {
        "status": f"certbot certificates 2>&1 | grep -A5 {domain}",
        "renew":  f"certbot renew --cert-name {domain} --non-interactive 2>&1",
        "issue":  f"certbot --nginx -d {domain} --non-interactive --agree-tos 2>&1",
    }
    cmd = cmds.get(action, f"certbot certificates 2>&1 | grep -A5 {domain}")
    r   = await run_shell(cmd, timeout=120)
    return {
        "ok":      r.get("exit_code", -1) == 0,
        "domain":  domain,
        "action":  action,
        "stdout":  r.get("stdout", ""),
        "stderr":  r.get("stderr", ""),
        "ts":      datetime.now(timezone.utc).isoformat(),
    }


async def system_metrics() -> dict:
    """
    STATUS: REAL (si E2_VPS_HOST configurado)
    CPU, RAM, disco, procesos del VPS de la plataforma.
    """
    cmd = (
        "echo CPU_IDLE=$(top -bn1 | grep 'Cpu(s)' | awk '{print $8}') && "
        "echo MEM=$(free -m | awk '/Mem:/{printf \"%s/%sMB\", $3, $2}') && "
        "echo DISK=$(df -h / | awk 'NR==2{print $5\" used of \"$2}') && "
        "echo LOAD=$(uptime | awk -F'load average:' '{print $2}') && "
        "echo UPTIME=$(uptime -p 2>/dev/null || uptime)"
    )
    r = await run_shell(cmd, timeout=15)
    lines = r.get("stdout", "").strip().split("\n")
    parsed: dict = {}
    for line in lines:
        if "=" in line:
            k, _, v = line.partition("=")
            parsed[k.strip()] = v.strip()

    return {
        "ok":         r.get("exit_code", -1) == 0,
        "metrics":    parsed,
        "raw":        r.get("stdout", "")[:2000],
        "ts":         datetime.now(timezone.utc).isoformat(),
        "vps_host":   _VPS_HOST or "not_configured",
        "configured": bool(_VPS_HOST),
    }

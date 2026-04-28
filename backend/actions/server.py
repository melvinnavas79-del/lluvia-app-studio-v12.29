"""
========================================
ACCIONES DEL SERVIDOR
========================================

Ejecucion de comandos seguros en el servidor.
"""

import subprocess
from security import is_command_safe


def install_radio() -> str:
    """Simula la instalacion de un servicio de radio."""
    out = subprocess.getoutput("echo 'Instalando radio... [OK simulado]'")
    return f"Instalacion iniciada:\n{out}"


def run_command(cmd: str) -> str:
    """Ejecuta un comando shell tras pasar la validacion de seguridad."""
    if not cmd:
        return "Comando vacio"

    safe, reason = is_command_safe(cmd)
    if not safe:
        return f"Comando rechazado: {reason}"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        out = (result.stdout or "") + (result.stderr or "")
        return out.strip()[:2000] or "(sin salida)"
    except subprocess.TimeoutExpired:
        return "El comando tardo demasiado y fue cancelado (15s)"
    except Exception as e:
        return f"Error ejecutando comando: {e}"

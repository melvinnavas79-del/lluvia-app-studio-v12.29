"""
========================================
VALIDACIONES DE SEGURIDAD
========================================

Filtros para prevenir comandos peligrosos en el servidor.
"""

import re
from typing import Tuple

# Lista negra de comandos peligrosos
DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/",          # Borrado masivo
    r"\bmkfs\b",                # Formateo
    r"\bdd\s+if=",              # Disco
    r":\(\)\s*\{",              # Fork bomb
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r">\s*/dev/sd[a-z]",        # Escribir en disco crudo
    r"\bchmod\s+-R\s+777\s+/",  # Permisos peligrosos
    r"\bcurl\b.*\|\s*(bash|sh)", # Pipe a shell
    r"\bwget\b.*\|\s*(bash|sh)",
    r"\beval\s*\(",
    r"sudo\s+passwd",
]


def is_command_safe(cmd: str) -> Tuple[bool, str]:
    """
    Verifica si un comando es seguro de ejecutar.
    Returns: (es_seguro, razon_si_no)
    """
    if not cmd or not isinstance(cmd, str):
        return False, "Comando vacio o invalido"

    cmd_lower = cmd.lower().strip()

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd_lower):
            return False, f"Comando bloqueado por seguridad (patron: {pattern})"

    # Limite de longitud
    if len(cmd) > 500:
        return False, "Comando demasiado largo"

    return True, "OK"


def sanitize_text(text: str, max_len: int = 4000) -> str:
    """Limpia texto de entrada del usuario."""
    if not text:
        return ""
    text = str(text).strip()
    return text[:max_len]


def validate_webhook_token(received: str, expected: str) -> bool:
    """Validacion simple de token de webhook."""
    if not expected or not received:
        return False
    return received == expected

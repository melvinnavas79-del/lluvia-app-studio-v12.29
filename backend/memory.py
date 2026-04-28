"""
========================================
MEMORIA DE CONVERSACION POR USUARIO
========================================

Sistema simple en memoria + persistencia opcional en MongoDB.
"""

from typing import Dict, List
from datetime import datetime, timezone

# Memoria en RAM (rapida)
_memory: Dict[str, List[dict]] = {}

# Limite de mensajes por usuario para no saturar el contexto
MAX_HISTORY = 20


def save(user: str, role: str, content: str) -> None:
    """Guarda un mensaje en el historial del usuario."""
    user = str(user)
    if user not in _memory:
        _memory[user] = []
    _memory[user].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    # Recortar historial
    if len(_memory[user]) > MAX_HISTORY * 2:
        _memory[user] = _memory[user][-MAX_HISTORY * 2:]


def get(user: str) -> List[dict]:
    """Obtiene el historial de un usuario."""
    return _memory.get(str(user), [])


def get_text_history(user: str, limit: int = 10) -> str:
    """Devuelve el historial reciente como texto plano para el prompt."""
    history = get(user)[-limit:]
    if not history:
        return "(sin historial previo)"
    lines = []
    for m in history:
        prefix = "Usuario" if m["role"] == "user" else "Asistente"
        lines.append(f"{prefix}: {m['content']}")
    return "\n".join(lines)


def clear(user: str) -> None:
    """Borra el historial de un usuario."""
    _memory.pop(str(user), None)


def all_users() -> List[str]:
    """Lista todos los usuarios con historial."""
    return list(_memory.keys())


def stats() -> dict:
    """Estadisticas de uso."""
    return {
        "total_users": len(_memory),
        "total_messages": sum(len(v) for v in _memory.values()),
    }

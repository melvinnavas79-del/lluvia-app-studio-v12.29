"""
Rate limiting global para endpoints sensibles (auth, paypal, voice).
- 5 logins por minuto por IP
- 30 mensajes de chat por minuto por IP
- 10 creaciones de orden PayPal por hora por IP
- 20 calls de voz por minuto por IP

Uso: aplicar @limiter.limit("5/minute") al endpoint y aceptar `request: Request`.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from fastapi.responses import JSONResponse


def _key(request: Request) -> str:
    # Confiamos en X-Forwarded-For si esta detras de Caddy/Nginx
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_key, default_limits=[])


def rate_limit_exceeded_handler(request: Request, exc) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(
        status_code=429,
        content={"detail": f"Limite alcanzado: {exc.detail}. Reintenta luego."},
    )

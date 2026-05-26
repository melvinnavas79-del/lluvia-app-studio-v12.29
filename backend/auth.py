"""
========================================
AUTENTICACION JWT + BCRYPT
========================================

Sistema 100% propio. Sin dependencias externas.
- Bearer token en header Authorization
- bcrypt para hash de passwords
- Roles: admin / affiliate
"""

import os
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request, Depends
from typing import Optional

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60 * 8  # 8 horas


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _get_secret() -> str:
    return os.environ["JWT_SECRET"]


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalido")


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


# Inyectado desde server.py
_db_ref = {"db": None}


def set_db(db):
    _db_ref["db"] = db


async def get_current_user(request: Request) -> dict:
    """Dependency que valida el token y carga el usuario desde MongoDB."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")

    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Tipo de token invalido")

    db = _db_ref["db"]
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Usuario desactivado")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Requiere rol admin")
    return user


async def seed_admin(db) -> None:
    """
    Garantiza que exista exactamente UN admin con el email/password de .env.
    Si cambia el email en .env, migra el admin existente (no crea uno nuevo).
    Si cambia la password en .env, actualiza el hash.
    """
    import uuid
    import logging as _log
    email = os.environ.get("ADMIN_EMAIL", "admin@admin.com").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "Admin#2026")
    if password == "Admin#2026":
        _log.warning(
            "SEGURIDAD: ADMIN_PASSWORD no configurado — usando contraseña por defecto. "
            "Configura ADMIN_PASSWORD en .env antes de exponer en producción."
        )

    # 1) Caso ideal: ya existe admin con ese email
    existing_target = await db.users.find_one({"email": email, "role": "admin"})
    if existing_target:
        if not verify_password(password, existing_target["password_hash"]):
            await db.users.update_one(
                {"id": existing_target["id"]},
                {"$set": {"password_hash": hash_password(password)}},
            )
        return

    # 2) Existe algun otro admin? -> migrar (cambiar su email/password)
    other_admin = await db.users.find_one({"role": "admin"})
    if other_admin:
        # Asegurar unicidad del nuevo email (no debe colisionar con otro user)
        clash = await db.users.find_one({"email": email})
        if clash:
            import logging
            logging.getLogger("auth").warning(
                f"seed_admin: no se pudo migrar admin a {email} porque ya existe "
                f"un usuario (rol={clash.get('role')}) con ese email. "
                f"El admin actual sigue siendo {other_admin['email']}. "
                f"Revisa ADMIN_EMAIL en .env."
            )
            return
        await db.users.update_one(
            {"id": other_admin["id"]},
            {"$set": {
                "email": email,
                "password_hash": hash_password(password),
                "name": "Administrador",
            }},
        )
        return

    # 3) No hay admin alguno -> crearlo
    await db.users.insert_one({
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": hash_password(password),
        "name": "Administrador",
        "role": "admin",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

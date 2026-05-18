"""
Agency View: panel central para que el operador vea sus clientes desplegados.
Por ahora lee del directorio /opt/lluvia/clients/ (modo VPS) o devuelve los
provisioning records guardados en Mongo (modo preview/dry-run).
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user

logger = logging.getLogger("agency_view")
router = APIRouter(prefix="/agency", tags=["agency"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


@router.get("/clients")
async def list_clients(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="solo admin")
    db = _db_ref["db"]
    items = []
    async for c in db.deployed_clients.find({}, {"_id": 0}).sort("created_at", -1).limit(500):
        items.append(c)
    # Calculo MRR estimado: cada cliente $199/mes default
    mrr = sum(int(c.get("monthly_usd", 199)) for c in items if c.get("active", True))
    return {"clients": items, "mrr_usd": mrr, "active_count": sum(1 for c in items if c.get("active", True))}

"""
workspace_files.py - Operaciones de archivos en el workspace del usuario
(/app/user_apps/{user_id}/{app_slug}/). Para el editor Monaco y el agente IA.

Endpoints:
  GET   /api/me/apps/{app_slug}/files                Tree completo
  GET   /api/me/apps/{app_slug}/file?path=...        Leer contenido
  PUT   /api/me/apps/{app_slug}/file                 Escribir (con diff guardado)
  DELETE /api/me/apps/{app_slug}/file?path=...       Borrar
  GET   /api/me/file-edits?app_slug=...              Historial de cambios
  POST  /api/me/file-edits/{edit_id}/rollback        Revertir un edit
"""

import os
import re
import uuid
import difflib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user

logger = logging.getLogger("workspace_files")
router = APIRouter(prefix="/me/apps", tags=["workspace_files"])

_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _user_apps_dir(user_id: str) -> Path:
    base = os.environ.get("LLUVIA_HOME", "/app")
    return Path(base) / "user_apps" / user_id


def _safe_path(app_dir: Path, rel_path: str) -> Path:
    """Resuelve rel_path dentro de app_dir, previniendo path-traversal."""
    rel_path = (rel_path or "").lstrip("/").replace("\\", "/")
    if ".." in rel_path.split("/"):
        raise HTTPException(400, "Path no permitido")
    candidate = (app_dir / rel_path).resolve()
    if not str(candidate).startswith(str(app_dir.resolve())):
        raise HTTPException(400, "Path fuera del workspace")
    return candidate


TEXT_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".md", ".txt",
             ".json", ".yml", ".yaml", ".toml", ".sh", ".env", ".example",
             ".gitignore", ".conf", "Dockerfile", "Procfile"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".next", "dist", "build"}
SKIP_FILES = {".DS_Store", "data.db", "data.db-journal"}


def _build_tree(root: Path) -> dict:
    """Construye un dict recursivo: {name, type, size, children}."""
    if not root.exists():
        return {"name": root.name, "type": "dir", "children": []}

    def _walk(p: Path) -> dict:
        if p.is_file():
            return {
                "name": p.name,
                "type": "file",
                "path": str(p.relative_to(root)).replace("\\", "/"),
                "size": p.stat().st_size,
                "ext": p.suffix.lower(),
            }
        children = []
        try:
            for child in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if child.name in SKIP_DIRS or child.name in SKIP_FILES:
                    continue
                children.append(_walk(child))
        except PermissionError:
            pass
        return {
            "name": p.name,
            "type": "dir",
            "path": str(p.relative_to(root)).replace("\\", "/") if p != root else "",
            "children": children,
        }
    return _walk(root)


@router.get("/{app_slug}/files")
async def list_files(app_slug: str, user: dict = Depends(get_current_user)):
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "", app_slug)[:80]
    if not safe:
        raise HTTPException(400, "app_slug invalido")
    base = _user_apps_dir(user["id"]) / safe
    if not base.exists():
        raise HTTPException(404, f"App '{safe}' no encontrada en tu workspace")
    return {"tree": _build_tree(base)}


@router.get("/{app_slug}/file")
async def read_file(app_slug: str, path: str, user: dict = Depends(get_current_user)):
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "", app_slug)[:80]
    base = _user_apps_dir(user["id"]) / safe
    f = _safe_path(base, path)
    if not f.exists() or not f.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    if f.stat().st_size > 2_000_000:
        raise HTTPException(413, "Archivo demasiado grande (>2MB)")
    try:
        content = f.read_text(encoding="utf-8")
        return {"path": path, "content": content, "size": f.stat().st_size,
                "encoding": "utf-8", "is_binary": False}
    except UnicodeDecodeError:
        return {"path": path, "is_binary": True, "size": f.stat().st_size,
                "content": "", "encoding": "binary"}


class WriteIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=400)
    content: str = Field(..., max_length=2_000_000)


@router.put("/{app_slug}/file")
async def write_file(app_slug: str, data: WriteIn, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "", app_slug)[:80]
    base = _user_apps_dir(user["id"]) / safe
    base.mkdir(parents=True, exist_ok=True)
    f = _safe_path(base, data.path)
    f.parent.mkdir(parents=True, exist_ok=True)

    old_content = ""
    if f.exists():
        try:
            old_content = f.read_text(encoding="utf-8")
        except Exception:
            old_content = ""

    f.write_text(data.content, encoding="utf-8")

    # Guardar diff para rollback
    diff = "\n".join(difflib.unified_diff(
        old_content.splitlines(), data.content.splitlines(),
        fromfile=f"a/{data.path}", tofile=f"b/{data.path}", lineterm="",
    ))
    edit_id = str(uuid.uuid4())
    await db.file_edits.insert_one({
        "id": edit_id,
        "user_id": user["id"],
        "app_slug": safe,
        "file_path": data.path,
        "diff": diff[:50000],
        "previous_content": old_content[:500_000],   # cap para rollback
        "applied_by": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "edit_id": edit_id, "size": len(data.content), "diff_lines": diff.count("\n")}


@router.delete("/{app_slug}/file")
async def delete_file(app_slug: str, path: str, user: dict = Depends(get_current_user)):
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "", app_slug)[:80]
    base = _user_apps_dir(user["id"]) / safe
    f = _safe_path(base, path)
    if not f.exists():
        raise HTTPException(404, "Archivo no encontrado")
    if f.is_file():
        f.unlink()
        return {"ok": True, "deleted": "file"}
    # Si es dir, debe estar vacio
    if any(f.iterdir()):
        raise HTTPException(400, "Directorio no vacio")
    f.rmdir()
    return {"ok": True, "deleted": "dir"}


@router.get("/_/file-edits")
async def list_edits(app_slug: Optional[str] = None, limit: int = 50,
                     user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    q = {"user_id": user["id"]}
    if app_slug:
        q["app_slug"] = re.sub(r"[^a-zA-Z0-9_.-]", "", app_slug)[:80]
    cur = db.file_edits.find(q, {"_id": 0, "previous_content": 0}).sort("created_at", -1).limit(min(int(limit), 200))
    return {"edits": [e async for e in cur]}


@router.post("/_/file-edits/{edit_id}/rollback")
async def rollback_edit(edit_id: str, user: dict = Depends(get_current_user)):
    db = _db_ref["db"]
    edit = await db.file_edits.find_one({"id": edit_id, "user_id": user["id"]})
    if not edit:
        raise HTTPException(404, "Edit no encontrado")
    base = _user_apps_dir(user["id"]) / edit["app_slug"]
    f = _safe_path(base, edit["file_path"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(edit.get("previous_content", ""), encoding="utf-8")
    await db.file_edits.update_one(
        {"id": edit_id},
        {"$set": {"rolled_back": True, "rolled_back_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "restored": edit["file_path"]}

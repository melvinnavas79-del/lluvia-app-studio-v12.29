"""
App Builder Pro - copia templates pre-construidos al workspace del usuario.

Por que NO generar codigo con el LLM:
- Cada token cuesta oros y tiempo. Un template ya testeado se materializa en
  segundos. Asi el usuario obtiene una app de calidad comercial sin esperar
  10 minutos de streaming y sin que el LLM invente APIs rotas.

Templates disponibles:
- audio_room: SPA + FastAPI + Socket.IO (Clubhouse/Spaces clone, 4 pantallas).

Como agregar mas templates:
1) Crear /app/backend/app_templates/<slug>/ con la estructura final.
2) Usar marcadores {{APP_NAME}} y {{BRAND_COLOR}} en los archivos que deban
   personalizarse.
3) Sumarlo a TEMPLATES dict de abajo.
"""

import re
import shutil
import logging
from pathlib import Path

logger = logging.getLogger("app_builder")

TEMPLATES_ROOT = Path(__file__).parent / "app_templates"

TEMPLATES = {
    "audio_room": {
        "name": "Audio Room (Clubhouse / Spaces)",
        "description": "App full-stack de salas de audio en vivo con WebRTC, 4 pantallas y monetizacion premium.",
        "path": TEMPLATES_ROOT / "audio_room",
        # Extensiones donde reemplazamos placeholders. Binarios no se tocan.
        "text_exts": {".html", ".css", ".js", ".py", ".md", ".txt", ".env", ".example", ".json", ".yml", ".yaml", ".toml", ".gitignore", ".sh", ".conf", "Dockerfile", "Procfile"},
    },
    "tiktok_clone": {
        "name": "TikTok / Bigo Live Clone (Vertical Video Feed)",
        "description": "App de feed vertical de videos en vivo con likes, comments, follows, regalos virtuales y monetizacion.",
        "path": TEMPLATES_ROOT / "tiktok_clone",
        "text_exts": {".html", ".css", ".js", ".py", ".md", ".txt", ".env", ".example", ".json", ".yml", ".yaml", ".toml", ".gitignore", ".sh", ".conf", "Dockerfile", "Procfile"},
    },
}


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "my-app"


def _safe_color(c: str) -> str:
    c = (c or "").strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", c):
        return c
    if re.fullmatch(r"#[0-9A-Fa-f]{3}", c):
        return c
    return "#5B8DEF"  # default azul Lluvia


def list_templates() -> list:
    return [
        {"id": tid, "name": t["name"], "description": t["description"]}
        for tid, t in TEMPLATES.items()
        if t["path"].exists()
    ]


def materialize_template(
    template_id: str,
    target_dir: Path,
    app_name: str,
    brand_color: str = "#5B8DEF",
) -> dict:
    """Copia un template al target_dir reemplazando placeholders.

    target_dir = /app/user_apps/{user_id}/{app_slug}/
    """
    tpl = TEMPLATES.get(template_id)
    if not tpl:
        return {"ok": False, "error": f"Template '{template_id}' no existe"}
    src = tpl["path"]
    if not src.exists():
        return {"ok": False, "error": f"Template path no existe: {src}"}

    target_dir = Path(target_dir)
    if target_dir.exists():
        return {"ok": False, "error": f"Ya existe una app en {target_dir.name}. Borrala primero o elegi otro nombre."}

    app_name_safe = (app_name or "Mi App").strip()[:60]
    color = _safe_color(brand_color)
    text_exts = tpl["text_exts"]
    app_slug_value = target_dir.name

    files_written = 0
    bytes_written = 0
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
        for root, dirs, files in __import__("os").walk(src):
            root_p = Path(root)
            # Saltear __pycache__ y .git
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules", "venv", ".venv")]
            # Saltear binarios de runtime (SQLite, logs) que pueden haber quedado en el source
            skip_files = {"data.db", "data.db-journal", ".DS_Store"}
            rel = root_p.relative_to(src)
            dst_root = target_dir / rel
            dst_root.mkdir(parents=True, exist_ok=True)
            for fname in files:
                if fname in skip_files or fname.endswith(".pyc") or fname.endswith(".log"):
                    continue
                src_f = root_p / fname
                dst_f = dst_root / fname
                is_text = (src_f.suffix.lower() in text_exts
                           or fname in (".env.example", ".gitignore", "Procfile", "Dockerfile", "install.sh"))
                if is_text:
                    try:
                        text = src_f.read_text(encoding="utf-8")
                        text = text.replace("{{APP_NAME}}", app_name_safe)
                        text = text.replace("{{APP_NAME_SLUG}}", app_slug_value)
                        text = text.replace("{{BRAND_COLOR}}", color)
                        dst_f.write_text(text, encoding="utf-8")
                    except UnicodeDecodeError:
                        shutil.copy2(src_f, dst_f)
                else:
                    shutil.copy2(src_f, dst_f)
                files_written += 1
                bytes_written += dst_f.stat().st_size
    except Exception as e:
        logger.exception("Fallo materializando template")
        return {"ok": False, "error": f"Error copiando archivos: {e}"}

    return {
        "ok": True,
        "template_id": template_id,
        "template_name": tpl["name"],
        "target_path": str(target_dir),
        "app_slug": target_dir.name,
        "app_name": app_name_safe,
        "brand_color": color,
        "files_written": files_written,
        "bytes_written": bytes_written,
    }

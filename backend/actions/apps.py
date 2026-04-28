"""
========================================
GENERACION DE APPS / PAGINAS WEB
========================================

Genera plantillas HTML/CSS basicas para landing pages.
"""

import os
import re
from datetime import datetime
from pathlib import Path

GENERATED_DIR = Path(__file__).parent.parent / "generated_apps"
GENERATED_DIR.mkdir(exist_ok=True)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, sans-serif;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  color: #e8e8e8;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.hero {{
  text-align: center;
  padding: 4rem 2rem;
  max-width: 720px;
}}
h1 {{ font-size: 3rem; margin-bottom: 1rem; color: #f5d76e; }}
p {{ font-size: 1.25rem; opacity: 0.85; margin-bottom: 2rem; }}
.btn {{
  display: inline-block;
  padding: 1rem 2rem;
  background: #f5d76e;
  color: #1a1a2e;
  text-decoration: none;
  border-radius: 999px;
  font-weight: 600;
  transition: transform 0.2s ease;
}}
.btn:hover {{ transform: translateY(-2px); }}
footer {{ position: fixed; bottom: 1rem; opacity: 0.5; font-size: 0.85rem; }}
</style>
</head>
<body>
  <div class="hero">
    <h1>{title}</h1>
    <p>{description}</p>
    <a class="btn" href="#contacto">Contactar</a>
  </div>
  <footer>Generado por Bot Multiplataforma - {date}</footer>
</body>
</html>
"""


def create_app(text: str = "") -> str:
    """Genera una pagina/app simple a partir del texto del usuario."""
    # Extraer titulo del comando: "crear app TituloApp"
    title = "Mi Nueva App"
    match = re.search(r"(?:crear|nuevo|nueva)\s+(?:app|aplicacion|pagina|web)\s+(.+)", text, re.IGNORECASE)
    if match:
        title = match.group(1).strip()[:80] or title

    # Slug del archivo
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:40] or "app"
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"{slug}-{timestamp}.html"
    filepath = GENERATED_DIR / filename

    html = HTML_TEMPLATE.format(
        title=title,
        description=f"Una landing generada automaticamente por tu bot a partir de: \"{text[:120]}\"",
        date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )

    filepath.write_text(html, encoding="utf-8")

    return (
        f"App creada exitosamente: {filename}\n"
        f"Ruta: backend/generated_apps/{filename}\n"
        f"Titulo: {title}"
    )


def list_apps() -> list:
    """Lista las apps generadas."""
    if not GENERATED_DIR.exists():
        return []
    return sorted([f.name for f in GENERATED_DIR.glob("*.html")], reverse=True)

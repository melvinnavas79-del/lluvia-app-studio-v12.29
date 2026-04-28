"""
========================================
CONFIGURACION DEL BOT MULTIPLATAFORMA
========================================

Edita las variables aqui o en el archivo .env
Las variables de .env tienen prioridad sobre los valores definidos aqui.

Para obtener tus API Keys:
- WHATSAPP/INSTAGRAM (Meta): https://developers.facebook.com/
- TELEGRAM: Habla con @BotFather en Telegram
- GITHUB: https://github.com/settings/tokens
- OPENAI: https://platform.openai.com/api-keys
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Cargar variables de entorno
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


# ==========================================
# TOKEN GENERAL DE SEGURIDAD (interno)
# ==========================================
TOKEN = os.environ.get("BOT_SECRET_TOKEN", "")


# ==========================================
# GITHUB
# ==========================================
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER = os.environ.get("GITHUB_USER", "")


# ==========================================
# WHATSAPP (Meta Cloud API)
# ==========================================
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_ID = os.environ.get("PHONE_ID", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "12345")


# ==========================================
# TELEGRAM
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")


# ==========================================
# INSTAGRAM (Meta)
# ==========================================
INSTAGRAM_TOKEN = os.environ.get("INSTAGRAM_TOKEN", "")
IG_ID = os.environ.get("IG_ID", "")


# ==========================================
# OPENAI - CONEXION DIRECTA
# ==========================================
# Pega aqui tu API Key personal de OpenAI o configurala en .env.
# Obtener en: https://platform.openai.com/api-keys
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Modelo por defecto (puedes cambiarlo: gpt-4o, gpt-4o-mini, gpt-4.1, etc.)
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


# ==========================================
# MONGODB
# ==========================================
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "bot_multiplataforma")


# ==========================================
# UTILIDAD: estado de credenciales
# ==========================================
def credentials_status() -> dict:
    """Retorna el estado de las credenciales configuradas (sin exponer valores)."""
    return {
        "github": bool(GITHUB_TOKEN),
        "whatsapp": bool(WHATSAPP_TOKEN) and bool(PHONE_ID),
        "telegram": bool(TELEGRAM_TOKEN),
        "instagram": bool(INSTAGRAM_TOKEN) and bool(IG_ID),
        "openai": bool(OPENAI_API_KEY),
        "llm_ready": bool(OPENAI_API_KEY),
        "model": LLM_MODEL,
    }

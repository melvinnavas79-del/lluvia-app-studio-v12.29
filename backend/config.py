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
- OPENAI: https://platform.openai.com/api-keys (o usa EMERGENT_LLM_KEY)
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
TOKEN = os.environ.get("BOT_SECRET_TOKEN", "TU_TOKEN")


# ==========================================
# GITHUB
# ==========================================
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "TU_GITHUB")
GITHUB_USER = os.environ.get("GITHUB_USER", "")


# ==========================================
# WHATSAPP (Meta Cloud API)
# ==========================================
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "TOKEN_META")
PHONE_ID = os.environ.get("PHONE_ID", "PHONE_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "12345")


# ==========================================
# TELEGRAM
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "BOT_TOKEN")


# ==========================================
# INSTAGRAM (Meta)
# ==========================================
INSTAGRAM_TOKEN = os.environ.get("INSTAGRAM_TOKEN", "TOKEN_META")
IG_ID = os.environ.get("IG_ID", "IG_ID")


# ==========================================
# OPENAI / EMERGENT LLM
# ==========================================
# Si tienes tu propia API Key de OpenAI, ponla en OPENAI_API_KEY.
# Si dejas vacia OPENAI_API_KEY, el bot usa EMERGENT_LLM_KEY automaticamente.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# Modelo por defecto
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5.2")


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
    placeholders = {
        "TU_TOKEN", "TU_GITHUB", "TOKEN_META", "PHONE_ID",
        "BOT_TOKEN", "IG_ID", "TU_API_KEY", "12345", ""
    }
    return {
        "github": GITHUB_TOKEN not in placeholders,
        "whatsapp": WHATSAPP_TOKEN not in placeholders and PHONE_ID not in placeholders,
        "telegram": TELEGRAM_TOKEN not in placeholders,
        "instagram": INSTAGRAM_TOKEN not in placeholders and IG_ID not in placeholders,
        "openai_personal": bool(OPENAI_API_KEY),
        "emergent_llm": bool(EMERGENT_LLM_KEY),
        "llm_ready": bool(OPENAI_API_KEY) or bool(EMERGENT_LLM_KEY),
        "model": LLM_MODEL,
        "provider": LLM_PROVIDER,
    }

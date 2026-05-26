"""
llm_router.py — Selección eficiente de modelo LLM por complejidad de tarea.

Complejidad "low"  → Groq (rápido, barato) para CRUDs, boilerplate, clasificación.
Complejidad "high" → OpenAI GPT-4 para orchestration compleja, razonamiento crítico.

Variables de entorno:
  GROQ_API_KEY   — habilita ruta Groq
  GROQ_MODEL     — modelo Groq (default: llama-3.1-8b-instant)
  OPENAI_API_KEY — fallback siempre disponible
"""
import os
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("llm_router")

GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL    = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_client(complexity: str = "low") -> tuple[AsyncOpenAI, str]:
    """
    Devuelve (client, model) según la complejidad:
      "low"  → Groq si está configurado, sino OpenAI mini
      "high" → OpenAI GPT-4o (siempre)
    """
    if complexity == "low" and GROQ_API_KEY:
        logger.debug(f"[llm_router] Groq:{GROQ_MODEL}")
        return AsyncOpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_API_KEY), GROQ_MODEL

    if complexity == "low":
        logger.debug(f"[llm_router] OpenAI mini (no Groq key)")
        return AsyncOpenAI(api_key=OPENAI_KEY), OPENAI_MODEL

    model = os.getenv("OPENAI_MODEL_HIGH", "gpt-4o")
    logger.debug(f"[llm_router] OpenAI high:{model}")
    return AsyncOpenAI(api_key=OPENAI_KEY), model


def groq_available() -> bool:
    return bool(GROQ_API_KEY)

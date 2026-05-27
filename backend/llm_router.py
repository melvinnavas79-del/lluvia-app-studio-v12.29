"""
llm_router.py — Selección eficiente de modelo LLM por complejidad de tarea.

Complejidad "low"  → Groq (rápido, barato) para CRUDs, boilerplate, clasificación.
Complejidad "high" → OpenAI GPT-4 / OpenRouter Claude para razonamiento crítico.

Variables de entorno:
  GROQ_API_KEY          — habilita ruta Groq
  GROQ_MODEL            — modelo Groq (default: llama-3.1-8b-instant)
  OPENAI_API_KEY        — fallback siempre disponible
  OPENAI_MODEL          — modelo OpenAI low (default: gpt-4o-mini)
  OPENAI_MODEL_HIGH     — modelo OpenAI high (default: gpt-4o)
  OPENROUTER_API_KEY    — habilita OpenRouter (acceso a Claude/Gemini/etc.)
  OPENROUTER_MODEL      — modelo OpenRouter low (default: anthropic/claude-3-haiku)
  OPENROUTER_MODEL_HIGH — modelo OpenRouter high (default: anthropic/claude-3-5-sonnet)
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

OPENROUTER_API_KEY    = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL   = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL      = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku")
OPENROUTER_MODEL_HIGH = os.getenv("OPENROUTER_MODEL_HIGH", "anthropic/claude-3-5-sonnet")


def get_client(complexity: str = "low", provider_hint: str = "") -> tuple[AsyncOpenAI, str]:
    """
    Devuelve (client, model) según complejidad + provider_hint.

    provider_hint: "groq" | "openrouter" | "openai" | "" (auto)
      - "openrouter" → OpenRouter (Claude/Gemini/etc.) si OPENROUTER_API_KEY está configurado
      - "groq"       → Groq directo si GROQ_API_KEY configurado
      - "openai"     → OpenAI directo
      - ""           → selección automática por complejidad

    Model fallback chain:
      low:  openrouter → groq → openai-mini
      high: openrouter → openai-gpt4o
    """
    # Explicit openrouter hint
    if provider_hint == "openrouter" and OPENROUTER_API_KEY:
        model = OPENROUTER_MODEL if complexity == "low" else OPENROUTER_MODEL_HIGH
        logger.debug(f"[llm_router] OpenRouter:{model}")
        return AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY), model

    # Explicit groq hint
    if provider_hint == "groq" and GROQ_API_KEY:
        logger.debug(f"[llm_router] Groq:{GROQ_MODEL}")
        return AsyncOpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_API_KEY), GROQ_MODEL

    # Auto: low complexity
    if complexity == "low":
        if GROQ_API_KEY:
            logger.debug(f"[llm_router] auto→Groq:{GROQ_MODEL}")
            return AsyncOpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_API_KEY), GROQ_MODEL
        if OPENROUTER_API_KEY:
            logger.debug(f"[llm_router] auto→OpenRouter:{OPENROUTER_MODEL}")
            return AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY), OPENROUTER_MODEL
        logger.debug(f"[llm_router] auto→OpenAI mini")
        return AsyncOpenAI(api_key=OPENAI_KEY), OPENAI_MODEL

    # Auto: high complexity
    if OPENROUTER_API_KEY:
        logger.debug(f"[llm_router] auto→OpenRouter high:{OPENROUTER_MODEL_HIGH}")
        return AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY), OPENROUTER_MODEL_HIGH

    model = os.getenv("OPENAI_MODEL_HIGH", "gpt-4o")
    logger.debug(f"[llm_router] auto→OpenAI high:{model}")
    return AsyncOpenAI(api_key=OPENAI_KEY), model


def groq_available() -> bool:
    return bool(GROQ_API_KEY)


def openrouter_available() -> bool:
    return bool(OPENROUTER_API_KEY)

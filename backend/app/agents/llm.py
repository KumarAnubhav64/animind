import os

from functools import lru_cache

from langchain_groq import ChatGroq

from app.config import get_settings

# Optional LangSmith tracing: if enabled in config AND an API key is present,
# turn on tracing before any langchain call happens. No key -> no tracing.
_settings = get_settings()
if _settings.langsmith_tracing and os.environ.get("LANGSMITH_API_KEY"):
    os.environ.setdefault("LANGSMITH_TRACING", "true")

# Free tier is TPM-constrained: let the SDK back off on 429s instead of failing.
_LLM_KWARGS = {"max_retries": 6, "timeout": 120}


def _groq(model: str, temperature: float) -> ChatGroq:
    s = get_settings()
    return ChatGroq(
        model=model,
        api_key=s.groq_api_key,
        temperature=temperature,
        **_LLM_KWARGS,
    )


@lru_cache
def planner_llm() -> ChatGroq:
    s = get_settings()
    return _groq(s.planner_model, 0.6)


@lru_cache
def coder_llm() -> ChatGroq:
    s = get_settings()
    return _groq(s.coder_model, 0.3)


def fixer_llm(attempt: int) -> ChatGroq:
    """Temperature drops as retries accumulate: explore early, exploit late."""
    s = get_settings()
    temp = max(0.0, 0.4 - 0.1 * attempt)
    return _groq(s.fixer_model, temp)


@lru_cache
def fallback_llm(temperature: float = 0.3) -> ChatGroq:
    return _groq(get_settings().fallback_model, temperature)


def premium_llm(temperature: float = 0.2):
    """Optional surgical router model for hard continuity/QA repairs."""
    s = get_settings()
    if not s.premium_model or not s.router_api_key:
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=s.premium_model,
        api_key=s.router_api_key,
        base_url=s.router_base_url,
        temperature=temperature,
        timeout=120,
        default_headers={"User-Agent": "animind/1.0"},
    )

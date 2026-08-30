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

# Groq's free tier caps each request at 8000 tokens (input + reserved output).
# gpt-oss-120b's DEFAULT output reservation (~3072) is the natural cap for a
# full Manim scene; a smaller max_tokens truncates codegen/fixer output and
# produces unclosed-bracket syntax errors. We keep the codegen system prompt
# trimmed (few-shot blocks removed) and set explicit max_tokens at the model's
# natural budget; oversized inputs are trimmed by _fit_to_budget.
_CODER_MAX_TOKENS = 3072
_FIXER_MAX_TOKENS = 3072
_PLANNER_MAX_TOKENS = 3072


def _groq(model: str, temperature: float, api_key: str | None = None, max_tokens: int | None = None) -> ChatGroq:
    s = get_settings()
    kwargs: dict = {}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatGroq(
        model=model,
        api_key=api_key or s.groq_api_key,
        temperature=temperature,
        **_LLM_KWARGS,
        **kwargs,
    )


# Hard ceiling Groq's free tier enforces per request (input + reserved output).
_GROQ_REQUEST_CAP = 8000
# Stay under the cap even if the tokenizer estimate is slightly off.
_GROQ_REQUEST_MARGIN = 300
# Rough bytes/token ratio used only when tiktoken is unavailable.
_BYTES_PER_TOKEN = 4

def _estimate_tokens(text: str) -> int:
    """Best-effort token estimate. Prefers tiktoken when present (it is in the
    backend env), otherwise falls back to a bytes/4 heuristic with headroom."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001
        return int(len(text) / _BYTES_PER_TOKEN)


def _fit_to_budget(
    messages: list[tuple[str, str]],
    max_tokens: int,
    *,
    max_input_tokens: int | None = None,
) -> list[tuple[str, str]]:
    """Trim variable-length user content so (input + max_tokens) stays under
    Groq's per-request cap. System/system-turn content is never trimmed; only
    the final human turn is shortened. The head (title/narration/visual) and
    tail (error/feedback) are the high-value parts, so each keeps a
    proportional share of the budget and the middle is cut."""
    if not messages:
        return messages
    ceiling = max_input_tokens or (_GROQ_REQUEST_CAP - _GROQ_REQUEST_MARGIN - max_tokens)
    # System/assistant turns count toward input; only the human turn is trimmed.
    fixed_tokens = sum(_estimate_tokens(text) for role, text in messages if role != "human")
    human_idx = None
    for i, (role, _) in enumerate(messages):
        if role == "human":
            human_idx = i
    if human_idx is None:
        return messages
    human_text = messages[human_idx][1]
    if fixed_tokens + _estimate_tokens(human_text) <= ceiling:
        return messages
    budget = max(64, ceiling - fixed_tokens)
    # Head holds title/narration/visual, tail holds the directive/error/feedback;
    # each gets a proportional slice so neither is lost entirely.
    keep = budget * _BYTES_PER_TOKEN
    head_bytes = int(keep * 0.6)
    tail_bytes = max(head_bytes, keep - head_bytes)
    if len(human_text) <= keep:
        return messages
    if len(human_text) <= head_bytes + tail_bytes + 8:
        trimmed = human_text[:head_bytes] + "\n…[content trimmed to fit token budget]"
    else:
        trimmed = (
            human_text[:head_bytes]
            + "\n…[content trimmed to fit token budget]…\n"
            + human_text[len(human_text) - tail_bytes:]
        )
    out = list(messages)
    out[human_idx] = (messages[human_idx][0], trimmed)
    return out


def _backup_groq(model: str, temperature: float) -> ChatGroq | None:
    """A Groq client bound to the backup API key, or None if unset."""
    s = get_settings()
    if not s.groq_api_key_backup:
        return None
    max_tokens = _CODER_MAX_TOKENS if model == s.coder_model else _PLANNER_MAX_TOKENS
    return _groq(model, temperature, api_key=s.groq_api_key_backup, max_tokens=max_tokens)


@lru_cache
def planner_llm() -> ChatGroq:
    s = get_settings()
    return _groq(s.planner_model, 0.6, max_tokens=_PLANNER_MAX_TOKENS)


@lru_cache
def coder_llm() -> ChatGroq:
    s = get_settings()
    return _groq(s.coder_model, 0.3, max_tokens=_CODER_MAX_TOKENS)


def fixer_llm(attempt: int) -> ChatGroq:
    """Temperature drops as retries accumulate: explore early, exploit late."""
    s = get_settings()
    temp = max(0.0, 0.4 - 0.1 * attempt)
    return _groq(s.fixer_model, temp, max_tokens=_FIXER_MAX_TOKENS)


@lru_cache
def fallback_llm(temperature: float = 0.3) -> ChatGroq:
    return _groq(get_settings().fallback_model, temperature, max_tokens=_CODER_MAX_TOKENS)


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

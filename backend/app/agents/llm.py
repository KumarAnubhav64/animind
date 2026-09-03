import os
import time
import random
import asyncio

from functools import lru_cache
from typing import TypeVar

from langchain_groq import ChatGroq

from app.config import get_settings

T = TypeVar("T")

# Optional LangSmith tracing: if enabled in config AND an API key is present,
# turn tracing on before any langchain call happens. No key -> no tracing.
_settings = get_settings()
if _settings.langsmith_tracing and os.environ.get("LANGSMITH_API_KEY"):
    os.environ.setdefault("LANGSMITH_TRACING", "true")

# Free tier is TPM-constrained: let the SDK back off on 429s instead of failing.
_LLM_KWARGS = {"max_retries": 6, "timeout": 120}


async def with_backoff(coro, *, max_retries: int = 5, base: float = 2.0, cap: float = 60.0):
    """Run an async callable with exponential backoff + jitter on 429/500 errors."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await coro
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
            if attempt >= max_retries or status not in (429, 500, 502, 503):
                raise
            last_exc = exc
            delay = min(cap, base * (2 ** attempt) + random.uniform(0, 1))
            if status == 429:
                retry_after = getattr(exc, "response", None)
                if retry_after is not None:
                    headers = getattr(retry_after, "headers", {})
                    ra = headers.get("retry-after") or headers.get("Retry-After")
                    if ra:
                        try:
                            delay = max(delay, float(ra))
                        except (ValueError, TypeError):
                            pass
            await asyncio.sleep(delay)
    raise last_exc

# Groq's free tier caps each request at 8000 tokens (input + reserved output).
# gpt-oss-120b's DEFAULT output reservation (~3072) is the natural cap for a
# full Manim scene; a smaller max_tokens truncates codegen/fixer output and
# produces unclosed-bracket syntax errors. Oversized inputs are shrunk by
# _fit_to_budget (few-shot sections drop first, then hard trims).
_CODER_MAX_TOKENS = 3072
_FIXER_MAX_TOKENS = 3072
_PLANNER_MAX_TOKENS = 3072
# Spec JSON output is ~600-800 tokens; a smaller reservation frees ~1k of the
# 8k request cap for the (large) system prompt + JSON schema.
_SPEC_MAX_TOKENS = 2048


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
# Stay well under the cap — the tokenizer estimate can undercount by ~5-8%
# and some models use a non-standard tokenizer. A larger margin prevents 413s
# (an oversized request costs a full failed round-trip and can be misread as a
# rate limit because Groq labels it rate_limit_exceeded/TPM).
_GROQ_REQUEST_MARGIN = 700
# Rough bytes/token ratio used only when tiktoken is unavailable.
_BYTES_PER_TOKEN = 4

# Section headers that mark droppable few-shot/example tails of system
# prompts. When a request is over budget, everything from the FIRST matching
# header is cut — the core rules above them always stay.
_SYSTEM_DROP_HEADERS = (
    "MOTION FEW-SHOT",
    "QUALITY PATTERNS",
    "QUALITY FEW-SHOT PATTERNS",
    "FEW-SHOT EXAMPLES",
    "FEW-SHOT EXAMPLE",
    "COMPACT EXAMPLE",
    "EXAMPLE 1",
    "EXAMPLE 2",
)


def _is_oversized_request(exc: Exception) -> bool:
    """True when Groq rejected the request itself as too large (HTTP 413 /
    'Request too large for model ... on tokens per minute'). Waiting cannot
    fix this — only shrinking the payload can."""
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status == 413:
        return True
    text = str(exc).lower()
    return "request too large" in text or "too large for model" in text


def _shrink_system_text(text: str) -> str:
    """Level-1 shrink: drop the few-shot/example tail of a system prompt.
    Returns the text unchanged when no droppable section header is found."""
    cut = len(text)
    for header in _SYSTEM_DROP_HEADERS:
        idx = text.find(header)
        if idx != -1:
            cut = min(cut, idx)
    if cut >= len(text):
        return text
    return text[:cut].rstrip() + "\n"


def _estimate_tokens(text: str) -> int:
    """Best-effort token estimate. Prefers tiktoken when present, otherwise
    falls back to a bytes/4 heuristic with headroom. Groq uses a tokenizer
    close to cl100k_base but not identical, so we add a safety factor."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return int(len(enc.encode(text)) * 1.08)
    except Exception:  # noqa: BLE001
        return int(len(text) / _BYTES_PER_TOKEN)


def _fit_to_budget(
    messages: list[tuple[str, str]],
    max_tokens: int,
    *,
    max_input_tokens: int | None = None,
    extra_input_tokens: int = 0,
) -> list[tuple[str, str]]:
    """Shrink messages so (input + extra_input_tokens + max_tokens) stays under
    Groq's per-request cap. extra_input_tokens covers request payload the
    caller adds outside the messages (e.g. the JSON response schema).

    Shrink order (cheapest quality loss first):
      1. Drop few-shot/example sections from system prompts (_shrink_system_text).
      2. Hard-trim system prompts, keeping the head (core rules live there).
      3. Middle-cut the FINAL human turn — its head (title/narration/visual) and
         tail (error/feedback) are the high-value parts, so each keeps a
         proportional share of the budget and only the middle is cut.
    Returns the input unchanged when it already fits.
    """
    if not messages:
        return messages
    ceiling = max_input_tokens or (_GROQ_REQUEST_CAP - _GROQ_REQUEST_MARGIN - max_tokens - extra_input_tokens)
    ceiling = max(128, ceiling)

    def _total(msgs: list[tuple[str, str]]) -> int:
        return sum(_estimate_tokens(text) for _, text in msgs)

    out = list(messages)
    if _total(out) <= ceiling:
        return out

    # Level 1: drop few-shot/example tails from system turns.
    out = [(role, _shrink_system_text(text) if role == "system" else text) for role, text in out]
    if _total(out) <= ceiling:
        return out

    # Level 2: hard-trim system turns (head-first — the core rules lead).
    human_tokens = sum(_estimate_tokens(text) for role, text in out if role == "human")
    # Reserve at least half the ceiling for the human turn when it carries
    # the task payload; the system floor keeps core rules alive.
    human_share = min(human_tokens, max(64, ceiling // 2))
    sys_budget = max(64, ceiling - human_share)
    sys_texts = [text for role, text in out if role == "system"]
    sys_total = sum(_estimate_tokens(text) for text in sys_texts)
    if sys_total > sys_budget and sys_texts:
        shrunk = []
        for role, text in out:
            if role != "system":
                shrunk.append((role, text))
                continue
            share = max(64, int(sys_budget * _estimate_tokens(text) / sys_total))
            keep_bytes = share * _BYTES_PER_TOKEN
            if len(text) > keep_bytes:
                shrunk.append((role, text[:keep_bytes] + "\n…[system prompt truncated to fit token budget]"))
            else:
                shrunk.append((role, text))
        out = shrunk
        if _total(out) <= ceiling:
            return out

    # Level 3: middle-cut the final human turn (head + tail survive).
    human_idx = None
    for i, (role, _) in enumerate(out):
        if role == "human":
            human_idx = i
    if human_idx is None:
        return out
    fixed_tokens = sum(_estimate_tokens(text) for i, (role, text) in enumerate(out) if i != human_idx)
    human_text = out[human_idx][1]
    budget = max(64, ceiling - fixed_tokens)
    keep = budget * _BYTES_PER_TOKEN
    head_bytes = int(keep * 0.6)
    tail_bytes = max(head_bytes, keep - head_bytes)
    if len(human_text) <= keep:
        return out
    if len(human_text) <= head_bytes + tail_bytes + 8:
        trimmed = human_text[:head_bytes] + "\n…[content trimmed to fit token budget]"
    else:
        trimmed = (
            human_text[:head_bytes]
            + "\n…[content trimmed to fit token budget]…\n"
            + human_text[len(human_text) - tail_bytes:]
        )
    out[human_idx] = (out[human_idx][0], trimmed)
    return out


def _backup_groq(
    model: str,
    temperature: float,
    max_tokens: int | None = None,
) -> ChatGroq | None:
    """A Groq client bound to the backup API key, or None if unset."""
    s = get_settings()
    if not s.groq_api_key_backup:
        return None
    if max_tokens is None:
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


@lru_cache
def spec_llm() -> ChatGroq:
    """LLM for declarative SceneSpec generation: same model as codegen but a
    smaller output reservation, because spec JSON is far more compact than
    Python source and the request also carries the JSON schema."""
    s = get_settings()
    return _groq(s.coder_model, 0.4, max_tokens=_SPEC_MAX_TOKENS)


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

"""Tests for the context summarizer: must never raise, must fall back to
truncation when the LLM call fails, and must skip short text untouched."""

import asyncio

from app.agents import summarizer
from app.agents.summarizer import summarize

SHORT = "A short piece of text."

LONG = (
    "The quick brown fox jumps over the lazy dog. " * 80
)


def test_short_text_passes_through():
    result = asyncio.run(summarize(SHORT, max_chars=500))
    assert result == SHORT


def test_truncation_fallback_when_llm_fails(monkeypatch):
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(summarizer, "fallback_llm", lambda *_a, **_k: object())
    monkeypatch.setattr(summarizer, "with_backoff", _boom)
    result = asyncio.run(summarize(LONG, max_chars=1500))
    assert "truncated" in result
    assert len(result) < len(LONG)


def test_llm_result_is_used_when_shorter(monkeypatch):
    class _Resp:
        content = "Compressed summary."

    class _FakeLLM:
        async def ainvoke(self, *_args, **_kwargs):
            return _Resp()

    async def _no_backoff(coro, **_kwargs):
        return await coro

    monkeypatch.setattr(summarizer, "fallback_llm", lambda *_a, **_k: _FakeLLM())
    monkeypatch.setattr(summarizer, "with_backoff", _no_backoff)
    result = asyncio.run(summarize(LONG, max_chars=1500))
    assert result == "Compressed summary."

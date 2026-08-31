"""Lightweight text summarizer for reducing token usage in LLM calls.

Uses a fast, cheap model to compress verbose text into a shorter version
that preserves key facts. Falls back to simple truncation if the LLM call
fails — the pipeline must never block on summarization.
"""

import logging

from app.agents.llm import fallback_llm, with_backoff

logger = logging.getLogger("animind.summarizer")

SUMMARIZE_SYSTEM_PROMPT = """\
You are a text compressor for an animation studio. You receive a piece of text \
about a video project and must condense it to about one third of its original \
length while preserving every factual detail, proper noun, number, and technical \
term. Keep the visual state of each scene — object names, positions, colors, and \
recurring elements — intact, since later scenes must stay visually consistent. \
Drop filler phrases, redundant descriptions, and verbose transitions. \
Return ONLY the condensed text, no commentary."""


# Maximum input window the summarizer reads. Large enough to cover the full
# accumulated scene context (early scenes carry the visual state the coder needs
# for continuity) while bounding the summarizer's own token spend.
_SUMMARIZER_INPUT_CHARS = 8000


async def summarize(text: str, *, max_chars: int = 1500) -> str:
    """Compress `text` to roughly max_chars. Never raises — falls back to \
    truncation if the LLM call fails."""
    if len(text) <= max_chars:
        return text
    try:
        llm = fallback_llm(temperature=0.0)
        resp = await with_backoff(
            llm.ainvoke([
                ("system", SUMMARIZE_SYSTEM_PROMPT),
                (
                    "human",
                    f"Condense the following to at most {max_chars} characters:\n\n"
                    f"{text[:_SUMMARIZER_INPUT_CHARS]}",
                ),
            ])
        )
        result = resp.content.strip()
        if result and len(result) < len(text):
            logger.debug("summarizer: %d -> %d chars", len(text), len(result))
            return result[:max_chars]
    except Exception as exc:  # noqa: BLE001
        logger.warning("summarizer: LLM fallback to truncation: %s", exc)
    return text[:max_chars] + "\n…[truncated]"

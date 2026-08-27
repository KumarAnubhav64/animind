"""Lightweight LLM call telemetry: latency + token counts per call.

Larger observability (LangSmith / Langfuse) is optional and configured
separately; this module gives cost/latency visibility out of the box through
the app logger and an in-memory history for tests and dashboards.
"""

import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger("animind.llm")

_calls: deque[dict[str, Any]] = deque(maxlen=500)


def _usage(result: Any) -> tuple[int | None, int | None]:
    metadata = getattr(result, "usage_metadata", None) or {}
    if not isinstance(metadata, dict):
        return None, None
    return metadata.get("input_tokens"), metadata.get("output_tokens")


def record(
    *,
    model: str,
    result: Any,
    latency_ms: int,
    project_id: str | None = None,
    note: str = "",
) -> None:
    tokens_in, tokens_out = _usage(result)
    entry = {
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
        "project_id": project_id,
        "note": note,
        "ts": time.time(),
    }
    _calls.append(entry)
    logger.info(
        "llm %s project=%s in=%s out=%s latency=%sms%s",
        model, project_id or "-", tokens_in, tokens_out, latency_ms,
        f" ({note})" if note else "",
    )


def call_history() -> list[dict[str, Any]]:
    return list(_calls)

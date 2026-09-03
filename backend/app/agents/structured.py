"""Shared structured-output LLM call with key-backup + fallback-model retry.

Every request is fitted to Groq's 8k per-request cap BEFORE the call: the JSON
schema counts toward input tokens, so it is passed to _fit_to_budget as
extra_input_tokens. On an oversized-request (413) rejection the payload is
shrunk further and retried instead of resubmitting the same bytes.
"""

import asyncio
import json
import logging

from app.config import get_settings
from app.pipeline.telemetry import record as _record_call

logger = logging.getLogger("animind.studio")


def _llm_max_tokens(model) -> int:
    from app.agents.llm import _PLANNER_MAX_TOKENS

    return getattr(model, "max_tokens", None) or _PLANNER_MAX_TOKENS


# Groq / provider wording for "the model's JSON did not pass schema validation".
_JSON_VALIDATION_HINTS = (
    "json_validate_failed",
    "failed to validate json",
    "failed_generation",
    "invalid json",
    "is not valid json",
    "does not conform",
    "could not be validated",
)


def _is_json_validation_error(message: str) -> bool:
    return any(hint in message for hint in _JSON_VALIDATION_HINTS)


# Appended to the last human turn after a JSON validation failure so later
# retries nudge the model toward a clean, schema-conforming response instead of
# resubmitting the identical prompt that just failed.
_JSON_REMEDIATION = (
    "\n\nREMINDER: respond with ONLY a single, well-formed JSON object that matches the "
    "schema exactly. No markdown, no code fences, no prose before or after the JSON, no "
    "trailing commas, no comments, and escape every quote/backslash inside strings."
)


def _append_remediation(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i][0] == "human":
            out = list(messages)
            role, text = out[i]
            out[i] = (role, text + _JSON_REMEDIATION)
            return out
    return messages


async def structured_call(
    model, messages, schema, attempts: int = 4, project_id: str | None = None
):
    """Invoke with_structured_output with retries (json_schema method; Groq's
    tool-call method fails on nested schemas, and long generations occasionally
    emit invalid JSON).

    A JSON-schema validation failure is not retried with an identical payload
    forever: on the first occurrence the prompt is nudged toward a clean JSON
    reply AND the call escalates to the backup Groq key, then the fallback
    model — the same ladder used for daily token caps. The primary model keeps
    its remaining attempts afterwards in case the failure was transient.
    """
    from app.agents.llm import (
        _GROQ_REQUEST_CAP,
        _GROQ_REQUEST_MARGIN,
        _backup_groq,
        _estimate_tokens,
        _fit_to_budget,
        fallback_llm,
    )

    max_tokens = _llm_max_tokens(model)
    schema_tokens = _estimate_tokens(json.dumps(getattr(schema, "model_json_schema", dict)()))
    fitted = _fit_to_budget(messages, max_tokens, extra_input_tokens=schema_tokens)
    full_ceiling = _GROQ_REQUEST_CAP - _GROQ_REQUEST_MARGIN - max_tokens - schema_tokens

    structured = model.with_structured_output(schema, method="json_schema")
    model_name = getattr(model, "model_name", None) or getattr(model, "model", None) or str(model)
    temperature = getattr(model, "temperature", 0.6)
    backup_llm = _backup_groq(model_name, temperature, max_tokens=max_tokens)
    used_backup = False
    tried_fallback = False
    remediated = False
    last_err: Exception | None = None

    async def _escalate(reason: str):
        """Try the backup Groq key, then the fallback model, against the same
        schema. Returns the parsed result or None when neither worked."""
        nonlocal used_backup, tried_fallback, last_err
        if not used_backup and backup_llm is not None:
            used_backup = True
            logger.warning(
                "structured call (%s): retrying on backup Groq key (%s)", reason, model_name
            )
            try:
                backup_structured = backup_llm.with_structured_output(
                    schema, method="json_schema"
                )
                result = await backup_structured.ainvoke(fitted)
                _record_call(
                    model=model_name, result=result,
                    latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                    project_id=project_id, note=f"{reason}-key-backup",
                )
                return result
            except Exception as backup_error:  # noqa: BLE001
                last_err = backup_error
                logger.warning(
                    "structured call (%s): backup key also failed: %s", reason, backup_error
                )
        if not tried_fallback:
            tried_fallback = True
            logger.warning(
                "structured call (%s): switching to fallback model %s",
                reason, get_settings().fallback_model,
            )
            try:
                fallback_structured = fallback_llm().with_structured_output(
                    schema, method="json_schema"
                )
                result = await fallback_structured.ainvoke(fitted)
                _record_call(
                    model=get_settings().fallback_model, result=result,
                    latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                    project_id=project_id, note=f"{reason}-fallback",
                )
                return result
            except Exception as fallback_error:  # noqa: BLE001
                last_err = fallback_error
                logger.warning(
                    "structured call (%s): fallback model also failed: %s",
                    reason, fallback_error,
                )
        return None

    for i in range(attempts):
        start = asyncio.get_event_loop().time()
        try:
            result = await structured.ainvoke(fitted)
            _record_call(
                model=model_name, result=result,
                latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                project_id=project_id,
            )
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            message = str(e).lower()
            # An oversized request never succeeds on retry — shrink and resend.
            from app.agents.llm import _is_oversized_request

            if _is_oversized_request(e) and i < attempts - 1:
                tighter = max(256, full_ceiling - 800 * (i + 1))
                refit = _fit_to_budget(fitted, max_tokens, max_input_tokens=tighter)
                if refit != fitted:
                    logger.warning(
                        "structured call oversized (attempt %s/%s); refitting payload",
                        i + 1, attempts,
                    )
                    fitted = refit
                    continue

            reason = None
            if "tokens per day" in message or "tpd" in message:
                reason = "tpd"
            elif _is_json_validation_error(message):
                reason = "json-validation"
                # Help subsequent identical retries pass validation instead of
                # failing the same way every time.
                if not remediated:
                    remediated = True
                    fitted = _append_remediation(fitted)
            if reason is not None:
                result = await _escalate(reason)
                if result is not None:
                    return result
            logger.warning(
                "structured call failed (%s, attempt %s/%s): %s",
                reason or "transient", i + 1, attempts, e,
            )
    raise last_err  # type: ignore[misc]

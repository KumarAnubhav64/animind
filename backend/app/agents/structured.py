"""Shared structured-output LLM call with key-backup + fallback-model retry."""

import asyncio
import logging

from app.config import get_settings
from app.pipeline.telemetry import record as _record_call

logger = logging.getLogger("animind.studio")


async def structured_call(
    model, messages, schema, attempts: int = 3, project_id: str | None = None
):
    """Invoke with_structured_output with retries (json_schema method; Groq's
    tool-call method fails on nested schemas, and long generations occasionally
    emit invalid JSON)."""
    from app.agents.llm import _backup_groq, fallback_llm

    structured = model.with_structured_output(schema, method="json_schema")
    model_name = getattr(model, "model_name", None) or getattr(model, "model", None) or str(model)
    temperature = getattr(model, "temperature", 0.6)
    backup_llm = _backup_groq(model_name, temperature)
    used_backup = False
    last_err: Exception | None = None
    for i in range(attempts):
        start = asyncio.get_event_loop().time()
        try:
            result = await structured.ainvoke(messages)
            _record_call(
                model=model_name, result=result,
                latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                project_id=project_id,
            )
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            message = str(e).lower()
            if "tokens per day" in message or "tpd" in message:
                if not used_backup and backup_llm is not None:
                    logger.warning(
                        "primary key hit daily token cap; retrying on backup Groq key"
                    )
                    used_backup = True
                    try:
                        fallback = backup_llm.with_structured_output(
                            schema, method="json_schema"
                        )
                        result = await fallback.ainvoke(messages)
                        _record_call(
                            model=model_name, result=result,
                            latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                            project_id=project_id, note="key-backup",
                        )
                        return result
                    except Exception as backup_error:  # noqa: BLE001
                        last_err = backup_error
                fallback = fallback_llm().with_structured_output(
                    schema, method="json_schema"
                )
                logger.warning(
                    "primary model hit daily token cap; switching to fallback model %s",
                    get_settings().fallback_model,
                )
                try:
                    result = await fallback.ainvoke(messages)
                    _record_call(
                        model=get_settings().fallback_model, result=result,
                        latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                        project_id=project_id, note="tpd-fallback",
                    )
                    return result
                except Exception as fallback_error:  # noqa: BLE001
                    last_err = fallback_error
                    logger.warning("fallback structured call failed: %s", fallback_error)
                    raise fallback_error
            logger.warning("structured call failed (attempt %s/%s): %s", i + 1, attempts, e)
    raise last_err  # type: ignore[misc]

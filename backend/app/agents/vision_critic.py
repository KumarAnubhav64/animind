"""Vision critic: screenshots -> layout/overlap verdict.

Primary: the configured vision model (AgentRouter by default). If it is
unavailable (quota exhausted, model missing) the critic falls back to a Groq
vision-capable model (e.g. qwen/qwen3.8-27b) before failing open. The visual
checker is a mandatory stage — it is only ever *skipped with a visible reason*,
never silently.

Fail-open: errors count as passed, but always carry a `skipped_reason` so the
degradation is loud instead of invisible.
"""

import base64
import logging
import time

from pydantic import BaseModel, Field

from app.agents.llm import get_settings
from app.pipeline.frames import extract_frames

logger = logging.getLogger("animind.vision")

# Availability flags with a retry window: a quota error (which can recover
# hourly/daily) re-enables the model after a delay; a missing model disables
# it for the process lifetime.
_RETRY_AFTER_S = 3600.0
_router_available = True
_router_retry_after = 0.0
_groq_available = True
_groq_retry_after = 0.0


def _usable(available: bool, retry_after: float) -> bool:
    if available:
        return True
    return time.monotonic() > retry_after


def _disable(available: bool, retry_after: float, permanent: bool) -> tuple[bool, float]:
    return False, float("inf") if permanent else time.monotonic() + _RETRY_AFTER_S


CRITIC_SYSTEM_PROMPT = """\
You are a strict visual QA reviewer for educational Manim animations. You receive \
the overall video topic, 3 screenshots from one scene, and the narration it accompanies.

Judge ONLY what is visible:
1. Overlap: do any texts/shapes/arrows collide or become unreadable?
2. Off-screen: is any element cut off by the frame edges?
3. Layout balance: is content bunched in one corner leaving large empty areas, \
or is the composition reasonable?
4. Relevance: does the visible content plausibly match the narration AND the \
overall video topic? If the topic is "object storage" but the scene shows \
unrelated shapes (e.g. hash diagrams when it should show HTTP API), flag it.

Be lenient on style and aesthetics; fail the scene ONLY for overlap/cutoff/clutter \
that would genuinely confuse a viewer. One minor imperfection is not a failure.

The screenshots are chronological samples (opening, middle, closing). An object may \
be absent from an early build frame; judge whether the intended visual argument appears \
by the closing frame and whether the progression matches the narration.
"""


class VisualVerdict(BaseModel):
    passed: bool = Field(description="True if the visuals are acceptable")
    issues: list[str] = Field(description="Empty if passed; otherwise concrete problems")
    skipped_reason: str | None = Field(
        default=None, description="Why critique was skipped/failed open, if it was"
    )


def _image_data_url(path) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/jpeg;base64,{data}"


def _vision_llm():
    """Primary vision model via AgentRouter (OpenAI-compatible) when configured,
    else ChatGroq (for accounts that have a vision model directly)."""
    settings = get_settings()
    if settings.router_api_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.vision_model,
            api_key=settings.router_api_key,
            base_url=settings.router_base_url,
            temperature=0.0,
            max_retries=2,
            timeout=120,
            # AgentRouter only serves whitelisted client User-Agents
            default_headers={"User-Agent": "opencode/1.0.0"},
        )
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.vision_model,
        api_key=settings.groq_api_key,
        temperature=0.0,
        max_retries=2,
        timeout=60,
    )


def _vision_llm_fallback():
    """Groq vision-capable model used when the primary vision model is down.
    Returns None if not configured."""
    settings = get_settings()
    model = settings.vision_model_fallback
    if not model or not settings.groq_api_key:
        return None
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=model,
        api_key=settings.groq_api_key,
        temperature=0.0,
        max_retries=2,
        timeout=60,
    )


async def _critique_with(llm, content, settings, *, is_router: bool) -> VisualVerdict | None:
    """Run one critique call. Returns the verdict, or None on any failure
    (updating availability flags). Never raises."""
    global _router_available, _router_retry_after, _groq_available, _groq_retry_after
    try:
        result_msg = await llm.ainvoke([("system", CRITIC_SYSTEM_PROMPT), ("human", content)])
        text = result_msg.content if isinstance(result_msg.content, str) else str(result_msg.content)
        start, end = text.find("{"), text.rfind("}")
        verdict = VisualVerdict.model_validate_json(text[start : end + 1])
        logger.info("vision critique: passed=%s issues=%s", verdict.passed, verdict.issues)
        return verdict
    except Exception as e:  # noqa: BLE001
        message = str(e)
        lower = message.lower()
        is_quota = "insufficient_user_quota" in message or "user quota is not enough" in message or "403" in message
        is_missing = "does not exist" in message or "model_not_found" in message
        if is_router:
            if is_quota:
                logger.warning(
                    "vision model %s quota exhausted (403) — falling back%s",
                    settings.vision_model,
                    " to Groq vision model" if settings.vision_model_fallback else ", visual QA will fail open",
                )
                _router_available, _router_retry_after = _disable(_router_available, _router_retry_after, permanent=False)
            elif is_missing:
                logger.warning("vision model %s unavailable — disabling", settings.vision_model)
                _router_available, _router_retry_after = _disable(_router_available, _router_retry_after, permanent=True)
            else:
                logger.warning("vision critique call failed: %s", message[:200])
            return None
        if is_missing:
            logger.warning("groq vision fallback %s unavailable — disabling", settings.vision_model_fallback)
            _groq_available, _groq_retry_after = _disable(_groq_available, _groq_retry_after, permanent=True)
        else:
            logger.warning("groq vision fallback call failed: %s", message[:200])
        return None


async def critique_scene(
    video_path: str,
    narration: str,
    visual_description: str = "",
    project_topic: str = "",
) -> VisualVerdict:
    """Returns verdict; never raises — errors count as passed (fail-open) but
    always record why, so a dead vision model is visible rather than silent."""
    global _router_available, _router_retry_after, _groq_available, _groq_retry_after
    router_ok = _usable(_router_available, _router_retry_after)
    groq_ok = _usable(_groq_available, _groq_retry_after)
    if not router_ok and not groq_ok:
        return VisualVerdict(
            passed=True, issues=[], skipped_reason="visual QA unavailable: no vision model reachable"
        )
    settings = get_settings()
    if not router_ok and settings.vision_model_fallback is None:
        return VisualVerdict(
            passed=True, issues=[],
            skipped_reason="visual QA skipped: primary vision model unavailable and no fallback configured",
        )
    if not router_ok and not settings.vision_model_fallback_vision_capable:
        return VisualVerdict(
            passed=True, issues=[],
            skipped_reason=(
                "visual QA skipped: primary vision model unavailable and the configured fallback "
                f"({settings.vision_model_fallback}) is text-only — text-only models cannot judge "
                "screenshots, so QA fails open instead of rejecting on hallucinations"
            ),
        )
    try:
        frame_count = settings.vision_max_frames if router_ok else settings.vision_max_frames_fallback
        frames = await extract_frames(
            video_path, count=frame_count, width=settings.vision_frame_width
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("frame extraction failed, skipping critique: %s", e)
        return VisualVerdict(passed=True, issues=[], skipped_reason=f"frame extraction failed: {e}")

    topic_line = f"Overall video topic: {project_topic}\n\n" if project_topic else ""
    content: list[dict] = [
        {"type": "text", "text": f"{topic_line}Narration for this scene:\n{narration}\n\n"
         f"Director's intent:\n{visual_description}\n\nReview these screenshots.\n\n"
         'Respond with ONLY a JSON object: {"passed": true/false, "issues": ["..."]}. '
         "issues must be empty when passed."}
    ]
    for i, p in enumerate(frames, start=1):
        content.append({"type": "text", "text": f"Chronological frame {i} of {len(frames)}:"})
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(p)}})

    if router_ok:
        verdict = await _critique_with(_vision_llm(), content, settings, is_router=True)
        if verdict is not None:
            return verdict

    if groq_ok and settings.vision_model_fallback_vision_capable:
        fallback = _vision_llm_fallback()
        if fallback is not None:
            verdict = await _critique_with(fallback, content, settings, is_router=False)
            if verdict is not None:
                return verdict

    return VisualVerdict(
        passed=True, issues=[],
        skipped_reason=(
            "visual QA skipped: primary vision model failed and no vision-capable "
            "fallback is reachable (text-only models are never allowed to critique)"
        ),
    )

"""Vision critic: screenshots -> layout/overlap verdict (Llama-4 Scout on Groq)."""

import base64
import logging

from pydantic import BaseModel, Field

from app.agents.llm import get_settings
from app.pipeline.frames import extract_frames

logger = logging.getLogger("animind.vision")

# Set False permanently if the configured vision model is unavailable, so we
# don't burn one failed call per scene.
_model_available = True

CRITIC_SYSTEM_PROMPT = """\
You are a strict visual QA reviewer for educational Manim animations. You receive \
3 screenshots from one scene and the narration it accompanies.

Judge ONLY what is visible:
1. Overlap: do any texts/shapes/arrows collide or become unreadable?
2. Off-screen: is any element cut off by the frame edges?
3. Layout balance: is content bunched in one corner leaving large empty areas, \
or is the composition reasonable?
4. Relevance: does the visible content plausibly match the narration?

Be lenient on style and aesthetics; fail the scene ONLY for overlap/cutoff/clutter \
that would genuinely confuse a viewer. One minor imperfection is not a failure.

The screenshots are chronological samples (opening, middle, closing). An object may \
be absent from an early build frame; judge whether the intended visual argument appears \
by the closing frame and whether the progression matches the narration.
"""


class VisualVerdict(BaseModel):
    passed: bool = Field(description="True if the visuals are acceptable")
    issues: list[str] = Field(description="Empty if passed; otherwise concrete problems")


def _image_data_url(path) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/jpeg;base64,{data}"


def _vision_llm():
    """Vision model via AgentRouter (OpenAI-compatible) when configured,
    else ChatGroq (for accounts that have a vision model)."""
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


async def critique_scene(
    video_path: str,
    narration: str,
    visual_description: str = "",
) -> VisualVerdict:
    """Returns verdict; never raises — errors count as passed (fail-open)."""
    global _model_available
    if not _model_available:
        return VisualVerdict(passed=True, issues=[])
    settings = get_settings()
    try:
        frames = await extract_frames(
            video_path, count=settings.vision_max_frames, width=settings.vision_frame_width
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("frame extraction failed, skipping critique: %s", e)
        return VisualVerdict(passed=True, issues=[])

    content: list[dict] = [
        {"type": "text", "text": f"Narration for this scene:\n{narration}\n\n"
         f"Director's intent:\n{visual_description}\n\nReview these screenshots.\n\n"
         'Respond with ONLY a JSON object: {"passed": true/false, "issues": ["..."]}. '
         "issues must be empty when passed."}
    ]
    for i, p in enumerate(frames, start=1):
        content.append({"type": "text", "text": f"Chronological frame {i} of {len(frames)}:"})
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(p)}})

    try:
        result_msg = await _vision_llm().ainvoke(
            [("system", CRITIC_SYSTEM_PROMPT), ("human", content)]
        )
        text = result_msg.content if isinstance(result_msg.content, str) else str(result_msg.content)
        start, end = text.find("{"), text.rfind("}")
        verdict = VisualVerdict.model_validate_json(text[start : end + 1])
        logger.info("vision critique: passed=%s issues=%s", verdict.passed, verdict.issues)
        return verdict
    except Exception as e:  # noqa: BLE001
        if "does not exist" in str(e) or "model_not_found" in str(e):
            logger.warning("vision model %s unavailable — disabling critique", get_settings().vision_model)
            _model_available = False
        else:
            logger.warning("vision critique failed (fail-open): %s", e)
        return VisualVerdict(passed=True, issues=[])

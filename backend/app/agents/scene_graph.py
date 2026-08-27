import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, TypedDict

from langgraph.graph import END, StateGraph
from moviepy import AudioFileClip

from app.agents.llm import coder_llm, fallback_llm, fixer_llm
from app.agents.tts import synthesize_speech
from app.config import get_settings
from app.pipeline.renderer import normalize_manim_code, preflight_visual_code, render_manim
from app.pipeline.telemetry import record as _record_call
from app.pipeline.video import merge_audio_video
from app.prompts import (
    CODER_SYSTEM_PROMPT,
    coder_user_prompt,
    fixer_user_prompt,
    FIXER_SYSTEM_PROMPT,
)
from app.schemas import extract_python_code

logger = logging.getLogger("animind.scene")


def _model_name(llm) -> str:
    return getattr(llm, "model_name", None) or getattr(llm, "model", None) or str(llm)


async def llm_with_retry(
    llm,
    messages,
    attempts: int = 4,
    wait_s: float = 30.0,
    project_id: str | None = None,
):
    """Rate-limit-aware LLM call: the SDK backs off on 429s, but on free tiers
    a parallel scene burst can still exhaust retries — wait and try again.
    If the primary Groq key keeps failing, retry on the backup key."""
    from app.agents.llm import _backup_groq

    last_err: Exception | None = None
    model = _model_name(llm)
    temperature = getattr(llm, "temperature", 0.3)
    backup_llm: Any = None
    used_backup = False
    for i in range(attempts):
        start = asyncio.get_event_loop().time()
        try:
            result = await llm.ainvoke(messages)
            _record_call(
                model=model, result=result,
                latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                project_id=project_id,
            )
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            message = str(e).lower()
            # A daily cap will not recover during this request. Retrying it
            # only delays the fallback and consumes another provider call.
            if "tokens per day" in message or "tpd" in message:
                settings = get_settings()
                if backup_llm is None:
                    backup_llm = _backup_groq(model, temperature)
                if not used_backup and backup_llm is not None:
                    logger.warning("primary key hit daily token cap; retrying on backup Groq key")
                    used_backup = True
                    try:
                        result = await backup_llm.ainvoke(messages)
                        _record_call(
                            model=model, result=result,
                            latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                            project_id=project_id, note="key-backup",
                        )
                        return result
                    except Exception as backup_error:  # noqa: BLE001
                        last_err = backup_error
                if model != settings.fallback_model:
                    logger.warning(
                        "primary model hit daily token cap; switching to fallback model %s",
                        settings.fallback_model,
                    )
                    if messages:
                        fallback = fallback_llm()
                        result = await fallback.ainvoke(messages)
                        _record_call(
                            model=_model_name(fallback), result=result,
                            latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                            project_id=project_id, note="tpd-fallback",
                        )
                        return result
                raise
            if ("rate_limit" in message or "rate limit" in message) and i < attempts - 1:
                logger.warning("rate limited, waiting %ss (attempt %s/%s)", wait_s, i + 1, attempts)
                await asyncio.sleep(wait_s)
            else:
                if backup_llm is None:
                    backup_llm = _backup_groq(model, temperature)
                if not used_backup and backup_llm is not None:
                    logger.warning("primary key rate-limited; retrying on backup Groq key")
                    used_backup = True
                    try:
                        result = await backup_llm.ainvoke(messages)
                        _record_call(
                            model=model, result=result,
                            latency_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                            project_id=project_id, note="key-backup",
                        )
                        return result
                    except Exception as backup_error:  # noqa: BLE001
                        last_err = backup_error
                raise
    raise last_err  # type: ignore[misc]


def scene_dir(media_dir: str, project_id: str, scene_id: str) -> Path:
    return Path(media_dir).resolve() / project_id / "scenes" / scene_id


class SceneState(TypedDict):
    # inputs (immutable during the run)
    project_id: str
    scene_id: str
    scene_idx: int
    title: str
    narration: str
    visual_description: str
    project_topic: str  # overall video topic for visual QA context
    # evolving
    audio_path: str | None
    audio_duration: float | None
    muted: bool
    code: str | None
    error: str | None
    attempts: int
    status: str
    video_path: str | None
    duration_s: float | None
    fell_back: bool
    critiqued: bool
    qa_attempts: int
    qa_exhausted: bool
    context: str
    spec_json: str | None
    treatment_md: str | None


class SceneResult(TypedDict):
    status: Literal["ready", "failed"]
    manim_code: str | None
    video_path: str | None
    audio_path: str | None
    duration_s: float | None
    attempts: int
    error: str | None
    spec_json: str | None
    qa_warning: str | None


# ---------------------------------------------------------------- nodes


WORDS_PER_SECOND = 2.6  # ~156 wpm narration pace


def estimate_duration(narration: str) -> float:
    return max(8.0, len(narration.split()) / WORDS_PER_SECOND)


async def synth_tts(state: SceneState) -> dict[str, Any]:
    settings = get_settings()
    out = scene_dir(settings.media_dir, state["project_id"], state["scene_id"]) / "audio.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        wav = await asyncio.to_thread(synthesize_speech, state["narration"])
        out.write_bytes(wav)

        def read_duration() -> float:
            clip = AudioFileClip(str(out))
            try:
                return float(clip.duration)
            finally:
                clip.close()

        duration = await asyncio.to_thread(read_duration)
        return {"audio_path": str(out), "audio_duration": duration, "muted": False, "status": "coding"}
    except Exception as e:  # noqa: BLE001
        error_msg = str(e).lower()
        is_rate_limit = "429" in error_msg or "rate_limit" in error_msg or "tpd" in error_msg
        if is_rate_limit:
            # Rate limit: fall back to muted scene with subtitles
            logger.warning("TTS rate-limited for scene %s — producing muted scene with captions", state["scene_id"])
            return {
                "audio_path": None,
                "audio_duration": estimate_duration(state["narration"]),
                "muted": True,
                "status": "coding",
            }
        # Other errors: raise so retry logic can attempt again
        logger.error("TTS failed for scene %s (%s)", state["scene_id"], e)
        raise RuntimeError(f"TTS synthesis failed: {e}") from e


async def generate_spec(state: SceneState) -> dict[str, Any]:
    """Tier 1: declarative SceneSpec -> deterministic Manim code (compiled)."""
    from app.pipeline.spec_compiler import compile_spec
    from app.pipeline.treatment import generate_treatment
    from app.prompts.spec_coder import (
        SPEC_CODER_SYSTEM_PROMPT,
        SpecCode,
        spec_coder_user_prompt,
    )
    from app.schemas.spec import SceneSpec
    from app.agents.studio_graph import structured_call
    from app.pipeline.events import publish as _publish

    scene_id = state["scene_id"]
    project_id = state["project_id"]

    async def _progress(message: str):
        await _publish(
            project_id,
            {
                "type": "workflow",
                "scene_id": scene_id,
                "scene_idx": state.get("scene_idx", 0),
                "agent": "SpecCoder",
                "node": "specgen",
                "message": message,
            },
        )
    msg = spec_coder_user_prompt(
        state["title"],
        state["narration"],
        state["visual_description"] or "",
        state.get("audio_duration"),
        state.get("context") or "",
        muted=state.get("muted", False),
    )
    parsed: SceneSpec | None = None
    try:
        await _progress(
            "Reading narration and continuity context to plan the scene's beats, objects, and visual layout."
        )
        parsed = await structured_call(
            coder_llm(),
            [
                ("system", SPEC_CODER_SYSTEM_PROMPT),
                ("human", msg + '\n\nReturn a single JSON object with keys "title" and "beats".'),
            ],
            SceneSpec,
            project_id=project_id,
        )
        await _progress(
            f"Structured {len(parsed.beats)} beats into a declarative spec ({len(parsed.beats)} action groups); compiling to Manim code."
        )
        # Stream the spec JSON to the frontend
        await _publish(
            project_id,
            {
                "type": "workflow",
                "scene_id": scene_id,
                "scene_idx": state.get("scene_idx", 0),
                "agent": "SpecCoder",
                "node": "specgen",
                "message": f"Generated spec with {len(parsed.beats)} beats",
                "details": {"spec_json": parsed.model_dump_json(indent=2)},
            },
        )
        code = compile_spec(parsed, state.get("audio_duration"))
        await _progress("Compiled the declarative spec into deterministic Manim code.")
        # Stream the compiled code to the frontend
        await _publish(
            project_id,
            {
                "type": "workflow",
                "scene_id": scene_id,
                "scene_idx": state.get("scene_idx", 0),
                "agent": "SpecCoder",
                "node": "specgen",
                "message": f"Compiled spec into {len(code.splitlines())} lines of Manim code",
                "details": {"compiled_code": code},
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("scene %s: spec generation failed (%s) — using raw codegen", scene_id, e)
        await _progress("Spec path failed; falling back to raw LLM code generation.")
        result = await generate_code(state)
        treatment = generate_treatment(
            state["title"], state["narration"], state.get("visual_description") or "",
            None, state.get("audio_duration"),
        )
        return {**result, "fell_back": True, "spec_json": None, "treatment_md": treatment}
    spec_json = parsed.model_dump_json()
    treatment = generate_treatment(
        state["title"], state["narration"], state.get("visual_description") or "",
        spec_json, state.get("audio_duration"),
    )
    return {
        "code": code,
        "status": "rendering",
        "attempts": 1,
        "spec_json": spec_json,
        "treatment_md": treatment,
    }


async def mathcheck(state: SceneState) -> dict[str, Any]:
    """Subject-expert gate: deterministic checks + optional LLM review on the
    SceneSpec BEFORE compilation. Fail-open — never blocks the scene."""
    from app.agents.math_expert import (
        apply_fixes,
        has_math_content,
        math_review,
        validate_math,
    )
    from app.schemas.spec import SceneSpec

    spec_json = state.get("spec_json")
    if not spec_json:
        return {"math_checked": True, "math_fixed": False}

    try:
        spec = SceneSpec.model_validate_json(spec_json)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "scene %s: spec unparseable (%s) — skipping math gate",
            state.get("scene_id"), e,
        )
        return {"math_checked": True, "math_fixed": False}

    settings = get_settings()
    narration = state.get("narration") or ""
    issues = validate_math(spec, narration)
    reviewed = False
    if settings.math_expert_enabled:
        for _ in range(max(1, settings.math_expert_max_attempts)):
            fixes = await math_review(spec, narration, issues)
            if not fixes:
                break
            if not apply_fixes(spec, fixes):
                break
            reviewed = True
            issues = validate_math(spec, narration)
            if not issues:
                break

    if not reviewed:
        if issues:
            logger.warning(
                "scene %s math findings (unfixed): %s",
                state.get("scene_id"), "; ".join(issues[:4]),
            )
        return {"math_checked": True, "math_fixed": False}

    try:
        from app.pipeline.spec_compiler import compile_spec

        code = compile_spec(spec, state.get("audio_duration"))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "scene %s: recompile after math fix failed (%s) — keeping original code",
            state.get("scene_id"), e,
        )
        return {"math_checked": True, "math_fixed": True}
    return {
        "spec_json": spec.model_dump_json(),
        "code": code,
        "math_checked": True,
        "math_fixed": True,
        "math_issues": issues[:3],
    }


async def generate_code(state: SceneState, feedback: str = "") -> dict[str, Any]:
    msg = coder_user_prompt(
        state["title"],
        state["narration"],
        state["visual_description"] or "",
        state.get("audio_duration"),
        state.get("context") or "",
        muted=state.get("muted", False),
    )
    response = await llm_with_retry(
        coder_llm(),
        [
            ("system", CODER_SYSTEM_PROMPT),
            ("human", f"{msg}\n\nAddress this quality feedback:\n{feedback}" if feedback else msg),
        ],
        project_id=state.get("project_id"),
    )
    return {
        "code": normalize_manim_code(extract_python_code(response.content)),
        "status": "rendering",
        "attempts": state["attempts"] + 1,
        "spec_json": None,
    }


async def fix_code(state: SceneState) -> dict[str, Any]:
    response = await llm_with_retry(
        fixer_llm(state["attempts"]),
        [
            ("system", FIXER_SYSTEM_PROMPT),
            (
                "human",
                fixer_user_prompt(
                    state["code"] or "",
                    state["error"] or "",
                    state["attempts"],
                    state.get("context") or "",
                    muted=state.get("muted", False),
                ),
            ),
        ],
        project_id=state.get("project_id"),
    )
    candidate = normalize_manim_code(extract_python_code(response.content))
    candidate_error = preflight_visual_code(candidate)
    if not candidate.strip() or candidate_error:
        logger.warning(
            "fixer returned an invalid candidate for scene %s; requesting fresh codegen",
            state.get("scene_id", "unknown"),
        )
        fresh = await generate_code(
            state,
            feedback=state["error"] or candidate_error or "Fixer returned no usable code",
        )
        candidate = fresh["code"]
    return {
        "code": candidate,
        "attempts": state["attempts"] + 1,
        "spec_json": None,
        "status": "rendering",
    }


async def render_node(state: SceneState) -> dict[str, Any]:
    settings = get_settings()
    work = scene_dir(settings.media_dir, state["project_id"], state["scene_id"])
    code = normalize_manim_code(state["code"] or "")
    ok, err, video_path = await render_manim(code, work, work / "render")
    if not ok:
        logger.info("scene %s render failed: %s", state["scene_id"], err.splitlines()[-1:] or err)
        return {"code": code, "error": err, "video_path": None, "status": "rendering"}
    return {"code": code, "error": None, "video_path": video_path, "status": "merging"}


async def critique_node(state: SceneState) -> dict[str, Any]:
    """Screenshot-based visual QA of the exact merged candidate."""
    from app.agents.vision_critic import critique_scene

    settings = get_settings()
    if not settings.vision_critique:
        return {"critiqued": True, "error": None}
    qa_attempts = state.get("qa_attempts", 0) + 1
    verdict = await critique_scene(
        state["video_path"], state["narration"], state.get("visual_description") or "",
        project_topic=state.get("project_topic", ""),
    )
    updates: dict[str, Any] = {
        "critiqued": True,
        "qa_attempts": qa_attempts,
        "qa_exhausted": False,
        "error": None,
    }
    if not verdict.passed:
        issues = "; ".join(verdict.issues[:3])
        logger.warning("scene %s: vision critique rejected — %s", state["scene_id"], issues)
        updates["error"] = f"visual QA rejected the animation: {issues}"
        updates["qa_issues"] = verdict.issues
        if qa_attempts >= settings.vision_max_attempts or state["attempts"] >= settings.max_scene_retries:
            updates["qa_exhausted"] = True
            logger.warning("scene %s: visual QA exhausted after %s attempt(s)", state["scene_id"], qa_attempts)
    elif verdict.skipped_reason:
        logger.warning("scene %s: visual QA skipped — %s", state["scene_id"], verdict.skipped_reason)
        updates["qa_warning"] = verdict.skipped_reason
    return updates


def after_critique(state: SceneState):
    if state.get("qa_exhausted"):
        return "fail"
    return "fix" if state["error"] else "accept"


async def merge_node(state: SceneState) -> dict[str, Any]:
    settings = get_settings()
    work = scene_dir(settings.media_dir, state["project_id"], state["scene_id"])
    out = work / "scene_final.mp4"
    if not state.get("video_path"):
        return {
            "status": "failed",
            "video_path": None,
            "duration_s": None,
            "error": "Cannot merge a scene without a rendered video",
        }
    try:
        if state["audio_path"]:
            duration = await merge_audio_video(state["video_path"], state["audio_path"], out)
        else:
            from app.pipeline.video import merge_with_captions

            duration = await merge_with_captions(
                state["video_path"], state["narration"], out
            )
    except Exception as e:  # noqa: BLE001
        # Last resort: ship the raw animation rather than losing the scene
        from moviepy import VideoFileClip

        logger.warning("scene %s: merge failed (%s) — shipping raw animation", state["scene_id"], e)
        try:
            raw = await asyncio.to_thread(lambda: VideoFileClip(state["video_path"]))
            try:
                duration = float(raw.duration)
            finally:
                raw.close()
            import shutil

            shutil.copyfile(state["video_path"], out)
            return {
                "status": "merging",
                "video_path": str(out),
                "audio_path": None,
                "duration_s": duration,
                "muted": True,
                "error": None,
            }
        except Exception as fallback_error:  # noqa: BLE001
            return {
                "status": "failed",
                "video_path": None,
                "duration_s": None,
                "error": f"merge failed and raw-video fallback failed: {fallback_error}",
            }
    return {
        "status": "merging",
        "video_path": str(out),
        "duration_s": duration,
        "error": None,
    }


def after_merge(state: SceneState):
    if state.get("video_path") and state.get("error") is None:
        return "critique"
    return "fail"


def accept_node(state: SceneState) -> dict[str, Any]:
    return {"status": "ready", "error": None}


# ---------------------------------------------------------------- edges


def after_render(state: SceneState):
    if state["error"] is None:
        return "merge"
    settings = get_settings()
    if state["attempts"] >= settings.max_scene_retries:
        return "fail"
    if settings.codegen_mode == "spec" and not state.get("fell_back"):
        return "fallback_codegen"  # compiled scene failed -> try raw LLM codegen
    return "fix"


def fail_node(state: SceneState) -> dict[str, Any]:
    return {"status": "failed", "video_path": None, "duration_s": None}


async def fallback_codegen(state: SceneState) -> dict[str, Any]:
    """Tier 2: spec compilation failed -> raw LLM codegen with RITL retries."""
    logger.warning("scene %s: spec path failed, falling back to raw codegen", state["scene_id"])
    result = await generate_code(state)
    return {**result, "fell_back": True, "spec_json": None}


def build_scene_graph():
    g = StateGraph(SceneState)
    g.add_node("tts", synth_tts)
    g.add_node("specgen", generate_spec)
    g.add_node("mathcheck", mathcheck)
    g.add_node("codegen", generate_code)
    g.add_node("fallback_codegen", fallback_codegen)
    g.add_node("fix", fix_code)
    g.add_node("render", render_node)
    g.add_node("critique", critique_node)
    g.add_node("merge", merge_node)
    g.add_node("accept", accept_node)
    g.add_node("fail", fail_node)

    def entry(state: SceneState):
        settings = get_settings()
        if settings.tts_enabled:
            return "tts"
        return "specgen" if settings.codegen_mode == "spec" else "codegen"

    def after_tts(state: SceneState):
        return "specgen" if get_settings().codegen_mode == "spec" else "codegen"

    g.set_conditional_entry_point(
        entry,
        {"tts": "tts", "specgen": "specgen", "codegen": "codegen"},
    )
    g.add_conditional_edges(
        "tts", after_tts, {"specgen": "specgen", "codegen": "codegen"}
    )
    g.add_edge("specgen", "mathcheck")
    g.add_edge("mathcheck", "render")
    g.add_edge("codegen", "render")
    g.add_edge("fix", "render")
    g.add_edge("fallback_codegen", "render")
    g.add_conditional_edges(
        "render",
        after_render,
        {"merge": "merge", "fix": "fix", "fail": "fail", "fallback_codegen": "fallback_codegen"},
    )
    g.add_conditional_edges(
        "merge", after_merge, {"critique": "critique", "fail": "fail"}
    )
    g.add_conditional_edges(
        "critique",
        after_critique,
        {"accept": "accept", "fix": "fix", "fail": "fail"},
    )
    g.add_edge("accept", END)
    g.add_edge("fail", END)
    return g.compile()


SCENE_GRAPH = build_scene_graph()


async def run_scene(
    project_id: str,
    scene_id: str,
    scene_idx: int,
    title: str,
    narration: str,
    visual_description: str,
    context: str = "",
    project_topic: str = "",
    on_update: Callable[[dict], Awaitable[None]] | None = None,
) -> tuple[SceneResult, list[dict]]:
    """Run the scene pipeline. Returns (result, step_events)."""
    events: list[dict] = []
    initial: SceneState = {
        "project_id": project_id,
        "scene_id": scene_id,
        "scene_idx": scene_idx,
        "title": title,
        "narration": narration,
        "visual_description": visual_description,
        "context": context,
        "project_topic": project_topic,
        "audio_path": None,
        "audio_duration": None,
        "muted": False,
        "code": None,
        "error": None,
        "attempts": 0,
        "status": "pending",
        "video_path": None,
        "duration_s": None,
        "fell_back": False,
        "critiqued": False,
        "qa_attempts": 0,
        "qa_exhausted": False,
        "spec_json": None,
        "treatment_md": None,
    }

    final_state: SceneState = {**initial}
    async for chunk in SCENE_GRAPH.astream(initial, stream_mode="updates"):
        for node_name, update in chunk.items():
            # LangGraph emits {node_name: None} when a node returns an empty
            # update; skip it rather than crashing.
            if not update:
                continue
            events.append({"node": node_name, **update})
            final_state.update(update)
            if on_update:
                await on_update({"node": node_name, "update": update})

    return _as_result(final_state, events), events


def _as_result(state: dict, events: list[dict]) -> SceneResult:
    result = {
        "status": state.get("status", "failed"),
        "manim_code": state.get("code"),
        "video_path": state.get("video_path"),
        "audio_path": state.get("audio_path"),
        "duration_s": state.get("duration_s"),
        "attempts": state.get("attempts", 0),
        "error": state.get("error"),
    }
    result["spec_json"] = state.get("spec_json")
    result["qa_warning"] = state.get("qa_warning")
    return result

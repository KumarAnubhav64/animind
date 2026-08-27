"""Production service: async pipeline over scenes (produce, regenerate, stitch)."""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from app.agents.scene_graph import run_scene
from app.config import get_settings
from app.db.models import Scene
from app.db.repositories import project_repo, scene_repo
from app.pipeline.events import publish
from app.pipeline.video import stitch_scenes

logger = logging.getLogger("animind.production")


async def _publish_scene_status(
    project_id: str, scene_id: str, status: str, extra: dict | None = None
):
    event = {"type": "scene", "scene_id": scene_id, "status": status}
    if extra:
        event.update(extra)
    await publish(project_id, event)


def _project_media_dir(project_id: str) -> Path:
    return Path(get_settings().media_dir).resolve() / project_id


def _final_path(project_id: str) -> Path:
    return _project_media_dir(project_id) / "final_video.mp4"


def _discard_final(project_id: str):
    _final_path(project_id).unlink(missing_ok=True)


def project_artifacts_ready(project_id: str) -> bool:
    scenes = scene_repo.list_for_project(project_id)
    return bool(scenes) and all(
        scene.status == "ready"
        and bool((scene.manim_code or "").strip())
        and bool(scene.video_path)
        and Path(scene.video_path).is_file()
        and Path(scene.video_path).stat().st_size >= 1024
        for scene in scenes
    )


def reconcile_ready_projects():
    """Invalidate legacy/partial rows produced before strict publication checks."""
    for project in project_repo.list():
        if project.status != "ready":
            continue
        final_path = Path(project.final_video_path) if project.final_video_path else None
        if project_artifacts_ready(project.id) and final_path and final_path.is_file():
            continue
        project_repo.update(
            project.id,
            status="failed",
            error="Project artifacts are incomplete; produce all scenes again",
            final_video_path=None,
        )


def _extract_visual_state(spec_json: str | None) -> str:
    """Extract a structured summary of visible objects from a scene's spec.

    Instead of dumping raw JSON, produces a human-readable inventory like:
        - circle (blue) at left (-3.4, 0.0)
        - equation A = πr² (purple) at bottom
    This gives the next scene's spec coder a clear picture of what exists.
    """
    if not spec_json:
        return ""
    try:
        from app.schemas.spec import SceneSpec
        spec = SceneSpec.model_validate_json(spec_json)
    except Exception:  # noqa: BLE001
        return ""

    alive: dict[str, dict] = {}  # id -> {op, color, position, text/tex}
    for beat in spec.beats:
        for a in beat.actions:
            if a.op == "remove":
                target = (a.target or "").lower()
                if target == "all":
                    alive.clear()
                elif target in alive:
                    del alive[target]
            elif a.op.startswith("add_") and a.id:
                pos = ""
                if a.at and len(a.at) >= 2:
                    pos = f"at ({a.at[0]:.1f}, {a.at[1]:.1f})"
                elif a.region:
                    pos = f"in {a.region}"
                desc = {
                    "op": a.op.replace("add_", ""),
                    "color": a.color or "default",
                    "pos": pos,
                }
                if a.text:
                    desc["text"] = a.text[:40]
                if a.tex:
                    desc["tex"] = a.tex[:40]
                if a.expr:
                    desc["expr"] = a.expr[:30]
                alive[a.id] = desc
            elif a.op == "transform" and a.id and a.id in alive:
                if a.text:
                    alive[a.id]["text"] = a.text[:40]
                if a.tex:
                    alive[a.id]["tex"] = a.tex[:40]

    if not alive:
        return "Scene ends with a clean slate (all objects removed)."
    lines = []
    for oid, info in alive.items():
        parts = [f"{info['op']} '{oid}'"]
        if info["color"] != "default":
            parts.append(f"({info['color']})")
        if info["pos"]:
            parts.append(info["pos"])
        if "text" in info:
            parts.append(f'text="{info["text"]}"')
        if "tex" in info:
            parts.append(f'tex="{info["tex"]}"')
        if "expr" in info:
            parts.append(f'expr={info["expr"]}')
        lines.append("- " + " ".join(parts))
    return "\n".join(lines)


def _continuity_context(scene: Scene) -> str:
    """Compact, truthful summary of the candidate that was actually delivered."""
    visual_state = _extract_visual_state(scene.spec_json)
    # Extract a brief conceptual summary from narration (first 1-2 sentences)
    narration = (scene.narration or "").strip()
    concept = ""
    if narration:
        # Take first two sentences as the conceptual summary
        sentences = []
        for sent in narration.replace("? ", ". ").replace("! ", ". ").split(". "):
            sent = sent.strip().rstrip(".")
            if sent:
                sentences.append(sent)
            if len(sentences) >= 2:
                break
        concept = ". ".join(sentences) + "." if sentences else narration[:120]

    parts = [f"Scene {scene.idx + 1} ({scene.title}):"]
    if concept:
        parts.append(f"Concept: {concept}")
    if visual_state:
        parts.append(f"Visual state at end:\n{visual_state}")
    else:
        parts.append(f"Visual description: {scene.visual_description or 'none'}")
    return "\n".join(parts)


def _prior_scene_context(project_id: str, before_idx: int) -> str:
    prior = [
        scene
        for scene in scene_repo.list_for_project(project_id)
        if scene.idx < before_idx and scene.status == "ready"
    ]
    parts = [_continuity_context(scene) for scene in prior]
    # Cap total context to avoid exceeding LLM context window (~3K chars = ~750 tokens)
    joined = "\n\n".join(parts)
    if len(joined) > 3000:
        joined = joined[:2800] + "\n\n[context truncated for length]"
    return joined


def _reset_scene(scene: Scene):
    scene_repo.update(
        scene.id,
        status="pending",
        error=None,
        manim_code=None,
        video_path=None,
        audio_path=None,
        duration_s=None,
        attempts=0,
        spec_json=None,
    )


def _reset_scenes(scenes: list[Scene], from_idx: int = 0):
    for scene in scenes:
        if scene.idx >= from_idx:
            _reset_scene(scene)


async def _produce_sequential(
    scenes: list[Scene], start_idx: int = 0
) -> dict[int, bool]:
    """Produce a suffix in order, carrying only delivered prior scenes forward."""
    results: dict[int, bool] = {}
    context_parts: list[str] = []
    for scene in scenes:
        if scene.idx < start_idx:
            fresh = scene_repo.get(scene.id)
            results[scene.idx] = bool(fresh and fresh.status == "ready")
            if not results[scene.idx]:
                continue
            context_parts.append(_continuity_context(fresh))
            continue
        ok = await produce_scene(scene, context="\n\n".join(context_parts))
        results[scene.idx] = ok
        fresh = scene_repo.get(scene.id)
        if ok and fresh and fresh.status == "ready":
            context_parts.append(_continuity_context(fresh))
        elif not ok:
            # Later scenes cannot form a valid final video without this scene;
            # stop here to avoid spending more free-tier calls on a broken run.
            for remaining in scenes:
                if remaining.idx > scene.idx:
                    results[remaining.idx] = False
            break
    return results


async def produce_scene(scene: Scene, context: str = "") -> bool:
    """Run the LangGraph scene pipeline for one scene and persist results."""
    _reset_scene(scene)
    scene_repo.update(
        scene.id,
        status="tts" if get_settings().tts_enabled else "coding",
    )
    await _publish_scene_status(
        scene.project_id,
        scene.id,
        "tts" if get_settings().tts_enabled else "coding",
    )

    agent_by_node = {
        "tts": "Voice Artist",
        "specgen": "SpecCoder",
        "mathcheck": "Math Expert",
        "codegen": "SceneCoder",
        "fallback_codegen": "Fallback Coder",
        "fix": "Fixer",
        "render": "Renderer",
        "merge": "Editor",
        "critique": "Vision Critic",
        "accept": "Producer",
        "fail": "Producer",
    }

    async def on_update(event: dict):
        node = event["node"]
        update = event.get("update") or {}
        details = {}
        for key in ("error", "attempts", "duration_s", "qa_attempts", "math_fixed", "math_issues"):
            if key in update and update[key] is not None:
                details[key] = update[key]
        await publish(
            scene.project_id,
            {
                "type": "workflow",
                "scene_id": scene.id,
                "scene_idx": scene.idx,
                "agent": agent_by_node.get(node, node),
                "node": node,
                "message": _workflow_message(node, update),
                "details": details,
            },
        )

    try:
        result, _events = await run_scene(
            scene.project_id,
            scene.id,
            scene.title,
            scene.narration,
            scene.visual_description or "",
            context=context,
            on_update=on_update,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("scene %s crashed", scene.id)
        result = {
            "status": "failed",
            "manim_code": None,
            "video_path": None,
            "audio_path": None,
            "duration_s": None,
            "attempts": 0,
            "error": f"{type(e).__name__}: {e}",
            "spec_json": None,
        }

    scene_repo.update(
        scene.id,
        status=result["status"],
        manim_code=result["manim_code"],
        video_path=result["video_path"],
        audio_path=result["audio_path"],
        duration_s=result["duration_s"],
        attempts=result["attempts"],
        spec_json=result.get("spec_json"),
        error=(result["error"] or "")[:2000] or None,
    )
    await _publish_scene_status(
        scene.project_id,
        scene.id,
        result["status"],
        {"attempts": result["attempts"], "error": result["error"]},
    )
    return result["status"] == "ready"


def _workflow_message(node: str, update: dict) -> str:
    messages = {
        "tts": "Preparing narration audio and measuring its duration.",
        "specgen": "Planning declarative beats, objects, and visual layout.",
        "mathcheck": "A subject expert is verifying every formula, number, and axis range against the narration.",
        "codegen": "Writing a Manim scene from the narration and visual intent.",
        "fallback_codegen": "The spec path was not usable, so raw code generation is taking over.",
        "fix": "Repairing the candidate using the render or visual-QA feedback.",
        "render": "Rendering the candidate in Manim Community Edition.",
        "merge": "Merging animation with voiceover or burned-in captions.",
        "critique": "Checking opening, middle, and closing frames for cutoff, overlap, and relevance.",
        "accept": "Candidate accepted and stored as the scene video.",
        "fail": "Scene could not produce a valid candidate within its retry budget.",
    }
    message = messages.get(node, "Working on the scene.")
    if node == "mathcheck" and update.get("math_fixed"):
        message += " Corrections applied to the scene spec and recompiled."
    error = update.get("error")
    return f"{message} {error}" if error else message


async def produce_project(project_id: str):
    """Produce all scenes, then stitch. Sequential mode rolls each finished
    scene's spec forward as context so later scenes stay consistent."""
    settings = get_settings()
    try:
        _discard_final(project_id)
        project_repo.update(
            project_id,
            status="producing",
            error=None,
            final_video_path=None,
        )
        await publish(project_id, {"type": "project", "status": "producing"})

        scenes = sorted(scene_repo.list_for_project(project_id), key=lambda s: s.idx)
        _reset_scenes(scenes)

        if settings.sequential_scenes:
            results = await _produce_sequential(scenes)
            if not all(results.get(scene.idx, False) for scene in scenes):
                failed = [
                    str(scene.idx + 1)
                    for scene in scenes
                    if not results.get(scene.idx, False)
                ]
                raise RuntimeError(f"Scene production failed: {', '.join(failed)}")
        else:
            sem = asyncio.Semaphore(settings.max_parallel_scenes)

            async def worker(scene: Scene) -> bool:
                async with sem:
                    return await produce_scene(scene)

            results = await asyncio.gather(*(worker(s) for s in scenes))
            if not all(results):
                failed = [str(scene.idx + 1) for scene, ok in zip(scenes, results) if not ok]
                raise RuntimeError(f"Scene production failed: {', '.join(failed)}")

        await restitch(project_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("project %s failed", project_id)
        _discard_final(project_id)
        project_repo.update(
            project_id,
            status="failed",
            error=str(e)[:2000],
            final_video_path=None,
        )
        await publish(project_id, {"type": "project", "status": "failed", "error": str(e)})


async def regenerate_scene(project_id: str, scene_id: str):
    try:
        scene = scene_repo.get(scene_id)
        if scene is None:
            return
        _discard_final(project_id)
        project_repo.update(
            project_id,
            status="producing",
            error=None,
            final_video_path=None,
        )
        await publish(project_id, {"type": "project", "status": "producing"})
        scenes = sorted(scene_repo.list_for_project(project_id), key=lambda s: s.idx)
        _reset_scenes(scenes, scene.idx)
        results = await _produce_sequential(scenes, start_idx=scene.idx)
        suffix = [item for item in scenes if item.idx >= scene.idx]
        if suffix and all(results.get(item.idx, False) for item in suffix):
            await restitch(project_id)
        else:
            failed = [
                str(item.idx + 1)
                for item in suffix
                if not results.get(item.idx, False)
            ]
            error = f"Scene regeneration failed: {', '.join(failed) or scene.idx + 1}"
            project_repo.update(
                project_id,
                status="failed",
                error=error,
                final_video_path=None,
            )
            await publish(
                project_id,
                {"type": "project", "status": "failed", "error": error},
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("regenerate %s failed", scene_id)
        _discard_final(project_id)
        scene_repo.update(scene_id, status="failed", error=str(e)[:2000])
        project_repo.update(
            project_id,
            status="failed",
            error=str(e)[:2000],
            final_video_path=None,
        )
        await publish(
            project_id,
            {"type": "project", "status": "failed", "error": str(e)},
        )


async def restitch(project_id: str):
    scenes = scene_repo.list_for_project(project_id)
    if not project_artifacts_ready(project_id):
        raise RuntimeError("Cannot publish final video until every scene is ready")
    out = _final_path(project_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary_out = out.with_name(f".final-{uuid.uuid4().hex}.mp4")
    project_repo.update(project_id, status="stitching")
    await publish(project_id, {"type": "project", "status": "stitching"})
    try:
        await stitch_scenes([s.video_path for s in scenes], temporary_out)
        if not temporary_out.is_file() or temporary_out.stat().st_size < 1024:
            raise RuntimeError("stitcher produced an empty final video")
        os.replace(temporary_out, out)
        project_repo.update(
            project_id, status="ready", final_video_path=str(out), error=None
        )
    finally:
        temporary_out.unlink(missing_ok=True)
    await publish(project_id, {"type": "project", "status": "ready"})

import asyncio
import ast
import glob
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


def normalize_manim_code(code: str) -> str:
    """Apply deterministic compatibility fixes before invoking Manim CE."""
    return (
        code.replace("set_start_and_end_points(", "put_start_and_end_on(")
        .replace("UP.rotate(", "rotate_vector(UP, ")
        .replace("DOWN.rotate(", "rotate_vector(DOWN, ")
        .replace("LEFT.rotate(", "rotate_vector(LEFT, ")
        .replace("RIGHT.rotate(", "rotate_vector(RIGHT, ")
    )


def preflight_visual_code(code: str) -> str | None:
    lowered = code.lower()
    if "hello, world" in lowered or "hello world" in lowered:
        return "Generated Manim code is a placeholder, not an explanation"
    if lowered.count("circle(") and lowered.count("triangle(") >= 4 and "transform" not in lowered:
        return "Generated transformation scene has repeated shapes without a visible transformation"
    return None


async def render_manim(
    code: str, work_dir: Path, media_dir: Path
) -> tuple[bool, str, str | None]:
    """Write Manim code to disk and render it.

    Returns (success, error_output, video_path).
    """
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    stable_path = work_dir / "scene.mp4"
    stable_path.unlink(missing_ok=True)
    (work_dir / "scene_final.mp4").unlink(missing_ok=True)
    py_file = work_dir / "scene.py"
    normalized_code = normalize_manim_code(code) if isinstance(code, str) else ""
    py_file.write_text(normalized_code, encoding="utf-8")
    if not isinstance(normalized_code, str) or not normalized_code.strip():
        return False, "Generated Manim code is empty", None
    preflight_error = preflight_visual_code(normalized_code)
    if preflight_error:
        return False, preflight_error, None
    try:
        tree = ast.parse(normalized_code)
    except SyntaxError as exc:
        return False, f"Generated Manim code has invalid Python syntax: {exc}", None
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    video_scene = next((cls for cls in classes if cls.name == "VideoScene"), None)
    if video_scene is None:
        return False, "Generated Manim code does not define VideoScene", None
    construct = next(
        (
            node
            for node in video_scene.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "construct"
        ),
        None,
    )
    if construct is None:
        return False, "VideoScene does not define construct", None
    calls = [node for node in ast.walk(construct) if isinstance(node, ast.Call)]
    has_scene_output = any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr in {"play", "add", "add_foreground_mobject"}
        for call in calls
    )
    if not has_scene_output:
        return False, "VideoScene.construct contains no animation or mobject", None

    py_file = py_file.resolve()
    media_dir = media_dir.resolve()

    # Every retry gets an isolated media directory and output name. Manim can
    # exit successfully for an empty/no-animation module, so reusing a fixed
    # path could otherwise copy an older attempt as the new render.
    attempt_media_dir = Path(
        tempfile.mkdtemp(prefix=".render-", dir=str(work_dir))
    ).resolve()
    out_name = f"s_{work_dir.name}_{uuid.uuid4().hex[:10]}"
    cmd = [
        sys.executable,
        "-m",
        "manim",
        "render",
        "-qm",
        str(py_file),
        "-o",
        out_name,
        "--media_dir",
        str(attempt_media_dir),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(work_dir),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, "Manim render timed out after 300s", None

        output = stdout.decode(errors="replace")[-4000:]
        if proc.returncode != 0:
            return False, output, None

        videos = sorted(
            glob.glob(
                str(attempt_media_dir / "videos" / "**" / f"{out_name}.mp4"),
                recursive=True,
            )
        )
        if not videos:
            return False, f"Render exited 0 but no video found. Output:\n{output}", None

        candidate = Path(videos[0])
        if not candidate.is_file() or candidate.stat().st_size < 1024:
            return False, "Render produced an empty or truncated video", None

        # Copy to a stable path inside the scene dir; the attempt directory is
        # disposable and never becomes the source of a later retry.
        temporary_stable = work_dir / f".scene-{uuid.uuid4().hex}.mp4"
        temporary_stable.write_bytes(candidate.read_bytes())
        os.replace(temporary_stable, stable_path)
        return True, "", str(stable_path)
    finally:
        for temporary in work_dir.glob(".scene-*.mp4"):
            temporary.unlink(missing_ok=True)
        shutil.rmtree(attempt_media_dir, ignore_errors=True)

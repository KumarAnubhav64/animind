import asyncio
import ast
import glob
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


_PLAIN_SCENE_CLASS_RE = re.compile(r"class\s+VideoScene\s*\(\s*Scene\s*\)")


def _ensure_moving_camera(code: str) -> str:
    """`self.camera.frame` exists only on MovingCameraScene; on a plain Scene
    it crashes at render time with 'Camera' object has no attribute 'frame'
    (the most common LLM codegen crash). Rewriting the base class is
    deterministic, idempotent, and always safe — MovingCameraScene subclasses
    Scene, so scenes that never touch the camera are unaffected."""
    if "self.camera.frame" in code:
        code = _PLAIN_SCENE_CLASS_RE.sub("class VideoScene(MovingCameraScene)", code)
    return code


def normalize_manim_code(code: str) -> str:
    """Apply deterministic compatibility fixes before invoking Manim CE."""
    return _ensure_moving_camera(
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
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"Generated Manim code has invalid Python syntax: {exc}"
    return None


def validate_scene_structure(tree: ast.AST) -> str | None:
    """Ensure the module defines a VideoScene with a construct that emits output."""
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    video_scene = next((cls for cls in classes if cls.name == "VideoScene"), None)
    if video_scene is None:
        return "Generated Manim code does not define VideoScene"
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
        return "VideoScene does not define construct"
    calls = [node for node in ast.walk(construct) if isinstance(node, ast.Call)]
    has_scene_output = any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr in {"play", "add", "add_foreground_mobject"}
        for call in calls
    )
    if not has_scene_output:
        return "VideoScene.construct contains no animation or mobject"
    return None


def _ends_in_zero_opacity(node: ast.AST) -> bool:
    """True if the expression is a call chain ending in `.set_opacity(0)` or `.fade(1)`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in {"set_opacity", "fade"}):
        return False
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return False
    value = node.args[0].value
    if not isinstance(value, (int, float)):
        return False
    if func.attr == "set_opacity":
        return value == 0
    return value == 1


def _call_root_name(node: ast.AST) -> str | None:
    """Resolve `mob.set_opacity(...)` / `mob.fade(...)` to the root variable name."""
    value = node.func.value if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) else None
    while isinstance(value, ast.Attribute):
        value = value.value
    if isinstance(value, ast.Name):
        return value.id
    return None


def detect_opacity_zero_then_fade_in(tree: ast.AST) -> str | None:
    """Reject mobjects forced to opacity 0 and then FadeIn'ed.

    FadeIn's target is the mobject itself, so it ends at whatever opacity the
    mobject currently has — an opacity-0 mobject stays invisible forever.
    """
    zeroed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _ends_in_zero_opacity(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    zeroed.add(target.id)
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and _ends_in_zero_opacity(node.value)
        ):
            name = _call_root_name(node.value)
            if name:
                zeroed.add(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "FadeIn":
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in zeroed:
                    return (
                        f"Invalid Manim (line {node.lineno}): {arg.id} has its opacity forced to 0 "
                        "and is then FadeIn'ed. FadeIn ends at the mobject's current opacity, so it "
                        "stays invisible. Remove `.set_opacity(0)`/`.fade(1)` (FadeIn already starts "
                        "faded) or reveal it with `Write`/`Create` instead."
                    )
    return None


def _uses_self_camera_frame(tree: ast.AST) -> bool:
    """True when the code reads `self.camera.frame` (a MovingCameraScene-only
    attribute)."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "frame"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "camera"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
        ):
            return True
    return False


def detect_camera_frame_on_plain_scene(tree: ast.AST) -> str | None:
    """Backstop for camera code the regex normalizer cannot fix (e.g. a base
    class written as `manim.Scene` or an alias). `self.camera.frame` on a
    plain Scene raises 'Camera' object has no attribute 'frame' at render."""
    if not _uses_self_camera_frame(tree):
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "VideoScene":
            bases = [
                base.id
                for base in node.bases
                if isinstance(base, ast.Name)
            ]
            if "MovingCameraScene" not in bases:
                return (
                    "Invalid Manim: `self.camera.frame` requires the scene class to "
                    "inherit MovingCameraScene — write `class VideoScene(MovingCameraScene)`, "
                    "or drop the camera calls and zoom by scaling/moving the mobjects "
                    "themselves. (`self.camera.background_color` is fine on any Scene.)"
                )
    return None


def validate_visual_code(code: str) -> str | None:
    """Full deterministic validation of a complete scene before rendering.

    Returns the first actionable error, or None if the code is renderable.
    """
    if not code or not code.strip():
        return "Generated Manim code is empty"
    preflight_error = preflight_visual_code(code)
    if preflight_error:
        return preflight_error
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Generated Manim code has invalid Python syntax: {exc}"
    structure_error = validate_scene_structure(tree)
    if structure_error:
        return structure_error
    camera_error = detect_camera_frame_on_plain_scene(tree)
    if camera_error:
        return camera_error
    get_area_error = detect_get_area_misuse(tree)
    if get_area_error:
        return get_area_error
    pattern_error = detect_invalid_manim_patterns(tree)
    if pattern_error:
        return pattern_error
    return detect_opacity_zero_then_fade_in(tree)


# Common LLM codegen mistakes that are deterministic and detectable before
# Manim ever runs. Catching them here saves a full render cycle and hands the
# Fixer a short, actionable message instead of a 4000-char traceback.
ANIMATION_CLASSES = {
    "Animation", "AnimationGroup", "Succession", "LaggedStart",
    "Write", "Create", "Uncreate", "FadeIn", "FadeOut", "FadeTransform",
    "FadeInFrom", "FadeOutAndShift", "FadeTransformPieces",
    "Transform", "ReplacementTransform", "TransformFromCopy", "MoveToTarget",
    "Indicate", "Circumscribe", "Flash", "GrowFromCenter", "GrowFromEdge",
    "GrowFromPoint", "ScaleInPlace", "Rotate", "Rotating", "ApplyMethod",
    "ApplyFunction", "ApplyPointwiseFunction", "ApplyMatrix",
    "ApplyComplexFunction", "ShowIncreasingSubsets", "AddTextWordByWord",
    "ShrinkToCenter", "FadeOutThenShrinkToCenter", "Unwrite",
}


def _is_animation_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ANIMATION_CLASSES
    )


def _chain_contains_animate(node: ast.AST) -> bool:
    while isinstance(node, ast.Attribute):
        if node.attr == "animate":
            return True
        node = node.value
    return False


def _chain_is_self_play(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "play"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _chain_is_self_move_camera(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "move_camera"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def detect_invalid_manim_patterns(tree: ast.AST) -> str | None:
    """Reject Manim code that can only crash the renderer, with a fixable reason."""
    for node in ast.walk(tree):
        # `2 * Write(x)` or `Write(x) * 2` — animations are not numbers. The
        # intent is timing, which belongs on run_time / self.play.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for operand in (node.left, node.right):
                if _is_animation_call(operand) or _chain_contains_animate(operand):
                    return (
                        f"Invalid Manim (line {node.lineno}): an animation object is being "
                        "multiplied by a number, e.g. `2 * Write(x)`. Manim animations cannot "
                        "be scaled with `*`. Express timing as `Write(x, run_time=2)` or "
                        "`self.play(..., run_time=2)`."
                    )
        # `mob.move_to(pos, run_time=...)` — run_time only exists on self.play,
        # `.animate` chains, and animation constructors.
        if isinstance(node, ast.Call):
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            if "run_time" not in kwargs:
                continue
            func = node.func
            if (
                _chain_is_self_play(func)
                or _chain_is_self_move_camera(func)
                or _chain_contains_animate(func)
            ):
                continue
            if isinstance(func, ast.Name) and func.id in ANIMATION_CLASSES:
                continue
            return (
                f"Invalid Manim (line {node.lineno}): `run_time` is not a valid argument for this "
                "call. `run_time` belongs only on `self.play(..., run_time=2)`, on an `.animate` "
                "chain, or on an animation constructor like `Write(x, run_time=2)` — not on plain "
                "mobject methods such as `.move_to(...)` or `.shift(...)`."
            )
    return None


def detect_get_area_misuse(tree: ast.AST) -> str | None:
    """Reject `get_area` calls that can only crash the renderer.

    Manim's `Axes.get_area` signature is `get_area(graph, x_range=None, ...)`:
    - arg 1 must be a *plotted graph mobject* (result of `axes.plot(f)`), never a
      bare function/lambda → otherwise `'function' object has no attribute 'function'`.
    - arg 2 (`x_range`) must be a tuple of numbers, never a lambda → otherwise
      `cannot unpack non-iterable function object`.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get_area"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, (ast.Lambda, ast.FunctionDef)):
            return (
                f"Invalid Manim (line {node.lineno}): `get_area()` received a lambda/function as "
                "its first argument. `get_area` needs a plotted graph mobject, e.g. "
                "`axes.get_area(axes.plot(func), x_range=[...])` — plot the function first, "
                "then pass that graph to `get_area`."
            )
        if len(node.args) >= 2 and isinstance(node.args[1], (ast.Lambda, ast.FunctionDef)):
            return (
                f"Invalid Manim (line {node.lineno}): `get_area()` second positional argument is "
                "a lambda, but that slot is `x_range` (a tuple like `[0, 4]`). The graph must be "
                "the first argument: `axes.get_area(axes.plot(func), x_range=[...])`."
            )
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
    validation_error = validate_visual_code(normalized_code)
    if validation_error:
        return False, validation_error, None

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

"""Math Expert: subject-expert correctness gate for SceneSpec.

Tier 1 (deterministic, zero model cost): syntax and value checks on plot
expressions, LaTeX, bar values, axis ranges, colors, and ops — the cases the
compiler silently papered over with defaults.

Tier 2 (optional LLM): a subject-expert review that reads the narration and
verifies every formula/number/range against the narration's claims, returning
surgical per-action corrections we apply deterministically and recompile.

The gate is FAIL-OPEN: budget exhausted or reviewer down -> proceed with a
logged warning, so free-tier caps can never deadlock the pipeline.
"""

import ast
import asyncio
import json
import logging
import math

from app.agents.llm import fixer_llm
from app.config import get_settings
from app.schemas.spec import SceneSpec

logger = logging.getLogger("animind.math")

KNOWN_OPS = {
    "set_title", "add_text", "add_equation", "add_shape", "add_asset", "add_axes",
    "add_bars", "add_curve", "label", "connect", "animate", "transform", "move",
    "rotate", "pulse", "remove", "clear", "wait",
}
COLORS = {
    "blue", "red", "green", "yellow", "teal", "purple", "orange",
    "gold", "white", "grey", "gray", "pink",
}
SHAPES = {
    "circle", "square", "dot", "triangle", "diamond", "ring",
    "sphere", "cube", "cylinder", "cone", "torus",
}

_MATH_WORDS = {
    "area", "sum", "equation", "formula", "equals", "derivative", "integral",
    "sine", "cosine", "sqrt", "square", "squared", "proportion", "rate",
    "slope", "angle", "radius", "perimeter", "volume", "distance",
    "velocity", "acceleration", "force", "period", "frequency", "power",
}


def _iter_actions(spec: SceneSpec):
    for beat in spec.beats:
        for action in beat.actions:
            yield action


def has_math_content(spec: SceneSpec, narration: str) -> bool:
    """Cheap heuristic: math fields anywhere, or math-y narration."""
    for action in _iter_actions(spec):
        if action.tex or action.expr or action.values or action.x_range or action.y_range:
            return True
    if any(char.isdigit() for char in narration):
        return True
    words = set(narration.lower().split())
    return bool(words & _MATH_WORDS)


# Names the spec compiler permits in plot expressions (mirrors _PLOT_ALLOWED).
_ALLOWED_EXPR_NAMES = {"x", "sin", "cos", "tan", "exp", "log", "sqrt", "pi", "e"}


def _expr_namespace() -> dict:
    return {
        "math": math,
        **{name: getattr(math, name) for name in _ALLOWED_EXPR_NAMES if hasattr(math, name)},
    }


def _check_expr(expr: str) -> str | None:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"expr '{expr}' is not valid Python: {e.msg}"
    undefined = {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id not in _ALLOWED_EXPR_NAMES
    }
    if undefined:
        return f"expr '{expr}' uses undefined name(s) {sorted(undefined)}"
    try:
        for x in (0.5, -0.5, 2.0):
            globs = {"__builtins__": {}, **_expr_namespace(), "x": x}
            eval(compile(expr, "<expr>", "eval"), globs, globs)
    except ZeroDivisionError:
        pass
    except Exception as e:  # noqa: BLE001
        return f"expr '{expr}' fails to evaluate at sample points: {e}"
    return None


def _check_tex(tex: str) -> str | None:
    if not tex or not tex.strip():
        return "empty LaTeX equation"
    if tex.count("{") != tex.count("}"):
        return f"unbalanced braces in LaTeX: {tex[:60]}"
    return None


def _check_numbers(values, label: str) -> str | None:
    for value in values:
        try:
            if not math.isfinite(float(value)):
                return f"{label} contains a non-finite value: {value}"
        except (TypeError, ValueError):
            return f"{label} contains a non-numeric value: {value}"
    return None


def _check_range(rng, label: str) -> str | None:
    if not (2 <= len(rng) <= 3):
        return f"{label} must be [start, end] or [start, end, step], got {rng}"
    try:
        start, end = float(rng[0]), float(rng[1])
    except (TypeError, ValueError):
        return f"{label} endpoints must be numbers, got {rng}"
    if start >= end:
        return f"{label} start must be less than end, got {rng}"
    if len(rng) == 3:
        try:
            step = float(rng[2])
        except (TypeError, ValueError):
            return f"{label} step must be a number, got {rng[2]}"
        if step <= 0:
            return f"{label} step must be positive, got {rng[2]}"
    return None


def validate_math(spec: SceneSpec, narration: str = "") -> list[str]:
    """Deterministic correctness checks; returns a list of concrete issues."""
    issues: list[str] = []
    for action in _iter_actions(spec):
        if action.op not in KNOWN_OPS:
            issues.append(f"unknown op '{action.op}' (id={action.id})")
        if action.tex:
            issue = _check_tex(action.tex)
            if issue:
                issues.append(f"[{action.id}] {issue}")
        if action.expr:
            issue = _check_expr(action.expr)
            if issue:
                issues.append(f"[{action.id}] {issue}")
        if action.values:
            issue = _check_numbers(action.values, f"[{action.id}] values")
            if issue:
                issues.append(issue)
        for rng, label in (
            (action.x_range, f"[{action.id}] x_range"),
            (action.y_range, f"[{action.id}] y_range"),
        ):
            if rng:
                issue = _check_range(rng, label)
                if issue:
                    issues.append(issue)
        if action.scale is not None:
            try:
                if not (math.isfinite(float(action.scale)) and float(action.scale) > 0):
                    issues.append(f"[{action.id}] scale must be positive, got {action.scale}")
            except (TypeError, ValueError):
                issues.append(f"[{action.id}] scale must be a number, got {action.scale}")
        if action.seconds is not None:
            try:
                if not (math.isfinite(float(action.seconds)) and float(action.seconds) > 0):
                    issues.append(f"[{action.id}] seconds must be positive, got {action.seconds}")
            except (TypeError, ValueError):
                issues.append(f"[{action.id}] seconds must be a number, got {action.seconds}")
        if action.at:
            issue = _check_numbers(action.at, f"[{action.id}] at")
            if issue:
                issues.append(issue)
        if action.color and (action.color or "").lower() not in COLORS:
            issues.append(f"[{action.id}] unknown color '{action.color}' (falls back to white)")
        if action.shape and (action.shape or "").lower() not in SHAPES:
            issues.append(f"[{action.id}] unknown shape '{action.shape}'")
    return issues


# ---------------------------------------------------------------- LLM tier

REVIEW_SYSTEM_PROMPT = """\
You are a subject-expert mathematics and LaTeX reviewer for an educational \
animation. A scene is described by a declarative spec; it accompanies a narration.

Your job: verify every formula, number, axis range, and plotted expression in \
the spec against the mathematical claims in the narration. Catch wrong formulas, \
incorrect values, implausible ranges, and malformed LaTeX — not style or wording.

Respond with ONLY a JSON object:
{"ok": true/false, "issues": ["..."], "fixes": [{"id": "...", "field": "...", "value": ...}]}

Rules:
- ok is false when any real mathematical error exists.
- issues are short and specific ("area formula should be pi*r^2").
- fixes are SURGICAL corrections to existing actions only. id must exist in \
the spec. field must be one of: tex, text, expr, values, x_range, y_range, \
scale, color, shape, region, seconds, at. For values/x_range/y_range/at pass \
the new value as a JSON array; for scale/seconds as a number. Never invent new \
actions or change ids.
- If everything is correct, return {"ok": true, "issues": [], "fixes": []}.
"""


def math_expert_llm():
    """Reviewer model: a stronger router model when configured (e.g. a Claude
    variant via AgentRouter), else the fixer model. Never the codegen budget."""
    settings = get_settings()
    model = settings.math_expert_model or settings.premium_model
    if settings.router_api_key and model:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=settings.router_api_key,
            base_url=settings.router_base_url,
            temperature=0.0,
            timeout=120,
            default_headers={"User-Agent": "opencode/1.0.0"},
        )
    return fixer_llm(0)


async def math_review(spec: SceneSpec, narration: str, issues: list[str]) -> list[dict]:
    """Subject-expert LLM review; returns a list of surgical fixes ([] on any
    failure — the gate is fail-open)."""
    from app.agents.scene_graph import llm_with_retry

    messages = [
        ("system", REVIEW_SYSTEM_PROMPT),
        (
            "human",
            "Narration:\n"
            f"{narration}\n\n"
            "SceneSpec JSON:\n"
            f"{spec.model_dump_json()}\n\n"
            "Deterministic findings (confirm these are real, fix if possible):\n"
            + ("\n".join(f"- {i}" for i in issues) if issues else "- none")
            + "\n\nReview the mathematics and return ONLY the JSON object described above.",
        ),
    ]
    try:
        response = await asyncio.wait_for(
            llm_with_retry(math_expert_llm(), messages, attempts=1, wait_s=5.0),
            timeout=30.0,
        )
        text = response.content if isinstance(response.content, str) else str(response.content)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return []
        payload = json.loads(text[start : end + 1])
        fixes = payload.get("fixes") or []
        if not isinstance(fixes, list):
            return []
        return [
            fix for fix in fixes
            if isinstance(fix, dict) and fix.get("id") and fix.get("field")
        ]
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
        logger.warning("math review failed (fail-open): %s", e)
        return []


_LIST_FIELDS = {"values", "x_range", "y_range", "at"}
_FLOAT_FIELDS = {"scale", "seconds"}
_STR_FIELDS = {"tex", "text", "expr", "color", "shape", "region", "target", "to", "direction"}


def _coerce(field: str, raw) -> object | None:
    try:
        if field in _LIST_FIELDS:
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, list):
                return [float(v) for v in raw]
            return None
        if field in _FLOAT_FIELDS:
            return float(raw)
        return str(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def apply_fixes(spec: SceneSpec, fixes: list[dict]) -> bool:
    """Apply surgical fixes in place; return True if any fix was applied."""
    applied = False
    for fix in fixes:
        target_id = fix.get("id")
        field = fix.get("field")
        if field not in (_LIST_FIELDS | _FLOAT_FIELDS | _STR_FIELDS):
            continue
        value = _coerce(field, fix.get("value"))
        if value is None:
            continue
        for beat in spec.beats:
            for index, action in enumerate(beat.actions):
                if action.id != target_id:
                    continue
                try:
                    beat.actions[index] = action.model_copy(update={field: value})
                except Exception as e:  # noqa: BLE001
                    logger.warning("math fix for %s.%s rejected: %s", target_id, field, e)
                else:
                    applied = True
                break
    return applied

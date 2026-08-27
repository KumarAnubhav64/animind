"""Golden-set evals for the Math Expert gate.

Deterministic tier (validate_math / has_math_content / apply_fixes) is fully
unit-tested here. The LLM tier is fail-open and only reached with a real model;
we test its wiring (mathcheck node) by faking math_review.
"""

import asyncio

import pytest

from app.agents.math_expert import (
    apply_fixes,
    has_math_content,
    validate_math,
)
from app.schemas.spec import SceneSpec


def _spec(actions: list[dict]) -> SceneSpec:
    return SceneSpec(
        title="Golden set scene",
        beats=[{"description": "one beat", "actions": actions}],
    )


def test_validate_math_flags_bad_expr():
    issues = validate_math(_spec([{"op": "add_axes", "id": "curve", "expr": "x**"}]))
    assert any("not valid Python" in issue for issue in issues)


def test_validate_math_flags_unbalanced_tex():
    issues = validate_math(_spec([{"op": "add_equation", "id": "eq1", "tex": "x^{2"}]))
    assert any("unbalanced braces" in issue for issue in issues)


def test_validate_math_flags_inverted_range_and_step():
    issues = validate_math(
        _spec([{"op": "add_axes", "id": "g", "x_range": [3, -3], "y_range": [0, 1, 0]}])
    )
    assert any("start must be less than end" in issue for issue in issues)
    assert any("step must be positive" in issue for issue in issues)


def test_validate_math_flags_non_numeric_values():
    issues = validate_math(_spec([{"op": "add_bars", "id": "bars", "values": [float("nan")]}]))
    assert any("non-finite value" in issue for issue in issues)


def test_validate_math_flags_unknown_color_op_shape():
    issues = validate_math(
        _spec(
            [
                {"op": "fly", "id": "ghost"},
                {"op": "add_shape", "id": "s1", "shape": "heptagon", "color": "cerulean"},
            ]
        )
    )
    assert any("unknown op" in issue for issue in issues)
    assert any("unknown color" in issue for issue in issues)
    assert any("unknown shape" in issue for issue in issues)


def test_validate_math_accepts_clean_spec():
    issues = validate_math(
        _spec(
            [
                {"op": "add_axes", "id": "g", "x_range": [-3, 3, 1], "y_range": [-1, 1, 1], "expr": "sin(x)"},
                {"op": "add_equation", "id": "eq1", "tex": "x^{2}", "region": "center"},
                {"op": "add_bars", "id": "bars", "values": [1.5, 2.5, 3.0]},
            ]
        )
    )
    assert issues == []


def test_has_math_content_detects_fields_and_narration():
    assert has_math_content(_spec([{"op": "add_equation", "id": "e", "tex": "E=mc^2"}]), "")
    assert has_math_content(_spec([{"op": "wait", "seconds": 1}]), "The area is 42 square units.")
    assert not has_math_content(_spec([{"op": "wait", "seconds": 1}]), "A pathogen meets an antibody.")


def test_apply_fixes_updates_tex_and_ignores_unknown():
    spec = _spec([{"op": "add_equation", "id": "eq1", "tex": "x^{2"}])
    applied = apply_fixes(spec, [{"id": "eq1", "field": "tex", "value": "x^{2}"}])
    assert applied
    assert spec.beats[0].actions[0].tex == "x^{2}"

    applied_unknown = apply_fixes(spec, [{"id": "nope", "field": "tex", "value": "x"}])
    assert applied_unknown is False
    assert spec.beats[0].actions[0].tex == "x^{2}"


def test_apply_fixes_coerces_list_and_number_fields():
    spec = _spec([{"op": "add_axes", "id": "g", "x_range": [0, 1], "y_range": [0, 1]}])
    applied = apply_fixes(
        spec,
        [
            {"id": "g", "field": "x_range", "value": "[0, 5]"},
            {"id": "g", "field": "scale", "value": "0.5"},
        ],
    )
    assert applied
    action = spec.beats[0].actions[0]
    assert action.x_range == [0.0, 5.0]
    assert action.scale == 0.5


def test_apply_fixes_rejects_invalid_value():
    spec = _spec([{"op": "add_bars", "id": "bars", "values": [1, 2]}])
    applied = apply_fixes(spec, [{"id": "bars", "field": "values", "value": "not-a-list"}])
    assert applied is False
    assert spec.beats[0].actions[0].values == [1, 2]


def test_mathcheck_passes_through_when_no_spec(monkeypatch):
    from app.agents import scene_graph

    result = asyncio.run(scene_graph.mathcheck({"spec_json": None}))
    assert result == {"math_checked": True, "math_fixed": False}


def test_mathcheck_passes_through_clean_spec(monkeypatch):
    from app.agents import scene_graph
    from app.agents import math_expert

    spec = _spec([{"op": "add_equation", "id": "eq1", "tex": "x^{2}"}])

    async def no_fixes(*_args, **_kwargs):
        return []

    monkeypatch.setattr(math_expert, "math_review", no_fixes)
    state = {
        "spec_json": spec.model_dump_json(),
        "narration": "x squared equals x squared",
        "audio_duration": 10.0,
    }
    result = asyncio.run(scene_graph.mathcheck(state))
    assert result["math_checked"] is True
    assert result["math_fixed"] is False


def test_mathcheck_applies_fix_and_recompiles(monkeypatch):
    from app.agents import scene_graph
    from app.agents import math_expert

    spec = _spec(
        [
            {"op": "set_title", "text": "Squaring"},
            {"op": "add_axes", "id": "g", "expr": "x**", "x_range": [0, 1], "y_range": [0, 1]},
            {"op": "add_shape", "id": "d", "shape": "dot", "at": [0.5, 0.5]},
            {"op": "add_text", "id": "t", "text": "the curve", "region": "bottom"},
        ]
    )
    assert validate_math(spec)

    async def fake_review(_spec, _narration, _issues):
        return [{"id": "g", "field": "expr", "value": "x**2"}]

    monkeypatch.setattr(math_expert, "math_review", fake_review)
    state = {
        "scene_id": "scene-1",
        "spec_json": spec.model_dump_json(),
        "narration": "The curve x squared is shown.",
        "audio_duration": 10.0,
    }
    result = asyncio.run(scene_graph.mathcheck(state))
    assert result["math_fixed"] is True
    assert result["code"]
    assert result["spec_json"] != state["spec_json"]
    repaired = SceneSpec.model_validate_json(result["spec_json"])
    axes = next(a for a in repaired.beats[0].actions if a.id == "g")
    assert axes.expr == "x**2"
    assert validate_math(repaired) == []

"""Tests for cross-scene visual state extraction."""

import json

from app.schemas.spec import SceneSpec


def _make_spec(actions: list[dict]) -> str:
    spec = SceneSpec(
        title="Test",
        beats=[{"description": "beat", "actions": actions}],
    )
    return spec.model_dump_json()


def test_extract_visual_state_empty():
    from app.services.production_service import _extract_visual_state
    assert _extract_visual_state(None) == ""
    assert _extract_visual_state("invalid json") == ""


def test_extract_visual_state_with_objects():
    from app.services.production_service import _extract_visual_state
    spec_json = _make_spec([
        {"op": "add_shape", "id": "circle1", "shape": "circle", "color": "blue", "at": [-3.0, 0.0]},
        {"op": "add_axes", "id": "axes1", "x_range": [-3, 3, 1], "y_range": [-2, 2, 1], "region": "right"},
        {"op": "add_equation", "id": "eq1", "tex": "A = \\pi r^2", "color": "purple", "at": [0.0, -2.0]},
    ])
    state = _extract_visual_state(spec_json)
    assert "circle" in state
    assert "blue" in state
    assert "axes" in state
    assert "equation" in state
    assert "purple" in state
    assert "A = \\pi r^2" in state


def test_extract_visual_state_tracks_removals():
    from app.services.production_service import _extract_visual_state
    spec_json = _make_spec([
        {"op": "add_shape", "id": "c1", "shape": "circle", "color": "blue"},
        {"op": "add_shape", "id": "s1", "shape": "square", "color": "red"},
        {"op": "remove", "target": "c1"},
    ])
    state = _extract_visual_state(spec_json)
    assert "c1" not in state
    assert "s1" in state


def test_extract_visual_state_remove_all():
    from app.services.production_service import _extract_visual_state
    spec_json = _make_spec([
        {"op": "add_shape", "id": "c1", "shape": "circle", "color": "blue"},
        {"op": "remove", "target": "all"},
    ])
    state = _extract_visual_state(spec_json)
    assert "clean slate" in state


def test_extract_visual_state_transform():
    from app.services.production_service import _extract_visual_state
    spec_json = _make_spec([
        {"op": "add_text", "id": "label1", "text": "step 1"},
        {"op": "transform", "id": "label1", "tex": "A = \\pi r^2"},
    ])
    state = _extract_visual_state(spec_json)
    # transform updates tex; text is still present (from add_text)
    assert "A = \\pi r^2" in state
    assert "label1" in state


def test_extract_visual_state_position_tracking():
    from app.services.production_service import _extract_visual_state
    spec_json = _make_spec([
        {"op": "add_shape", "id": "d1", "shape": "dot", "color": "red", "at": [-3.0, 1.5]},
        {"op": "add_shape", "id": "d2", "shape": "dot", "color": "green", "region": "right"},
    ])
    state = _extract_visual_state(spec_json)
    assert "(-3.0, 1.5)" in state
    assert "in right" in state


def test_extract_visual_state_expr_tracking():
    from app.services.production_service import _extract_visual_state
    spec_json = _make_spec([
        {"op": "add_axes", "id": "g", "x_range": [0, 6, 1], "y_range": [-1, 1, 1], "expr": "sin(x)"},
    ])
    state = _extract_visual_state(spec_json)
    assert "sin(x)" in state


def test_continuity_context_with_spec():
    """Test the full _continuity_context with a mock Scene."""
    from app.services.production_service import _continuity_context

    class FakeScene:
        idx = 0
        title = "The Ring"
        spec_json = _make_spec([
            {"op": "add_shape", "id": "ring", "shape": "ring", "color": "orange", "at": [-3.0, 0.0]},
            {"op": "add_axes", "id": "axes", "x_range": [-3, 3, 1], "y_range": [-2, 2, 1], "at": [3.0, 0.0]},
        ])
        visual_description = None

    ctx = _continuity_context(FakeScene())
    assert "Scene 1 (The Ring)" in ctx
    assert "ring" in ctx
    assert "orange" in ctx
    assert "axes" in ctx

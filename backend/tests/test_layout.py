"""Tests for the SceneLayout schema and spatial planning integration."""

from app.schemas.spec import LayoutRegion, SceneLayout, SceneSpec


def test_layout_region_minimal():
    r = LayoutRegion(name="left_area", area="left")
    assert r.name == "left_area"
    assert r.area == "left"
    assert r.description == ""
    assert r.at is None


def test_layout_region_with_coordinates():
    r = LayoutRegion(name="sine_plot", area="right", description="sine wave axes", at=[3.4, 0.0])
    assert r.at == [3.4, 0.0]


def test_scene_layout_side_by_side():
    layout = SceneLayout(
        regions=[
            LayoutRegion(name="circle_area", area="left", at=[-3.4, 0.0]),
            LayoutRegion(name="sine_area", area="right", at=[3.4, 0.0]),
        ],
        notes="Both share vertical scale",
    )
    assert len(layout.regions) == 2
    assert layout.notes == "Both share vertical scale"


def test_scene_spec_optional_layout():
    spec = SceneSpec(
        title="Test",
        layout=SceneLayout(regions=[LayoutRegion(name="main", area="center")]),
        beats=[{"description": "beat 1", "actions": [{"op": "set_title", "text": "T"}]}],
    )
    assert spec.layout is not None
    assert len(spec.layout.regions) == 1


def test_scene_spec_no_layout():
    spec = SceneSpec(
        title="Test",
        beats=[{"description": "beat 1", "actions": [{"op": "set_title", "text": "T"}]}],
    )
    assert spec.layout is None


def test_compiler_respects_explicit_at_coordinates():
    """When an action has at:[x,y], the compiler uses those exact coordinates."""
    from app.pipeline.spec_compiler import compile_spec

    spec = SceneSpec(
        title="Explicit coords",
        layout=SceneLayout(
            regions=[
                LayoutRegion(name="left_area", area="left", at=[-3.4, 0.0]),
                LayoutRegion(name="right_area", area="right", at=[3.4, 0.0]),
            ]
        ),
        beats=[
            {
                "description": "Side by side elements",
                "actions": [
                    {"op": "set_title", "text": "Side by Side"},
                    {
                        "op": "add_shape", "id": "dot1", "shape": "dot",
                        "color": "blue", "at": [-3.0, 0.0],
                    },
                    {
                        "op": "add_shape", "id": "dot2", "shape": "dot",
                        "color": "red", "at": [3.0, 0.0],
                    },
                    {
                        "op": "add_text", "id": "label1", "text": "Left",
                        "at": [-3.0, -1.5],
                    },
                    {
                        "op": "add_text", "id": "label2", "text": "Right",
                        "at": [3.0, -1.5],
                    },
                ],
            }
        ],
    )
    code = compile_spec(spec, 10.0)
    assert "move_to([-3.00, 0.00, 0])" in code
    assert "move_to([3.00, 0.00, 0])" in code
    assert "move_to([-3.00, -1.50, 0])" in code
    assert "move_to([3.00, -1.50, 0])" in code


def test_compiler_uses_explicit_at_over_region_slot():
    """When both region and at are provided, at wins."""
    from app.pipeline.spec_compiler import compile_spec

    spec = SceneSpec(
        title="At wins",
        beats=[
            {
                "description": "At takes priority",
                "actions": [
                    {"op": "set_title", "text": "At Priority"},
                    {
                        "op": "add_shape", "id": "s1", "shape": "circle",
                        "color": "green", "region": "center", "at": [5.0, 1.0],
                    },
                    {"op": "add_text", "id": "t1", "text": "label", "at": [-5.0, 0.0]},
                    {"op": "add_text", "id": "t2", "text": "other", "at": [0.0, -2.0]},
                ],
            }
        ],
    )
    code = compile_spec(spec, 10.0)
    assert "move_to([5.00, 1.00, 0])" in code
    assert "move_to([-5.00, 0.00, 0])" in code
    assert "move_to([0.00, -2.00, 0])" in code


def test_compiler_multi_element_side_by_side():
    """Multiple elements with explicit at coords render correctly."""
    from app.pipeline.spec_compiler import compile_spec

    spec = SceneSpec(
        title="Sine and Circle",
        layout=SceneLayout(
            regions=[
                LayoutRegion(name="circle_area", area="left", at=[-3.4, 0.0]),
                LayoutRegion(name="sine_area", area="right", at=[3.4, 0.0]),
            ]
        ),
        beats=[
            {
                "description": "Circle and sine side by side",
                "actions": [
                    {"op": "set_title", "text": "Sine + Circle"},
                    {
                        "op": "add_axes", "id": "circle_axes",
                        "x_range": [-1.5, 1.5, 0.5], "y_range": [-1.5, 1.5, 0.5],
                        "at": [-3.4, 0.0], "color": "white",
                    },
                    {
                        "op": "add_axes", "id": "sine_axes",
                        "x_range": [0, 6.28, 1.57], "y_range": [-1.5, 1.5, 0.5],
                        "at": [3.4, 0.0], "color": "blue",
                        "expr": "sin(x)",
                    },
                    {
                        "op": "add_shape", "id": "dot", "shape": "dot",
                        "color": "red", "at": [-3.4, 0.0],
                    },
                    {"op": "label", "id": "lbl", "text": "θ", "target": "dot", "direction": "up"},
                ],
            }
        ],
    )
    code = compile_spec(spec, 15.0)
    assert "move_to([-3.40, 0.00, 0])" in code
    assert "move_to([3.40, 0.00, 0])" in code
    assert "sin(x)" in code
    assert "mathcheck" not in code  # this is spec compiler, not graph

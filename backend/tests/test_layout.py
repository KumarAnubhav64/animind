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


def _spec_with_regions(title, actions):
    return SceneSpec(
        title=title,
        layout=SceneLayout(
            regions=[
                LayoutRegion(name="left_area", area="left", at=[-3.4, 0.0]),
                LayoutRegion(name="right_area", area="right", at=[3.4, 0.0]),
                LayoutRegion(name="center_area", area="center", at=[0.0, 0.0]),
            ]
        ),
        beats=[{"description": "action beat", "actions": actions}],
    )


def test_compiler_places_named_region_at_its_layout_coordinates():
    """Actions referencing a layout region BY NAME land at that region's at anchor,
    not the REGIONS center fallback (the overlap bug this guards against)."""
    from app.pipeline.spec_compiler import compile_spec

    spec = _spec_with_regions(
        "Named regions",
        [
            {"op": "set_title", "text": "Named regions"},
            {"op": "add_shape", "id": "hero_l", "shape": "circle", "color": "red", "region": "left_area"},
            {"op": "add_shape", "id": "hero_r", "shape": "circle", "color": "blue", "region": "right_area"},
            {"op": "add_shape", "id": "hero_c", "shape": "circle", "color": "green", "region": "center_area"},
        ],
    )
    code = compile_spec(spec, 12.0)
    assert "m_hero_l.move_to([-3.40, 0.00, 0])" in code
    assert "m_hero_r.move_to([3.40, 0.00, 0])" in code
    assert "m_hero_c.move_to([0.00, 0.00, 0])" in code


def test_compiler_named_region_fill_uses_region_box_not_center_band():
    """Region-placed (no at) shapes size to the referenced region's box extents
    (left/right are 4.75x3.45), proving the layout box drives the fit, not the
    whole-band center default (5.55x3.05)."""
    from app.pipeline.spec_compiler import compile_spec

    spec = _spec_with_regions(
        "Fill per region",
        [
            {"op": "set_title", "text": "Fill per region"},
            {"op": "add_shape", "id": "hero_l", "shape": "circle", "color": "red", "region": "left_area"},
            {"op": "add_shape", "id": "hero_r", "shape": "circle", "color": "blue", "region": "right_area"},
            {"op": "add_shape", "id": "hero_c", "shape": "circle", "color": "green", "region": "center_area"},
        ],
    )
    code = compile_spec(spec, 8.0)
    assert "_fit(m_hero_l, 4.75, 3.45, True)" in code
    assert "m_hero_l.move_to([-3.40, 0.00, 0])" in code


def test_compiler_area_keyword_still_resolves_without_layout_region():
    """Bare area words (left/center/...) keep working when no layout names match."""
    from app.pipeline.spec_compiler import compile_spec

    spec = SceneSpec(
        title="Bare area",
        beats=[
            {
                "description": "Area keywords",
                "actions": [
                    {"op": "set_title", "text": "Areas"},
                    {"op": "add_shape", "id": "left_obj", "shape": "square", "color": "red", "region": "left"},
                    {"op": "add_shape", "id": "right_obj", "shape": "square", "color": "blue", "region": "right"},
                    {"op": "add_shape", "id": "center_obj", "shape": "circle", "color": "green", "region": "center"},
                ],
            }
        ],
    )
    code = compile_spec(spec, 8.0)
    assert "m_left_obj.move_to([-3.40, -0.40, 0])" in code
    assert "m_right_obj.move_to([3.40, -0.40, 0])" in code


def test_derive_layout_injects_regions_when_spec_has_none():
    from app.pipeline.spec_compiler import compile_spec, derive_layout

    spec = SceneSpec(
        title="No layout",
        beats=[
            {
                "description": "Content placed across areas",
                "actions": [
                    {"op": "set_title", "text": "Derived"},
                    {"op": "add_shape", "id": "a", "shape": "circle", "color": "red", "region": "left"},
                    {"op": "add_shape", "id": "b", "shape": "circle", "color": "blue", "region": "right"},
                    {"op": "add_text", "id": "c", "text": "center note", "region": "center"},
                ],
            }
        ],
    )
    assert spec.layout is None
    derived = derive_layout(spec)
    assert derived is not spec
    assert derived.layout is not None
    names = {r.name for r in derived.layout.regions}
    assert names == {"left", "right", "center"}
    by_name = {r.name: r for r in derived.layout.regions}
    assert by_name["left"].at == [-3.4, -0.4]
    assert by_name["right"].at == [3.4, -0.4]
    # deterministic: calling again yields an identical layout
    again = derive_layout(derived)
    assert again.layout.model_dump() == derived.layout.model_dump()
    # and compilation output is untouched by the derived layout
    assert compile_spec(derived) == compile_spec(spec)


def test_derive_layout_groups_by_proximity_to_region_anchor():
    """Explicit at coords bucket objects into the area whose anchor is nearest,
    and custom region keywords resolve to their matching area."""
    from app.pipeline.spec_compiler import compile_spec, derive_layout

    spec = SceneSpec(
        title="Pictograph",
        beats=[
            {
                "description": "Two groups",
                "actions": [
                    {"op": "set_title", "text": "Pictograph"},
                    {"op": "add_text", "id": "sun", "text": "☀", "region": "left_area", "at": [-3.0, 0.0]},
                    {"op": "add_text", "id": "tree", "text": "🌳", "region": "right_area", "at": [3.0, 0.0]},
                    {"op": "add_text", "id": "cap", "text": "caption", "at": [0.0, -2.4]},
                ],
            }
        ],
    )
    derived = derive_layout(spec)
    names = {r.name for r in derived.layout.regions}
    assert names == {"left_area", "right_area", "bottom_area"}
    by_name = {r.name: r for r in derived.layout.regions}
    assert by_name["left_area"].area == "left"
    assert by_name["right_area"].area == "right"
    assert "cap" in by_name["bottom_area"].description
    assert compile_spec(derived) == compile_spec(spec)


def test_derive_layout_keeps_existing_layout_untouched():
    from app.pipeline.spec_compiler import derive_layout

    spec = SceneSpec(
        title="Has layout",
        layout=SceneLayout(
            regions=[LayoutRegion(name="custom", area="left", at=[-2.0, 1.0], description="hand tuned")]
        ),
        beats=[{"description": "b", "actions": [{"op": "set_title", "text": "T"}]}],
    )
    assert derive_layout(spec) is spec  # returned unchanged when regions exist

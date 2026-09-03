import ast
import asyncio
from pathlib import Path

import pytest

from app.agents import scene_graph
from app.agents.example_memory import CARDS, lookup_example
from app.pipeline.renderer import normalize_manim_code, render_manim, validate_visual_code


def test_card_code_blocks_are_valid_python():
    for card in CARDS:
        assert card.code.strip(), card.slug
        ast.parse(card.code)


def test_cards_have_unique_slugs_and_required_fields():
    slugs = [card.slug for card in CARDS]
    assert len(slugs) == len(set(slugs))
    assert len(CARDS) >= 8
    for card in CARDS:
        assert card.heading
        assert card.keywords
        assert card.apis
        assert card.lesson
        assert card.render().startswith(f"# {card.heading}")


def test_lookup_returns_sine_card_for_orbiting_dot_narration():
    block = lookup_example(
        "Sum of Simple Sines",
        "Watch the dot orbit the unit circle and trace out a sine wave.",
        "A red dot spins around a blue circle while a green dashed line marks its height on the axes.",
    )
    assert block is not None
    assert "Orbiting dot draws a sine wave" in block
    assert "```python" in block
    assert "class VideoScene" in block


def test_lookup_returns_area_card_for_riemann_narration():
    block = lookup_example(
        "Definite integrals",
        "Approximate the area under the curve with thin rectangles, then fill it in.",
        "Bars under a parabola that turn into a shaded region.",
    )
    assert block is not None
    assert "Riemann rectangles" in block


def test_lookup_matches_on_renderer_error_for_fixer():
    block = lookup_example(
        "Title", "Some narration about angles.", "", "NameError: name 'Angle' is not defined"
    )
    assert block is not None
    assert "rotating-angle" in block or "The Angle Between Them" in block


def test_lookup_returns_none_when_nothing_scores():
    assert lookup_example("quantum chromodynamics lattice gauge theory") is None
    assert lookup_example("") is None


def test_lookup_respects_max_entries():
    block = lookup_example(
        "Draw a circle, move a dot around it, then slide the dot along a parabola to its minimum",
        max_entries=2,
    )
    assert block is not None
    assert block.count("Lesson:") == 2


def test_card_blocks_render_distinctly():
    assert lookup_example("angle between two lines theta") != lookup_example("dot orbiting sine wave trace")


def test_follow_camera_card_upgrades_to_moving_camera_scene():
    card = next(c for c in CARDS if c.slug == "follow-camera")
    assert "class VideoScene(Scene):" in card.code
    assert "self.camera.frame" in card.code
    fixed = normalize_manim_code(card.code)
    assert "class VideoScene(MovingCameraScene):" in fixed
    assert validate_visual_code(fixed) is None


def test_all_cards_pass_visual_validation_after_normalization():
    for card in CARDS:
        fixed = normalize_manim_code(card.code)
        err = validate_visual_code(fixed)
        assert err is None, f"{card.slug}: {err}"


@pytest.mark.parametrize("slug", [card.slug for card in CARDS])
def test_every_card_renders_to_video(tmp_path: Path, slug: str):
    card = next(c for c in CARDS if c.slug == slug)
    ok, error, video = asyncio.run(
        render_manim(normalize_manim_code(card.code), tmp_path / "scene", tmp_path / "scene" / "render")
    )
    assert ok, f"{slug}: {error}"
    assert video is not None
    assert Path(video).stat().st_size > 0


def test_example_block_survives_fit_to_budget_middle_cut():
    from app.agents.llm import _fit_to_budget

    block = lookup_example("Watch the dot orbit and trace out a sine wave")
    assert block is not None
    system = "You are an expert Manim animator.\n" * 20
    long_body = "Narration and visual description content here. " * 120
    human = f"{long_body}\n\n{block}"
    trimmed = _fit_to_budget([("system", system), ("human", human)], max_tokens=2048, max_input_tokens=1500)
    assert "REFERENCE EXAMPLE" in trimmed[-1][1]
    assert "```python" in trimmed[-1][1]


def test_fixer_injects_example_memory_into_human_turn(monkeypatch):
    captured: dict = {}

    class Response:
        content = (
            "```python\nfrom manim import *\nclass VideoScene(Scene):\n"
            "    def construct(self):\n"
            '        t = Text("ok")\n'
            "        self.play(Write(t, run_time=2))\n"
            "        self.wait(1)\n"
            "```\n"
        )

    async def invoke(_llm, messages, project_id=None):
        captured["messages"] = messages
        return Response()

    monkeypatch.setattr(scene_graph, "llm_with_retry", invoke)
    state = {
        "attempts": 1,
        "scene_id": "scene-1",
        "title": "A dot orbiting a circle drawing a sine",
        "narration": "Watch the dot orbit and leave a sine trace.",
        "visual_description": "Orbiting dot with a dashed projection and growing curve.",
        "code": "from manim import *\nclass VideoScene(Scene):\n    def construct(self):\n        pass\n",
        "error": "some error",
        "context": "",
    }
    result = asyncio.run(scene_graph.fix_code(state))
    assert result["attempts"] == 2
    human = captured["messages"][-1][1]
    assert "REFERENCE EXAMPLE" in human
    assert human.rstrip().endswith("```")
    assert "Orbiting dot draws a sine wave" in human

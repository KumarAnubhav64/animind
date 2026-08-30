import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.scene_graph import after_critique, llm_with_retry
from app.pipeline.frames import extract_frames
from app.pipeline.renderer import (
    detect_invalid_manim_patterns,
    normalize_manim_code,
    preflight_visual_code,
    render_manim,
)
from app.pipeline.spec_compiler import compile_spec
from app.pipeline.treatment import _layout_diagram
from app.prompts.coder import coder_user_prompt
from app.prompts.fixer import fixer_user_prompt
from app.schemas import extract_python_code
from app.schemas.spec import LayoutRegion, SceneLayout, SceneSpec, SpecAction, SpecBeat
from app.services import production_service


def test_renderer_rejects_empty_code_and_removes_stale_video(tmp_path: Path):
    work = tmp_path / "scene"
    work.mkdir()
    stale = work / "scene.mp4"
    stale.write_bytes(b"old render")

    ok, error, video = asyncio.run(render_manim("", work, work / "render"))

    assert not ok
    assert error == "Generated Manim code is empty"
    assert video is None
    assert not stale.exists()
    assert (work / "scene.py").read_text() == ""


def test_renderer_normalizes_legacy_line_updater_method():
    assert normalize_manim_code("line.set_start_and_end_points(a, b)") == "line.put_start_and_end_on(a, b)"


def test_renderer_normalizes_numpy_direction_rotation_and_rejects_placeholder():
    assert normalize_manim_code("2 * UP.rotate(angle)") == "2 * rotate_vector(UP, angle)"
    ok, error, video = asyncio.run(
        render_manim(
            'from manim import *\nclass VideoScene(Scene):\n    def construct(self):\n        self.play(Write(Text("Hello, World!")))',
            Path("/tmp/opencode/placeholder-scene"),
            Path("/tmp/opencode/placeholder-scene/render"),
        )
    )
    assert not ok
    assert "placeholder" in error
    assert video is None


def test_preflight_rejects_repeated_untransformed_triangles():
    assert "transformation" in (preflight_visual_code("Circle()\n" + "Triangle()\n" * 4) or "")


def test_preflight_rejects_malformed_syntax():
    err = preflight_visual_code("self.play(Write(Text('hi'))")
    assert err is not None
    assert "invalid Python syntax" in err
    assert preflight_visual_code("x = 1\nself.play(FadeIn(x), run_time=2)") is None


def test_extract_python_code_strips_tool_call_scaffolding():
    raw = (
        "I'll analyze the requirements first.\n"
        "<tool_call>\n"
        "<function=WebSearch><parameter name=\"query\">manim get_area</parameter></function>\n"
        "</tool_call>\n"
        "```python\n"
        "from manim import *\n"
        "class VideoScene(Scene):\n"
        "    def construct(self):\n"
        "        self.play(Write(Text('hi')))\n"
        "```\n"
    )
    code = extract_python_code(raw)
    assert "tool_call" not in code
    assert "WebSearch" not in code
    assert "class VideoScene" in code


def test_extract_python_code_strips_scaffolding_without_fences():
    raw = (
        "<tool_call><function=WebSearch>query</function></tool_call>\n"
        "from manim import *\nclass VideoScene(Scene):\n"
        "    def construct(self):\n"
        "        pass\n"
    )
    code = extract_python_code(raw)
    assert "tool_call" not in code
    assert "WebSearch" not in code
    assert code.startswith("from manim")


def test_validate_visual_code_rejects_get_area_with_raw_function():
    from app.pipeline.renderer import validate_visual_code

    err = validate_visual_code(
        "from manim import *\n"
        "class VideoScene(Scene):\n"
        "    def construct(self):\n"
        "        axes = Axes()\n"
        "        area = axes.get_area(lambda x: x, x_range=[0, 4])\n"
        "        self.add(area)\n"
    )
    assert err is not None
    assert "get_area" in err


def test_validate_visual_code_rejects_get_area_with_lambda_in_x_range():
    from app.pipeline.renderer import validate_visual_code

    err = validate_visual_code(
        "from manim import *\n"
        "class VideoScene(Scene):\n"
        "    def construct(self):\n"
        "        axes = Axes()\n"
        "        area = axes.get_area(complex_signal, lambda x: 0)\n"
        "        self.add(area)\n"
    )
    assert err is not None
    assert "x_range" in err


def test_validate_visual_code_accepts_plotted_get_area():
    from app.pipeline.renderer import validate_visual_code

    err = validate_visual_code(
        "from manim import *\n"
        "class VideoScene(Scene):\n"
        "    def construct(self):\n"
        "        axes = Axes()\n"
        "        graph = axes.plot(lambda x: x)\n"
        "        area = axes.get_area(graph, x_range=[0, 4])\n"
        "        self.add(area)\n"
    )
    assert err is None


def test_validate_visual_code_rejects_missing_video_scene_class():
    from app.pipeline.renderer import validate_visual_code

    err = validate_visual_code(
        "from manim import *\n"
        "class NotAVideo(Scene):\n"
        "    def construct(self):\n"
        "        self.play(Write(Text('hi')))\n"
    )
    assert err is not None
    assert "does not define VideoScene" in err


def test_validate_visual_code_rejects_opacity_zero_then_fade_in():
    from app.pipeline.renderer import validate_visual_code

    err = validate_visual_code(
        "from manim import *\n"
        "class VideoScene(Scene):\n"
        "    def construct(self):\n"
        "        curve = axes.plot(lambda x: x).set_opacity(0)\n"
        "        self.play(FadeIn(curve, run_time=3))\n"
    )
    assert err is not None
    assert "stays invisible" in err


def test_validate_visual_code_accepts_healthy_scene():
    from app.pipeline.renderer import validate_visual_code

    err = validate_visual_code(
        "from manim import *\n"
        "class VideoScene(Scene):\n"
        "    def construct(self):\n"
        "        t = Text('hi', font_size=40)\n"
        "        self.play(Write(t, run_time=2))\n"
        "        self.wait(1)\n"
    )
    assert err is None


def test_detect_invalid_manim_patterns_rejects_animation_multiplied_by_int():
    import ast

    tree = ast.parse(
        'from manim import *\n'
        'class VideoScene(Scene):\n'
        '    def construct(self):\n'
        '        t = Text("hi")\n'
        '        self.play(2 * Write(t))\n'
    )
    err = detect_invalid_manim_patterns(tree)
    assert err is not None
    assert "multiplied by a number" in err
    assert "run_time" in err


def test_detect_invalid_manim_patterns_rejects_run_time_on_mobject_method():
    import ast

    tree = ast.parse(
        'from manim import *\n'
        'class VideoScene(Scene):\n'
        '    def construct(self):\n'
        '        c = Circle()\n'
        '        c.move_to(UP, run_time=2)\n'
        '        self.play(Create(c))\n'
    )
    err = detect_invalid_manim_patterns(tree)
    assert err is not None
    assert "run_time" in err


def test_detect_invalid_manim_patterns_accepts_valid_usage():
    import ast

    tree = ast.parse(
        'from manim import *\n'
        'import numpy as np\n'
        'class VideoScene(Scene):\n'
        '    def construct(self):\n'
        '        radius = 2.0\n'
        '        p = np.array([0, 1, 0]) * radius\n'
        '        t = Text("x", font_size=36)\n'
        '        self.play(Write(t, run_time=2), Create(Circle()), run_time=3)\n'
        '        self.play(t.animate.shift(UP * 2), run_time=2)\n'
        '        self.wait(1)\n'
    )
    assert detect_invalid_manim_patterns(tree) is None


def test_layout_diagram_handles_region_models():
    spec = SceneSpec(
        title="t",
        layout=SceneLayout(
            regions=[
                LayoutRegion(name="sine_plot", area="center", description="red sine"),
                LayoutRegion(name="labels", area="top", description="labels"),
            ]
        ),
        beats=[SpecBeat(description="x", actions=[])],
    )
    diagram = _layout_diagram(spec)
    assert "sine_plot" in diagram
    assert "center" in diagram
    assert "labels" in diagram


def _curve_spec() -> SceneSpec:
    return SceneSpec(
        title="Sum of Simple Sines",
        beats=[
            SpecBeat(description="title", actions=[SpecAction(op="set_title", text="Sum of Simple Sines")]),
            SpecBeat(
                description="sum curve",
                actions=[
                    SpecAction(op="add_axes", id="main_axes", x_range=[-7, 7, 1], y_range=[-2, 2, 0.5], at=[0, 0]),
                    SpecAction(op="add_curve", id="purple_wave", expr="sin(x) + 0.5*sin(2*x) + 0.33*sin(3*x)", target="main_axes", color="purple"),
                ],
            ),
            SpecBeat(
                description="three stacked sines",
                actions=[
                    SpecAction(op="remove", target="purple_wave"),
                    SpecAction(op="add_curve", id="sine1", expr="sin(x)", target="main_axes", color="blue", offset=1.4),
                    SpecAction(op="add_curve", id="sine2", expr="sin(x)", target="main_axes", color="blue"),
                    SpecAction(op="add_curve", id="sine3", expr="sin(x)", target="main_axes", color="blue", offset=-1.4),
                ],
            ),
        ],
    )


def test_add_curve_plots_all_curves_on_one_axes():
    spec = _curve_spec()
    assert spec.validate_ids() == []
    code = compile_spec(spec)
    ast.parse(code)
    assert code.count("= Axes(") == 1
    assert code.count(".plot(lambda x:") == 4
    assert "(sin(x)) - 1.40" in code
    assert "= Axes(" not in code.replace("m_main_axes = Axes(", "")


def test_add_curve_renders_to_video(tmp_path: Path):
    code = compile_spec(_curve_spec())
    ok, error, video = asyncio.run(render_manim(code, tmp_path / "scene", tmp_path / "scene" / "render"))
    assert ok, error
    assert video is not None
    assert Path(video).stat().st_size > 0


def test_validate_ids_rejects_add_curve_without_target():
    spec = SceneSpec(
        title="t",
        beats=[SpecBeat(description="x", actions=[SpecAction(op="add_curve", id="c", expr="sin(x)")])],
    )
    issues = spec.validate_ids()
    assert any("missing 'target'" in issue for issue in issues)


def test_fixer_candidate_requests_fresh_codegen(monkeypatch):
    from app.agents import scene_graph

    class Response:
        content = "Hello, World!"

    async def invoke(_llm, _messages, project_id=None):
        return Response()

    monkeypatch.setattr(scene_graph, "llm_with_retry", invoke)
    async def fresh_codegen(_state, feedback=""):
        assert "visual QA rejected" in feedback
        return {"code": "fresh code", "attempts": 2, "spec_json": None, "status": "rendering"}

    monkeypatch.setattr(scene_graph, "generate_code", fresh_codegen)
    state = {
        "attempts": 1,
        "scene_id": "scene-1",
        "title": "Test scene",
        "narration": "Explain the test.",
        "visual_description": "Show the test.",
        "code": "from manim import *\nclass VideoScene(Scene):\n    def construct(self):\n        self.play(Write(Text('keep me')))\n",
        "error": "visual QA rejected",
        "context": "",
    }
    result = asyncio.run(scene_graph.fix_code(state))
    assert result["code"] == "fresh code"
    assert result["attempts"] == 2


def test_renderer_rejects_construct_without_scene_output(tmp_path: Path):
    code = """\
from manim import *

class VideoScene(Scene):
    def construct(self):
        title = Text("Never added")
"""
    ok, error, video = asyncio.run(
        render_manim(code, tmp_path / "scene", tmp_path / "scene" / "render")
    )

    assert not ok
    assert error == "VideoScene.construct contains no animation or mobject"
    assert video is None


def test_renderer_rejects_wait_only_scene(tmp_path: Path):
    code = """\
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.wait(2)
"""
    ok, error, video = asyncio.run(
        render_manim(code, tmp_path / "scene", tmp_path / "scene" / "render")
    )

    assert not ok
    assert error == "VideoScene.construct contains no animation or mobject"
    assert video is None


def test_compiler_rejects_title_only_spec():
    spec = SceneSpec(
        title="Empty explanation",
        beats=[
            {
                "description": "Only a title",
                "actions": [{"op": "set_title", "text": "Empty explanation"}],
            }
        ],
    )

    with pytest.raises(ValueError, match="underspecified"):
        compile_spec(spec)


def test_compiler_fits_axes_labels_and_long_title():
    spec = SceneSpec(
        title="Frequency, period, and unwrapping a circular motion into a sine wave",
        beats=[
            {
                "description": "Build the complete relationship",
                "actions": [
                    {"op": "add_shape", "id": "circle", "shape": "circle", "region": "left"},
                    {"op": "add_shape", "id": "dot", "shape": "dot", "region": "left"},
                    {
                        "op": "add_axes",
                        "id": "graph",
                        "region": "right",
                        "x_range": [-3, 3, 1],
                        "y_range": [-1, 1, 1],
                        "expr": "sin(x)",
                    },
                    {"op": "label", "id": "wave", "text": "sine wave", "target": "graph"},
                ],
            }
        ],
    )

    code = compile_spec(spec)

    assert "x_length=4.75, y_length=3.45" in code
    assert "_fit(title, 11.0, 0.72)" in code
    assert "m_wave.next_to(m_graph, DOWN" in code
    assert "_keep_in_frame(m_wave)" in code


def test_raw_and_fixer_prompts_include_continuity():
    context = "Scene 1: red circle represents the pathogen"

    assert context in coder_user_prompt("Next", "Narration", "Visual", 10, context)
    assert context in fixer_user_prompt("code", "visual QA failed", 2, context)


def test_vision_qa_second_rejection_routes_to_failure():
    assert after_critique({"qa_exhausted": False, "error": "visual QA rejected"}) == "fix"
    assert after_critique({"qa_exhausted": True, "error": "visual QA rejected"}) == "fail"
    assert after_critique({"qa_exhausted": False, "error": None}) == "accept"


def test_scene_graph_contains_qa_failure_route():
    from app.agents.scene_graph import SCENE_GRAPH

    routes = SCENE_GRAPH.get_graph().edges
    assert any(edge.source == "critique" and edge.target == "fail" for edge in routes)


def test_daily_token_cap_uses_fallback_once(monkeypatch):
    class DailyCappedLLM:
        calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            raise RuntimeError("Rate limit reached on tokens per day (TPD)")

    class FallbackLLM:
        calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return "fallback result"

    llm = DailyCappedLLM()
    fallback = FallbackLLM()
    monkeypatch.setattr("app.agents.scene_graph.fallback_llm", lambda: fallback)
    result = asyncio.run(
        llm_with_retry(llm, [("human", "test")], attempts=4, wait_s=0)
    )
    assert result == "fallback result"
    assert llm.calls == 1
    assert fallback.calls == 1


def test_restitch_requires_every_scene(monkeypatch, tmp_path: Path):
    ready_video = tmp_path / "scene.mp4"
    ready_video.write_bytes(b"video")
    scenes = [
        SimpleNamespace(
            status="ready", video_path=str(ready_video), manim_code="class VideoScene: pass"
        ),
        SimpleNamespace(status="failed", video_path=None, manim_code=None),
    ]
    monkeypatch.setattr(production_service.scene_repo, "list_for_project", lambda _id: scenes)

    with pytest.raises(RuntimeError, match="every scene is ready"):
        asyncio.run(production_service.restitch("project"))


def test_frame_extraction_keeps_three_downscaled_images(tmp_path: Path):
    from moviepy import ColorClip

    video = tmp_path / "source.mp4"
    clip = ColorClip(size=(1280, 720), color=(20, 30, 40), duration=1.0)
    clip.write_videofile(str(video), codec="libx264", fps=12, logger=None)
    clip.close()

    frames = asyncio.run(extract_frames(video, count=3, width=480, out_dir=tmp_path / "frames"))

    assert len(frames) == 3
    from PIL import Image

    assert [Image.open(frame).size for frame in frames] == [(480, 270)] * 3


def test_fit_to_budget_trims_only_when_over_and_keeps_head_tail():
    from app.agents.llm import _fit_to_budget

    system = "sys" * 1000
    body = "Narration and visual description content. " * 200
    human = f"head {body} tail"
    messages = [("system", system), ("human", human)]

    # Fits fine: untouched.
    assert _fit_to_budget(messages, max_tokens=2048, max_input_tokens=10_000) == messages

    # Exceeds the ceiling: human turn is trimmed, head/tail markers survive,
    # and the estimated input+max_tokens fits under Groq's 8000 cap.
    trimmed = _fit_to_budget([("system", system), ("human", human)], max_tokens=2048, max_input_tokens=2048)
    assert trimmed != messages
    human_t = trimmed[-1][1]
    assert "head" in human_t and "tail" in human_t
    assert "[content trimmed to fit token budget]" in human_t
    assert len(human_t) < len(human)

    # System turns are never trimmed away.
    assert trimmed[0][0] == "system"
    assert trimmed[0][1] == system


def test_fit_to_budget_estimates_tokens_without_tiktoken():
    from app.agents.llm import _estimate_tokens

    assert _estimate_tokens("") == 0
    assert _estimate_tokens("hello world") > 0

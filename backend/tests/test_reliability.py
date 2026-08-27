import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.scene_graph import after_critique, llm_with_retry
from app.pipeline.frames import extract_frames
from app.pipeline.renderer import normalize_manim_code, preflight_visual_code, render_manim
from app.pipeline.spec_compiler import compile_spec
from app.prompts.coder import coder_user_prompt
from app.prompts.fixer import fixer_user_prompt
from app.schemas.spec import SceneSpec
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
    assert "_fit(title, 13.0, 0.72)" in code
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

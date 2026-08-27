"""Pipeline smoke test without any LLM: hardcoded scene -> render -> merge -> stitch."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.pipeline.renderer import render_manim
from app.pipeline.video import merge_audio_video, stitch_scenes

SCENE = """
from manim import *

class VideoScene(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c1c"
        title = Text("AniMind Test", font_size=44).to_edge(UP, buff=0.4)
        circle = Circle(radius=1.5, color=BLUE)
        label = Text("scene {n}", font_size=32).next_to(circle, DOWN)
        self.play(Write(title))
        self.play(Create(circle))
        self.play(FadeIn(label))
        self.play(Rotate(circle, angle=TAU / 4), run_time=2)
        self.wait(2)
"""


async def make_wav(path: Path, seconds: float):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={seconds}",
        str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def main():
    base = Path("/tmp/opencode/animind_smoke")
    if base.exists():
        import shutil; shutil.rmtree(base)

    scene_paths = []
    for n in (1, 2):
        work = base / f"proj/scenes/s{n}"
        ok, err, video = await render_manim(SCENE.format(n=n), work, work / "render")
        assert ok, f"render failed for scene {n}:\n{err[-1500:]}"
        print(f"scene {n}: rendered -> {video}")

        wav = work / "audio.wav"
        await make_wav(wav, 6.0)
        out = work / "scene_final.mp4"
        dur = await merge_audio_video(video, str(wav), out)
        print(f"scene {n}: merged, duration={dur:.1f}s")
        assert abs(dur - 6.0) < 1.0
        scene_paths.append(str(out))

    final = base / "proj/final_video.mp4"
    total = await stitch_scenes(scene_paths, final)
    print(f"stitched final: {total:.1f}s -> {final}")
    assert final.stat().st_size > 10_000
    print("SMOKE TEST PASSED")


asyncio.run(main())

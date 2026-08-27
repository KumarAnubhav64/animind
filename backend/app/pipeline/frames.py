"""Frame extraction for visual critique. Downscaled aggressively: the critic
only needs composition/overlap signals, not pixels."""

import asyncio
import tempfile
from pathlib import Path


async def extract_frames(
    video_path: str | Path,
    count: int = 3,
    width: int = 480,
    out_dir: str | Path | None = None,
) -> list[Path]:
    """Grab `count` evenly-spaced frames, scaled to `width` px JPEGs."""
    video_path = Path(video_path)
    out_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="frames_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    from moviepy import VideoFileClip

    def _extract() -> list[Path]:
        clip = VideoFileClip(str(video_path))
        try:
            duration = clip.duration or 0
            paths: list[Path] = []
            if count <= 1:
                sample_times = [duration * 0.5]
            else:
                # Sample the opening, middle, and closing composition so QA
                # can judge the visual payoff without increasing frame count.
                sample_times = [
                    duration * (0.05 + 0.9 * i / (count - 1))
                    for i in range(count)
                ]
            for i, t in enumerate(sample_times):
                t = min(max(t, 0.0), max(0.0, duration - 0.05))
                frame = clip.get_frame(t)
                import PIL.Image

                img = PIL.Image.fromarray(frame)
                ratio = width / img.width
                img = img.resize((width, int(img.height * ratio)))
                p = out_dir / f"frame_{i}.jpg"
                img.save(p, "JPEG", quality=60)
                paths.append(p)
            return paths
        finally:
            clip.close()

    return await asyncio.to_thread(_extract)

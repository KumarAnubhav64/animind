import asyncio
from pathlib import Path

from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

WORDS_PER_SECOND = 2.6
CAPTION_MAX_WORDS = 6


def _find_font() -> str:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return ""


def _caption_chunks(narration: str, max_words: int = CAPTION_MAX_WORDS):
    words = narration.split()
    return [
        " ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)
    ]


def _caption_image(text: str, width: int = 1280, font_size: int = 34):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(_find_font(), font_size)
    # wrap text to ~90% of frame width
    draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) > width * 0.88:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 6
    img_h = line_h * len(lines) + 24
    img = Image.new("RGBA", (width, img_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 12
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((width - w) / 2, y), ln, font=font, fill=(255, 255, 255, 255))
        y += line_h

    # semi-transparent rounded backdrop
    bg = Image.new("RGBA", (width, img_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    bd.rounded_rectangle((20, 4, width - 20, img_h - 4), radius=10, fill=(0, 0, 0, 160))
    out = Image.alpha_composite(bg, img)
    return out


def _merge_with_captions(video_path: str, narration: str, out_path: Path) -> float:
    """No-audio fallback: burn narration subtitles over the animation.

    The animation usually runs shorter than the narration, so we hold the last
    frame until the estimated narration ends (mirrors the audio merge behavior).
    """
    video = VideoFileClip(video_path)
    chunks = _caption_chunks(narration)
    total_words = sum(len(c.split()) for c in chunks)
    est_duration = total_words / WORDS_PER_SECOND

    if est_duration > video.duration:
        last_frame = video.get_frame(max(0.0, video.duration - 0.05))
        freeze = (
            ImageClip(last_frame)
            .with_duration(est_duration - video.duration)
            .with_start(video.duration)
        )
        base = CompositeVideoClip([video, freeze]).with_duration(est_duration)
    else:
        base = video

    overlays = []
    t = 0.0
    for chunk in chunks:
        chunk_dur = len(chunk.split()) / WORDS_PER_SECOND
        chunk_dur = min(chunk_dur, est_duration - t)
        if chunk_dur <= 0.05:
            break
        img = _caption_image(chunk, width=base.size[0])
        # Position from the bottom in absolute pixels. A relative y value such
        # as 0.82 is the overlay's top edge and can push the caption below the
        # frame when the wrapped text is more than one line.
        caption_y = max(8, base.size[1] - img.height - 24)
        clip = (
            ImageClip(np_array_from_pil(img))
            .with_start(t)
            .with_duration(chunk_dur)
            .with_position(("center", caption_y))
        )
        overlays.append(clip)
        t += chunk_dur

    final = CompositeVideoClip([base, *overlays]).with_duration(est_duration)
    final.write_videofile(str(out_path), codec="libx264", logger=None, fps=24)
    duration = final.duration
    video.close()
    base.close()
    final.close()
    for c in overlays:
        c.close()
    return duration


def np_array_from_pil(img):
    import numpy as np

    return np.array(img)


async def merge_with_captions(video_path: str, narration: str, out_path: Path) -> float:
    return await asyncio.to_thread(_merge_with_captions, video_path, narration, out_path)


def _merge(video_path: str, audio_path: str, out_path: Path) -> float:
    video = VideoFileClip(video_path)
    audio = AudioFileClip(audio_path)

    if audio.duration > video.duration:
        # Hold the last frame while narration finishes
        last_frame = video.get_frame(max(0.0, video.duration - 0.05))
        freeze = ImageClip(last_frame).with_duration(audio.duration - video.duration).with_start(video.duration)
        clip = CompositeVideoClip([video, freeze]).with_duration(audio.duration)
    else:
        clip = video.with_duration(audio.duration)

    clip = clip.with_audio(audio)
    clip.write_videofile(
        str(out_path),
        codec="libx264",
        audio_codec="aac",
        logger=None,
        fps=24,
    )
    duration = clip.duration
    video.close()
    audio.close()
    clip.close()
    return duration


async def merge_audio_video(
    video_path: str, audio_path: str, out_path: Path
) -> float:
    return await asyncio.to_thread(_merge, video_path, audio_path, out_path)


def _stitch(scene_paths: list[str], out_path: Path) -> float:
    from moviepy import concatenate_videoclips

    clips = [VideoFileClip(p) for p in scene_paths]
    target_size = clips[0].size
    for c in clips:
        c.resize = None  # avoid stale attribute issues
    final = concatenate_videoclips(clips, method="compose")
    final = final.resized(target_size) if final.size != target_size else final
    final.write_videofile(str(out_path), codec="libx264", audio_codec="aac", logger=None)
    duration = final.duration
    for c in clips:
        c.close()
    final.close()
    return duration


async def stitch_scenes(scene_paths: list[str], out_path: Path) -> float:
    return await asyncio.to_thread(_stitch, scene_paths, out_path)

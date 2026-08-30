"""Guards that only vision-capable models are allowed to critique scenes."""

import asyncio

import pytest

from app.agents import vision_critic
from app.agents.vision_critic import critique_scene


@pytest.fixture(autouse=True)
def _reset_vision_flags():
    vision_critic._router_available = True
    vision_critic._router_retry_after = 0.0
    vision_critic._groq_available = True
    vision_critic._groq_retry_after = 0.0
    yield
    vision_critic._router_available = True
    vision_critic._router_retry_after = 0.0
    vision_critic._groq_available = True
    vision_critic._groq_retry_after = 0.0


def _disable_router(monkeypatch):
    """Simulate the router being quota-exhausted: unavailable + far-future retry."""
    monkeypatch.setattr(vision_critic, "_router_available", False)
    monkeypatch.setattr(vision_critic, "_router_retry_after", float("inf"))


def _disable_groq(monkeypatch):
    monkeypatch.setattr(vision_critic, "_groq_available", False)
    monkeypatch.setattr(vision_critic, "_groq_retry_after", float("inf"))


async def _never(_messages):
    raise AssertionError("no model call should happen")


def test_text_only_fallback_is_never_allowed_to_critique(monkeypatch):
    """When the primary vision model is down, a text-only fallback must fail open
    with a visible reason instead of reviewing (and possibly rejecting) frames."""
    _disable_router(monkeypatch)
    monkeypatch.setattr(vision_critic, "_vision_llm", _never)
    monkeypatch.setattr(vision_critic, "_vision_llm_fallback", _never)
    monkeypatch.setattr(
        vision_critic, "extract_frames",
        lambda *a, **k: _async([]),
    )

    def fake_settings(**overrides):
        from app.config import Settings

        return Settings(
            vision_critique=True,
            vision_max_frames=2,
            vision_frame_width=320,
            vision_model_fallback="some-text-only-model",
            vision_model_fallback_vision_capable=False,
            **overrides,
        )

    monkeypatch.setattr(vision_critic, "get_settings", lambda: fake_settings())

    verdict = asyncio.run(critique_scene("no-such-video.mp4", "narration"))
    assert verdict.passed is True
    assert verdict.issues == []
    assert verdict.skipped_reason is not None
    assert "text-only" in verdict.skipped_reason


def test_vision_capable_fallback_is_used_when_primary_down(monkeypatch):
    """A fallback declared vision-capable is allowed to critique."""
    from app.agents.vision_critic import VisualVerdict

    calls = []

    async def fake_critique_with(llm, content, settings, *, is_router):
        calls.append((llm, is_router))
        return VisualVerdict(passed=True, issues=[])

    frame_requests = []

    async def fake_extract_frames(video_path, *, count, width):
        frame_requests.append(count)
        return []

    _disable_router(monkeypatch)
    monkeypatch.setattr(vision_critic, "_critique_with", fake_critique_with)
    monkeypatch.setattr(vision_critic, "extract_frames", fake_extract_frames)

    def fake_settings(**overrides):
        from app.config import Settings

        return Settings(
            vision_critique=True,
            vision_max_frames=2,
            vision_max_frames_fallback=2,
            vision_frame_width=320,
            vision_model_fallback="some-vision-model",
            vision_model_fallback_vision_capable=True,
            **overrides,
        )

    monkeypatch.setattr(vision_critic, "get_settings", lambda: fake_settings())

    verdict = asyncio.run(critique_scene("no-such-video.mp4", "narration"))
    assert verdict.passed is True
    assert calls and calls[0][1] is False  # is_router=False -> fallback path used
    assert frame_requests == [2]  # fallback uses the reduced frame count


def _async(value):
    async def _inner():
        return value

    return _inner()

import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field

SceneStatus = Literal[
    "pending", "tts", "coding", "rendering", "merging", "ready", "failed"
]
ProjectStatus = Literal[
    "drafting", "producing", "stitching", "ready", "failed"
]


class ScenePlan(BaseModel):
    title: str = Field(description="Short scene title")
    narration: str = Field(
        description="Voiceover narration for this scene, 2-5 spoken sentences"
    )
    visual_description: str = Field(
        description="Concrete description of what the animation should show"
    )


class Storyboard(BaseModel):
    title: str | None = Field(default=None, description="Title of the video")
    hook: str | None = Field(default=None, description="One-line hook shown first")
    scenes: list[ScenePlan] = Field(
        description=f"3 to 4 scenes building up the concept",
    )


class ProjectCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    audience_level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    subject: str | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class MessageOut(BaseModel):
    id: str
    project_id: str
    role: str
    content: str
    scene_id: str | None = None
    video_path: str | None = None
    video_available: bool = False
    created_at: str | None = None


class SceneUpdate(BaseModel):
    title: str | None = None
    narration: str | None = None


class SceneOut(BaseModel):
    id: str
    project_id: str
    idx: int
    title: str
    narration: str
    visual_description: str | None
    manim_code: str | None
    spec_json: str | None = None
    treatment_md: str | None = None
    status: SceneStatus
    error: str | None
    attempts: int
    duration_s: float | None
    muted: bool = False
    video_available: bool = False
    qa_warning: str | None = None


class ProjectOut(BaseModel):
    id: str
    topic: str
    audience_level: str
    subject: str | None
    status: ProjectStatus
    error: str | None
    final_video_path: str | None = None
    research_brief: str | None = None
    scenes: list[SceneOut] = Field(default_factory=list)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


CODE_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)
# Some fallback models emit XML tool-call scaffolding (e.g. `<tool_call>`, `<function=...>`,
# `<parameter=...>`) instead of a pure code block. Strip it before extracting the Python.
TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>.*?</tool_call>|<function=\w*>.*?</function>|<parameter=\w*>.*?</parameter>",
    re.DOTALL,
)


def _strip_tool_call_scaffolding(text: str) -> str:
    cleaned = TOOL_CALL_BLOCK_RE.sub("", text)
    lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("<")]
    return "\n".join(lines).strip()


def extract_python_code(text: str) -> str:
    """Extract python code from an LLM response (strips markdown fences and
    tool-call scaffolding that some fallback models emit)."""
    match = CODE_FENCE_RE.search(text)
    if match:
        return _strip_tool_call_scaffolding(match.group(1)).strip()
    text = _strip_tool_call_scaffolding(text.strip())
    if text.startswith("```"):
        text = text.strip("`").lstrip("python").strip()
    return text

from app.schemas.spec import SceneSpec, SpecBeat, SpecAction  # noqa: E402,F401

SceneOut.model_rebuild()

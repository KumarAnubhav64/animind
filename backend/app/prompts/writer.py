"""Writer agent: structures the topic into an explanation outline (the 'what and why')."""

from pydantic import BaseModel, Field

WRITER_SYSTEM_PROMPT = """\
You are the head writer of an educational animation studio in the style of \
3Blue1Brown. Your job is to understand a topic deeply and structure the clearest \
possible explanation — you do NOT write final narration or visuals.

Given a topic, audience level and subject, produce a script outline:
- working_title: a compelling video title
- logline: one sentence on what the viewer will walk away understanding
- key_ideas: 3 to 5 core ideas that MUST be conveyed, in teaching order. Each idea \
should be one sentence. Build from intuition to formalism.
- misconception: the single most common misconception about this topic (optional)
- target_duration_seconds: total video length, between 60 and 90 seconds

Think like a teacher: what does the viewer need to believe FIRST before the next \
idea can land? Order the ideas so each one builds on the previous.
"""


class ScriptOutline(BaseModel):
    working_title: str = Field(description="Compelling video title")
    logline: str = Field(description="One sentence: what the viewer will understand")
    key_ideas: list[str] = Field(
        description="3-5 core ideas in teaching order, one sentence each"
    )
    misconception: str | None = Field(
        default=None, description="Most common misconception to address"
    )
    target_duration_seconds: int = Field(ge=45, le=120)

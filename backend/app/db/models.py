import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(Text)
    audience_level: Mapped[str] = mapped_column(String, default="beginner")
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="drafting")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_video_path: Mapped[str | None] = mapped_column(String, nullable=True)
    visual_ledger: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "audience_level": self.audience_level,
            "subject": self.subject,
            "status": self.status,
            "error": self.error,
            "final_video_path": self.final_video_path,
            "visual_ledger": self.visual_ledger,
            "created_at": str(self.created_at),
        }


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    narration: Mapped[str] = mapped_column(Text)
    visual_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manim_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    video_path: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    spec_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "idx": self.idx,
            "title": self.title,
            "narration": self.narration,
            "visual_description": self.visual_description,
            "manim_code": self.manim_code,
            "status": self.status,
            "error": self.error,
            "attempts": self.attempts,
            "video_path": self.video_path,
            "audio_path": self.audio_path,
            "duration_s": self.duration_s,
            "muted": self.audio_path is None,
            "video_available": bool(self.video_path) and Path(self.video_path).exists(),
        }

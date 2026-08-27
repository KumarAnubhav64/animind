"""Storyboard service: Writer -> Director -> Producer studio pipeline + persistence."""

from app.agents.studio_graph import run_studio
from app.config import get_settings
from app.db.models import Project
from app.db.repositories import project_repo, scene_repo
from app.pipeline.events import publish


def create_project(topic: str, audience_level: str, subject: str | None) -> Project:
    """Persist a project immediately so the UI can subscribe before agents run."""
    return project_repo.create(
        topic=topic,
        audience_level=audience_level,
        subject=subject,
        status="drafting",
    )


async def generate_storyboard(project_id: str):
    """Run Writer -> Director -> Producer and persist the resulting scenes."""
    project = project_repo.get(project_id)
    if project is None:
        return
    settings = get_settings()
    await publish(
        project.id,
        {"type": "workflow", "agent": "Studio", "node": "start", "message": "Starting Writer → Director → Producer storyboard review.", "details": {}},
    )
    try:
        storyboard = await run_studio(
            project.topic,
            project.audience_level,
            project.subject,
            project_id=project.id,
        )
        for i, scene_plan in enumerate(storyboard.scenes[: settings.max_scenes]):
            scene_repo.create(
                project_id=project.id,
                idx=i,
                title=scene_plan.title,
                narration=scene_plan.narration,
                visual_description=scene_plan.visual_description,
                status="pending",
            )
        await publish(
            project.id,
            {
                "type": "workflow",
                "agent": "Studio",
                "node": "storyboard",
                "message": f"Storyboard complete with {len(storyboard.scenes[: settings.max_scenes])} production scenes.",
                "details": {"scenes": len(storyboard.scenes[: settings.max_scenes])},
            },
        )
        await publish(project.id, {"type": "storyboard", "project_id": project.id})
    except Exception as error:  # noqa: BLE001
        message = f"{type(error).__name__}: {error}"
        project_repo.update(project.id, status="failed", error=message[:2000])
        await publish(
            project.id,
            {
                "type": "workflow",
                "agent": "Studio",
                "node": "storyboard_failed",
                "message": message,
                "details": {"error": message},
            },
        )
        await publish(
            project.id,
            {"type": "project", "status": "failed", "error": message},
        )

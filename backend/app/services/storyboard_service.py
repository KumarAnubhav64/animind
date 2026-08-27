"""Storyboard service: Writer -> Director -> Producer studio pipeline + persistence."""

from app.agents.studio_graph import run_studio
from app.config import get_settings
from app.db.models import Project
from app.db.repositories import message_repo, project_repo, scene_repo
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
    # Save user message (the topic)
    message_repo.create(
        project_id=project_id, role="user", content=project.topic,
    )
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
        n_scenes = len(storyboard.scenes[: settings.max_scenes])
        for i, scene_plan in enumerate(storyboard.scenes[: settings.max_scenes]):
            scene_repo.create(
                project_id=project.id,
                idx=i,
                title=scene_plan.title,
                narration=scene_plan.narration,
                visual_description=scene_plan.visual_description,
                status="pending",
            )
        # Save assistant acknowledgment
        scene_list = "\n".join(
            f"{i+1}. **{s.title}** — {s.narration[:80]}..."
            for i, s in enumerate(storyboard.scenes[:n_scenes])
        )
        message_repo.create(
            project_id=project_id,
            role="assistant",
            content=(
                f"I've planned **{n_scenes} scenes** for your explainer video:\n\n"
                f"{scene_list}\n\n"
                "Starting production now — each scene will be rendered as a separate animation."
            ),
        )
        await publish(
            project.id,
            {
                "type": "workflow",
                "agent": "Studio",
                "node": "storyboard",
                "message": f"Storyboard complete with {n_scenes} production scenes.",
                "details": {"scenes": n_scenes},
            },
        )
        await publish(project.id, {"type": "storyboard", "project_id": project.id})
    except Exception as error:  # noqa: BLE001
        message = f"{type(error).__name__}: {error}"
        project_repo.update(project.id, status="failed", error=message[:2000])
        message_repo.create(
            project_id=project_id, role="assistant",
            content=f"Sorry, production failed: {message[:500]}",
        )
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

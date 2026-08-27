import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.db import init_db, message_repo, project_repo, scene_repo
from app.pipeline.events import history, subscribe, unsubscribe
from app.schemas import MessageCreate, MessageOut, ProjectCreate, ProjectOut, SceneOut, SceneUpdate
from app.services import production_service
from app.services.storyboard_service import create_project as persist_project
from app.services.storyboard_service import generate_storyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("animind")
_active_projects: set[str] = set()

app = FastAPI(title="AniMind", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins + [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    Path(get_settings().media_dir).mkdir(parents=True, exist_ok=True)
    production_service.reconcile_ready_projects()


@app.get("/api/health")
async def health():
    return {"ok": True}


def _project_out(project_id: str) -> ProjectOut:
    project = project_repo.get(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    data = project.to_dict()
    data["scenes"] = [SceneOut(**s.to_dict()).model_dump() for s in scene_repo.list_for_project(project_id)]
    return ProjectOut(**data)


# ---------------------------------------------------------------- projects


@app.get("/api/projects", response_model=list[ProjectOut])
async def list_projects():
    projects = project_repo.list()
    return [_project_out(p.id) for p in projects]


@app.post("/api/projects", response_model=ProjectOut)
async def create_project(req: ProjectCreate):
    if not get_settings().groq_api_key:
        raise HTTPException(503, "ANIMIND_GROQ_API_KEY is not configured")
    project = persist_project(req.topic, req.audience_level, req.subject)
    asyncio.create_task(generate_storyboard(project.id))
    return _project_out(project.id)


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str):
    return _project_out(project_id)


@app.post("/api/projects/{project_id}/produce")
async def produce(project_id: str):
    if project_repo.get(project_id) is None:
        raise HTTPException(404, "Project not found")
    if project_id in _active_projects:
        raise HTTPException(409, "Project production is already running")
    _active_projects.add(project_id)

    async def run():
        try:
            await production_service.produce_project(project_id)
        finally:
            _active_projects.discard(project_id)

    asyncio.create_task(run())
    return {"started": True}


@app.post("/api/scenes/{scene_id}/regenerate")
async def regenerate(scene_id: str):
    scene = scene_repo.get(scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    if scene.project_id in _active_projects:
        raise HTTPException(409, "Project production is already running")
    _active_projects.add(scene.project_id)

    async def run():
        try:
            await production_service.regenerate_scene(scene.project_id, scene_id)
        finally:
            _active_projects.discard(scene.project_id)

    asyncio.create_task(run())
    return {"started": True}


@app.patch("/api/scenes/{scene_id}", response_model=SceneOut)
async def update_scene(scene_id: str, req: SceneUpdate):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Nothing to update")
    current = scene_repo.get(scene_id)
    if current is None:
        raise HTTPException(404, "Scene not found")
    if current.project_id in _active_projects:
        raise HTTPException(409, "Cannot edit a project while production is running")
    scene = scene_repo.update(scene_id, **fields)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    # Title/narration are generation inputs. In sequential mode, changing an
    # earlier scene also invalidates every downstream continuity-dependent scene.
    if "title" in fields or "narration" in fields:
        affected = [
            item
            for item in scene_repo.list_for_project(scene.project_id)
            if item.idx >= scene.idx
        ]
        for item in affected:
            scene_repo.update(
                item.id,
                status="pending",
                manim_code=None,
                video_path=None,
                audio_path=None,
                duration_s=None,
                attempts=0,
                spec_json=None,
                error=None,
            )
        project_repo.update(
            scene.project_id,
            status="drafting",
            final_video_path=None,
            error=None,
        )
        scene = scene_repo.get(scene_id)
    return SceneOut(**scene.to_dict())


# ---------------------------------------------------------------- streaming


@app.get("/api/projects/{project_id}/events")
async def events(project_id: str):
    queue = subscribe(project_id)

    async def gen():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=600)
                yield {"data": json.dumps(event)}
                if event.get("type") == "project" and event.get("status") in (
                    "ready",
                    "failed",
                ):
                    break
        except asyncio.TimeoutError:
            yield {"data": json.dumps({"type": "ping"})}
        finally:
            unsubscribe(project_id, queue)

    return EventSourceResponse(gen())


@app.get("/api/projects/{project_id}/events/history")
async def event_history(project_id: str):
    if project_repo.get(project_id) is None:
        raise HTTPException(404, "Project not found")
    return {"events": history(project_id)}


@app.get("/api/config")
async def public_config():
    settings = get_settings()
    return {
        "models": {
            "planner": settings.planner_model,
            "coder": settings.coder_model,
            "fixer": settings.fixer_model,
            "fallback": settings.fallback_model,
            "vision": settings.vision_model if settings.vision_critique else None,
        },
        "tts": {
            "enabled": settings.tts_enabled,
            "model": settings.tts_model,
            "voice": settings.tts_voice,
            "fallback": "muted animation with burned-in captions",
        },
        "codegen_mode": settings.codegen_mode,
        "sequential_scenes": settings.sequential_scenes,
        "math_expert": {
            "enabled": settings.math_expert_enabled,
            "max_attempts": settings.math_expert_max_attempts,
            "model": settings.math_expert_model
            or settings.premium_model
            or settings.fixer_model,
        },
        "vision": {
            "enabled": settings.vision_critique,
            "frames": settings.vision_max_frames,
            "width": settings.vision_frame_width,
        },
    }


@app.get("/api/scenes/{scene_id}/video")
async def scene_video(scene_id: str):
    scene = scene_repo.get(scene_id)
    if scene is None or scene.status != "ready" or not scene.video_path:
        raise HTTPException(404, "Scene video not ready")
    path = Path(scene.video_path)
    if not path.exists():
        raise HTTPException(404, "Scene video file missing")
    return FileResponse(path, media_type="video/mp4", filename=f"scene_{scene.idx}.mp4")


@app.get("/api/videos/{project_id}")
async def video(project_id: str):
    project = project_repo.get(project_id)
    if (
        project is None
        or project.status != "ready"
        or not project.final_video_path
        or not production_service.project_artifacts_ready(project_id)
    ):
        raise HTTPException(404, "Video not ready")
    path = Path(project.final_video_path)
    if not path.exists():
        raise HTTPException(404, "Video not ready")
    return FileResponse(path, media_type="video/mp4", filename="animind.mp4")


# ---------------------------------------------------------------- chat


@app.get("/api/projects/{project_id}/messages", response_model=list[MessageOut])
async def get_messages(project_id: str):
    if project_repo.get(project_id) is None:
        raise HTTPException(404, "Project not found")
    msgs = message_repo.list_for_project(project_id)
    return [MessageOut(**m.to_dict()) for m in msgs]


@app.post("/api/projects/{project_id}/messages", response_model=MessageOut)
async def send_message(project_id: str, req: MessageCreate):
    project = project_repo.get(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if project_id in _active_projects:
        raise HTTPException(409, "Project production is already running")
    # Persist the user message
    message_repo.create(project_id=project_id, role="user", content=req.content)
    # Trigger production
    _active_projects.add(project_id)

    async def run():
        try:
            await production_service.produce_project(project_id)
        finally:
            _active_projects.discard(project_id)

    asyncio.create_task(run())
    # Return the user message; assistant messages are added during pipeline
    msgs = message_repo.list_for_project(project_id)
    return MessageOut(**msgs[-1].to_dict())

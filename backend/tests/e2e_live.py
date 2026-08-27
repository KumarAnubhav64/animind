"""End-to-end test with live Groq API: storyboard -> produce 1 scene."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import init_db, make_session
from app.db.models import Project, Scene
from app.services.storyboard_service import create_project_with_storyboard
from app.services.production_service import produce_scene


async def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "Why does compounding interest grow exponentially?"
    init_db()

    project = await create_project_with_storyboard(topic, "beginner", None)
    print(f"\nPROJECT {project.id} — storyboard: {topic!r}")
    with make_session() as s:
        scenes = s.query(Scene).filter(Scene.project_id == project.id).order_by(Scene.idx).all()
        for sc in scenes:
            print(f"  [{sc.idx}] {sc.title}\n      narration: {sc.narration[:100]}...\n      visual: {sc.visual_description[:90]}...")
        scene = scenes[0]

    ok = await produce_scene(scene)
    s2 = make_session()
    sc = s2.query(Scene).get(scene.id) if hasattr(make_session, "__self__") else None

    from app.db.repositories import scene_repo
    result = scene_repo.get(scene.id)
    print(f"\nSCENE RESULT: status={result.status} attempts={result.attempts} duration={result.duration_s}")
    if result.error:
        print("error tail:", (result.error or "")[-300:])
    if result.video_path and Path(result.video_path).exists():
        print(f"video: {result.video_path} ({Path(result.video_path).stat().st_size//1024} KB)")
    print("E2E TEST", "PASSED" if ok else "FAILED")


asyncio.run(main())

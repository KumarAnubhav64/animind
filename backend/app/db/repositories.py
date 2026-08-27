"""Repository layer: all SQL lives here. Services never touch sessions directly."""

from sqlalchemy import select

from app.db.models import Project, Scene
from app.db.session import make_session


class ProjectRepository:
    def list(self) -> list[Project]:
        with make_session() as s:
            return s.scalars(select(Project).order_by(Project.created_at)).all()

    def get(self, project_id: str) -> Project | None:
        with make_session() as s:
            return s.get(Project, project_id)

    def create(self, **fields) -> Project:
        project = Project(**fields)
        with make_session() as s:
            s.add(project)
            s.commit()
        return project

    def update(self, project_id: str, **fields) -> Project | None:
        with make_session() as s:
            project = s.get(Project, project_id)
            if project is None:
                return None
            for k, v in fields.items():
                setattr(project, k, v)
            s.commit()
            return project


class SceneRepository:
    def list_for_project(self, project_id: str) -> list[Scene]:
        with make_session() as s:
            return (
                s.scalars(
                    select(Scene)
                    .where(Scene.project_id == project_id)
                    .order_by(Scene.idx)
                )
                .all()
            )

    def get(self, scene_id: str) -> Scene | None:
        with make_session() as s:
            return s.get(Scene, scene_id)

    def create(self, **fields) -> Scene:
        scene = Scene(**fields)
        with make_session() as s:
            s.add(scene)
            s.commit()
            return scene

    def update(self, scene_id: str, **fields) -> Scene | None:
        with make_session() as s:
            scene = s.get(Scene, scene_id)
            if scene is None:
                return None
            for k, v in fields.items():
                setattr(scene, k, v)
            s.commit()
            return scene


project_repo = ProjectRepository()
scene_repo = SceneRepository()

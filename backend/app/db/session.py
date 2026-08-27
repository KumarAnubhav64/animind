from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _engine_url() -> str:
    url = get_settings().database_url
    return url if "://" in url else f"sqlite:///{url}"


_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_engine_url(), connect_args={"check_same_thread": False})
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def make_session() -> Session:
    return get_session_factory()()


def init_db():
    from app.db.models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)

    # `create_all` does not add columns to an existing SQLite database. Keep
    # the small prototype migration here so upgrades do not lose spec context.
    columns = {column["name"] for column in inspect(engine).get_columns("scenes")}
    if "spec_json" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE scenes ADD COLUMN spec_json TEXT"))
    project_columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    if "visual_ledger" not in project_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE projects ADD COLUMN visual_ledger TEXT"))

    columns = {column["name"] for column in inspect(engine).get_columns("scenes")}
    if "treatment_md" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE scenes ADD COLUMN treatment_md TEXT"))

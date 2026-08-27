import json
import sqlite3
import threading
from contextlib import contextmanager

from app.config import get_settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    audience_level TEXT NOT NULL DEFAULT 'beginner',
    subject TEXT,
    status TEXT NOT NULL DEFAULT 'drafting',
    final_video_path TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    idx INTEGER NOT NULL,
    title TEXT NOT NULL,
    narration TEXT NOT NULL,
    visual_description TEXT,
    manim_code TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    video_path TEXT,
    audio_path TEXT,
    duration_s REAL,
    spec_json TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().database_url, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _lock, db() as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def dumps(obj) -> str:
    return json.dumps(obj)

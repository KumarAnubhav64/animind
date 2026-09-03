"""Development server with hot-reload that properly excludes media/ from the
file watcher.

Watchfiles reports *absolute* paths, but uvicorn's FileFilter stores the
``reload_excludes`` entries as-is and compares them against ``path.parents``
using relative ``PosixPath('media')`` — which never matches the absolute
parent ``PosixPath('/home/.../backend/media')``.  Passing the absolute path
fixes this.
"""
from pathlib import Path

_MEDIA = (Path(__file__).resolve().parent / "media").as_posix()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=[_MEDIA],
    )


if __name__ == "__main__":
    main()

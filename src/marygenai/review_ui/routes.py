from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


def mount_review_ui(app: FastAPI) -> None:
    """Mount the local static review UI on an existing FastAPI app."""
    static_dir = Path(__file__).parent / "static"
    index_path = static_dir / "index.html"

    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    def review_ui_index() -> str:
        return index_path.read_text(encoding="utf-8")

    app.mount(
        "/ui/static",
        StaticFiles(directory=str(static_dir)),
        name="review_ui_static",
    )

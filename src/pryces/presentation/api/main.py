import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import data, health, overview, portfolios

API_PREFIX = "/api"
WEB_DIR_ENV_VAR = "PRYCES_WEB_DIR"
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_WEB_DIR = _REPO_ROOT / "web"


def resolve_web_dir() -> Path:
    override = os.environ.get(WEB_DIR_ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT_WEB_DIR


def create_app() -> FastAPI:
    load_dotenv()
    app = FastAPI(title="Pryces Portfolio API", version="0.1.0")

    # Only needed when the dashboard runs on its own dev server (`ng serve`);
    # a bundled dashboard is same-origin and never preflights.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (health.router, overview.router, portfolios.router, data.router):
        app.include_router(router, prefix=API_PREFIX)

    _mount_web(app)
    return app


def _mount_web(app: FastAPI) -> None:
    # Mounted last so it can never shadow the API. Absent in a headless
    # deployment, in which case the app simply stays API-only.
    directory = resolve_web_dir()
    if not directory.is_dir():
        return
    # The dashboard uses hash routing, so every deep link requests "/" and the
    # fragment resolves client-side — no server-side SPA fallback needed.
    app.mount("/", StaticFiles(directory=directory, html=True), name="web")


app = create_app()

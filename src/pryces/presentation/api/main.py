from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import health, portfolios


def create_app() -> FastAPI:
    load_dotenv()
    app = FastAPI(title="Pryces Portfolio API", version="0.1.0")

    # v1 binds to loopback; allow localhost web origins (any port) so the
    # dashboard served via `python -m http.server` can call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(portfolios.router)
    return app


app = create_app()

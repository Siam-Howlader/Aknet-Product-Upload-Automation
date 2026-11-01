from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database.db import init_database
from app.logging_setup import configure_logging
from app.routes.automation import router as automation_router
from app.routes.products import router as products_router


def create_app() -> FastAPI:
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_database()
        yield

    app = FastAPI(title="AI OpenCart Product Uploader",
                  version="0.1.0", lifespan=lifespan)

    static_dir = Path("app/static")
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "images").mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates = Jinja2Templates(directory="app/templates")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"title": "AI OpenCart Product Uploader"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(
        products_router, prefix="/api/products", tags=["products"])
    app.include_router(automation_router,
                       prefix="/api/automation", tags=["automation"])

    return app


def run() -> None:
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


app = create_app()

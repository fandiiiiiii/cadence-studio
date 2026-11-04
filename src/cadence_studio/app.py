"""FastAPI application factory for the local Cadence Studio workbench."""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__
from .api import router
from .config import DATA_DIR, WEB_DIR, ensure_dirs
from .services import SERVICES


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    SERVICES.manager.start()
    SERVICES.db.add_event("app_started", f"工作台启动 · v{__version__}")
    yield
    SERVICES.manager.shutdown()
    SERVICES.db.add_event("app_stopped", "工作台关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cadence Studio API",
        version=__version__,
        description="Local, taxonomy-governed AI music annotation workbench.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        host = request.url.hostname or ""
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse(
                status_code=403,
                content={"detail": {"message": "仅允许从本机访问 Cadence Studio。", "code": "local_only"}},
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                origin_host = urlparse(origin).hostname or ""
                if origin_host not in {"127.0.0.1", "localhost", "::1"}:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": {"message": "跨站请求被拒绝。", "code": "bad_origin"}},
                    )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
            "font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(part) for part in first.get("loc", []))
        message = first.get("msg", "请求参数无效")
        return JSONResponse(
            status_code=422,
            content={"detail": {"message": f"{loc}: {message}".strip(": "), "code": "validation_error"}},
        )

    app.include_router(router)
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR)), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/api/info", include_in_schema=False)
    def info():
        return {"name": APP_NAME, "version": __version__, "data_dir": str(DATA_DIR)}

    return app


app = create_app()

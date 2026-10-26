from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .routers import admin, auth, institution, notifications, reviewer_apps, reviewer_docs, reviewer_findings, reviewer_notices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pramaan")

app = FastAPI(title="PRAMAAN — AICTE Application Scrutiny Prototype", version="0.1.0",
              docs_url="/api/docs" if settings.env != "production" else None, redoc_url=None,
              openapi_url="/api/openapi.json" if settings.env != "production" else None)

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-Requested-With"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": {"status": exc.status_code, "message": exc.detail}}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")} for e in exc.errors()]
    return JSONResponse({"error": {"status": 422, "message": "Some fields are invalid", "fields": errs}}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"error": {"status": 500, "message": "Internal server error. The incident has been logged."}}, status_code=500)


for r in (auth, reviewer_apps, reviewer_docs, reviewer_findings, reviewer_notices, institution, admin, notifications):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


if settings.secret_key.startswith("dev-only"):
    log.warning("SECRET_KEY not set — using an insecure development key")

# Serve the built SPA (frontend/dist) with history-API fallback so deep links survive refresh.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (DIST / full_path).resolve()
        if full_path and DIST.resolve() in f.parents and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")

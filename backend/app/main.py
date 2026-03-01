from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.supabase import get_supabase, shutdown_supabase
from app.routers.cases import router as cases_router
from app.routers.emails import router as emails_router
from app.routers.gmail import router as gmail_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail fast on missing critical env vars.
    get_supabase()
    yield
    shutdown_supabase()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

_SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "screenshots"
_SCREENSHOT_DIR.mkdir(exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(_SCREENSHOT_DIR)), name="screenshots")

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(cases_router)
app.include_router(emails_router)
app.include_router(gmail_router)

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.supabase import get_supabase, shutdown_supabase
from app.routers.cases import router as cases_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail fast on missing critical env vars.
    get_supabase()
    yield
    shutdown_supabase()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

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

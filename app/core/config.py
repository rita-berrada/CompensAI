from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    log_level: str
    cors_origins: list[str]

    supabase_url: str
    supabase_service_role_key: str
    supabase_schema: str
    supabase_timeout_seconds: float

    n8n_webhook_secret: str | None
    agent1_send_webhook_url: str | None

    admin_api_key: str | None

    anthropic_api_key: str | None
    anthropic_model: str
    anthropic_timeout_seconds: float

    stripe_secret_key: str | None
    stripe_success_url: str
    stripe_cancel_url: str
    success_fee_rate: float


def load_settings() -> Settings:
    load_dotenv(override=False)

    return Settings(
        app_name=os.getenv("APP_NAME", "CompensAI Backend"),
        environment=os.getenv("ENVIRONMENT", "local"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        cors_origins=_split_csv(os.getenv("CORS_ORIGINS")),
        supabase_url=_env_required("SUPABASE_URL").rstrip("/"),
        supabase_service_role_key=_env_required("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_schema=os.getenv("SUPABASE_SCHEMA", "public"),
        supabase_timeout_seconds=_env_float("SUPABASE_TIMEOUT_SECONDS", 15.0),
        n8n_webhook_secret=os.getenv("N8N_WEBHOOK_SECRET") or None,
        agent1_send_webhook_url=os.getenv("AGENT1_SEND_WEBHOOK_URL") or None,
        admin_api_key=os.getenv("ADMIN_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
        anthropic_timeout_seconds=_env_float("ANTHROPIC_TIMEOUT_SECONDS", 30.0),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY") or None,
        stripe_success_url=os.getenv("STRIPE_SUCCESS_URL", "https://example.com/success"),
        stripe_cancel_url=os.getenv("STRIPE_CANCEL_URL", "https://example.com/cancel"),
        success_fee_rate=_env_float("SUCCESS_FEE_RATE", 0.2),
    )


settings = load_settings()

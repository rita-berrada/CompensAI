from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_n8n_secret(
    x_compensai_webhook_secret: str | None = Header(default=None, alias="X-CompensAI-Webhook-Secret"),
) -> None:
    if not settings.n8n_webhook_secret:
        return
    if x_compensai_webhook_secret != settings.n8n_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")


def require_admin_key(
    x_compensai_admin_key: str | None = Header(default=None, alias="X-CompensAI-Admin-Key"),
) -> None:
    if not settings.admin_api_key:
        return
    if x_compensai_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")

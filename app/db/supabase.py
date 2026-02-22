from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


class SupabaseError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class SupabaseRESTClient:
    base_url: str
    service_role_key: str
    schema: str = "public"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.rest_url = f"{self.base_url}/rest/v1"
        self._client = httpx.Client(timeout=self.timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.service_role_key,
            "authorization": f"Bearer {self.service_role_key}",
            "accept": "application/json",
            "content-type": "application/json",
            "accept-profile": self.schema,
            "content-profile": self.schema,
        }

    def select(
        self,
        table: str,
        *,
        filters: dict[str, str] | None = None,
        columns: str = "*",
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": columns}
        if filters:
            params.update(filters)
        if limit is not None:
            params["limit"] = str(limit)
        if order is not None:
            params["order"] = order

        try:
            resp = self._client.get(f"{self.rest_url}/{table}", headers=self._headers(), params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SupabaseError(
                f"Supabase select failed for {table}",
                status_code=exc.response.status_code,
                body=exc.response.text,
            ) from exc
        return list(resp.json() or [])

    def insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {**self._headers(), "prefer": "return=representation"}
        try:
            resp = self._client.post(f"{self.rest_url}/{table}", headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SupabaseError(
                f"Supabase insert failed for {table}",
                status_code=exc.response.status_code,
                body=exc.response.text,
            ) from exc
        data = resp.json() or []
        if isinstance(data, list) and data:
            return dict(data[0])
        if isinstance(data, dict):
            return data
        return {}

    def update(self, table: str, *, filters: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        headers = {**self._headers(), "prefer": "return=representation"}
        try:
            resp = self._client.patch(f"{self.rest_url}/{table}", headers=headers, params=filters, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SupabaseError(
                f"Supabase update failed for {table}",
                status_code=exc.response.status_code,
                body=exc.response.text,
            ) from exc
        data = resp.json() or []
        if isinstance(data, list) and data:
            return dict(data[0])
        if isinstance(data, dict):
            return data
        return {}

    def delete(self, table: str, *, filters: dict[str, str]) -> None:
        try:
            resp = self._client.delete(f"{self.rest_url}/{table}", headers=self._headers(), params=filters)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SupabaseError(
                f"Supabase delete failed for {table}",
                status_code=exc.response.status_code,
                body=exc.response.text,
            ) from exc


_supabase: SupabaseRESTClient | None = None


def get_supabase() -> SupabaseRESTClient:
    global _supabase
    if _supabase is None:
        _supabase = SupabaseRESTClient(
            base_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            schema=settings.supabase_schema,
            timeout_seconds=settings.supabase_timeout_seconds,
        )
    return _supabase


def shutdown_supabase() -> None:
    global _supabase
    if _supabase is None:
        return
    _supabase.close()
    _supabase = None

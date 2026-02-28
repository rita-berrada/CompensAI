from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.db.supabase import SupabaseRESTClient


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_jsonable_decimal(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def find_case_by_message_id(db: SupabaseRESTClient, message_id: str) -> dict[str, Any] | None:
    rows = db.select("cases", filters={"message_id": f"eq.{message_id}"}, columns="*", limit=1)
    return rows[0] if rows else None


def get_case(db: SupabaseRESTClient, case_id: str) -> dict[str, Any] | None:
    rows = db.select("cases", filters={"id": f"eq.{case_id}"}, columns="*", limit=1)
    return rows[0] if rows else None


def insert_case(
    db: SupabaseRESTClient,
    *,
    source: str,
    message_id: str,
    thread_id: str | None,
    from_email: str,
    to_email: str,
    email_subject: str,
    email_body: str,
    vendor: str | None = None,
    category: str | None = None,
    estimated_value: Decimal | None = None,
    flight_number: str | None = None,
    booking_reference: str | None = None,
    incident_date: str | None = None,
    status: str = "processing",
) -> dict[str, Any]:
    case_id = str(uuid4())
    payload: dict[str, Any] = {
        "id": case_id,
        "source": source,
        "message_id": message_id,
        "thread_id": thread_id,
        "from_email": from_email,
        "to_email": to_email,
        "email_subject": email_subject,
        "email_body": email_body,
        "vendor": vendor,
        "category": category,
        "estimated_value": _to_jsonable_decimal(estimated_value),
        "flight_number": flight_number,
        "booking_reference": booking_reference,
        "incident_date": incident_date,
        "status": status,
        "updated_at": _utc_now_iso(),
    }
    return db.insert("cases", payload)


def update_case(db: SupabaseRESTClient, case_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    updates = {**updates, "updated_at": _utc_now_iso()}
    return db.update("cases", filters={"id": f"eq.{case_id}"}, payload=updates)


def insert_event(
    db: SupabaseRESTClient,
    *,
    case_id: str,
    actor: str,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid4()),
        "case_id": case_id,
        "actor": actor,
        "event_type": event_type,
        "details": details or {},
    }
    return db.insert("case_events", payload)


def delete_case(db: SupabaseRESTClient, case_id: str) -> None:
    """Delete a case and all its associated events from Supabase."""
    # Delete case events first (foreign key constraint)
    db.delete("case_events", filters={"case_id": f"eq.{case_id}"})
    # Delete the case
    db.delete("cases", filters={"id": f"eq.{case_id}"})


def get_pending_drafts(db: SupabaseRESTClient, limit: int = 100) -> list[dict[str, Any]]:
    """Get cases with drafts ready to send (awaiting_approval status)."""
    rows = db.select(
        "cases",
        filters={"status": "eq.awaiting_approval"},
        columns="id,from_email,to_email,email_body,draft_email_subject,draft_email_body,form_data,thread_id,message_id,vendor,category,flight_number,booking_reference",
        limit=limit,
        order="updated_at.desc",  # Most recent first
    )
    # Filter to only include cases that have both subject and body
    return [
        row for row in rows
        if row.get("draft_email_subject") and row.get("draft_email_body")
    ]

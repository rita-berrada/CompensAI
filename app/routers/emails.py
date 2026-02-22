from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import require_n8n_secret
from app.db.supabase import SupabaseError, get_supabase
from app.repositories.cases import find_case_by_message_id, insert_case, insert_event, update_case
from app.routers.cases import CaseIntakeRequest
from app.services.agent2 import process_case
from app.services.triage import triage_email


router = APIRouter(prefix="/emails", tags=["emails"])


class EmailIngestResponse(BaseModel):
    accepted: bool
    decision: str
    triage: dict[str, Any]
    existing: bool = False
    case_id: str | None = None
    status: str | None = None


def _clean_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


@router.post("/ingest", response_model=EmailIngestResponse)
def ingest_email(payload: CaseIntakeRequest, _: None = Depends(require_n8n_secret)) -> EmailIngestResponse:
    """
    n8n should POST *every* email here.
    - Triage decides trash vs candidate.
    - Only candidate creates a case and triggers Agent2.
    """
    db = get_supabase()
    try:
        extracted_fields = payload.extracted_fields or {}
        subject = _clean_or_none(payload.email_subject) or _clean_or_none(extracted_fields.get("subject")) or ""
        body_text = _clean_or_none(payload.email_body) or _clean_or_none(extracted_fields.get("body_text")) or _clean_or_none(
            extracted_fields.get("snippet")
        ) or ""
        from_email = _clean_or_none(payload.from_email) or _clean_or_none(extracted_fields.get("from_email")) or "unknown@unknown.local"
        to_email = _clean_or_none(payload.to_email) or _clean_or_none(extracted_fields.get("to_email")) or "unknown@unknown.local"

        existing = find_case_by_message_id(db, payload.message_id)
        if existing:
            triage = {"confidence": 1, "reasons": ["Duplicate message_id"], "hints": {}}
            return EmailIngestResponse(
                accepted=True,
                decision="candidate",
                triage=triage,
                existing=True,
                case_id=existing["id"],
                status=existing.get("status"),
            )

        triage_result = triage_email(
            subject=subject,
            body_text=body_text,
            from_email=from_email,
            extracted_fields=extracted_fields,
        )
        triage_output = dict(triage_result.output or {})
        decision = str(triage_output.get("decision") or "candidate")
        if decision not in {"trash", "candidate"}:
            decision = "candidate"

        if decision == "trash":
            return EmailIngestResponse(accepted=False, decision="trash", triage=triage_output, existing=False)

        hints = triage_output.get("hints") if isinstance(triage_output.get("hints"), dict) else {}
        vendor_hint = hints.get("vendor_hint") if isinstance(hints, dict) else None
        category_hint = hints.get("category_hint") if isinstance(hints, dict) else None

        extracted_fields_augmented = {**extracted_fields, "triage": triage_output}

        created = insert_case(
            db,
            source=payload.source,
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            from_email=from_email,
            to_email=to_email,
            email_subject=subject,
            email_body=body_text,
            vendor=payload.vendor or (vendor_hint if isinstance(vendor_hint, str) else None),
            category=payload.category or (category_hint if isinstance(category_hint, str) else None),
            estimated_value=payload.estimated_value,
            flight_number=payload.flight_number,
            booking_reference=payload.booking_reference,
            incident_date=payload.incident_date,
            status="processing",
        )

        insert_event(
            db,
            case_id=created["id"],
            actor="agent1",
            event_type="email_scanned",
            details={
                "message_id": payload.message_id,
                "thread_id": payload.thread_id,
                "source": payload.source,
                "extracted_fields": extracted_fields_augmented,
                "triage_meta": {
                    "model": triage_result.model,
                    "usage": triage_result.usage,
                    "error": triage_result.error,
                },
            },
        )

        agent2_result = process_case(created, extracted_fields=extracted_fields_augmented)
        updated = update_case(db, created["id"], agent2_result.case_updates)

        for event_type, details in agent2_result.events:
            insert_event(db, case_id=created["id"], actor="agent2", event_type=event_type, details=details)

        return EmailIngestResponse(
            accepted=True,
            decision="candidate",
            triage=triage_output,
            existing=False,
            case_id=updated["id"],
            status=updated.get("status"),
        )
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc

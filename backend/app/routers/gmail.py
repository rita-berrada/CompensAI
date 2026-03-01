from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import require_admin_key
from app.db.supabase import SupabaseError, get_supabase
from app.repositories.cases import (
    find_case_by_message_id,
    get_case,
    insert_case,
    insert_event,
    update_case,
)
from pathlib import Path

from app.services.agent2 import _infer_category, process_case
from app.services.form_filler import fill_form
from app.services.gmail import get_gmail_service

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

router = APIRouter(prefix="/gmail", tags=["gmail"])


# ---------------------------------------------------------------------------
# POST /gmail/scan-inbox
# ---------------------------------------------------------------------------


class ScanInboxResponse(BaseModel):
    scanned: int
    created: int
    skipped: int
    errors: list[str] = []


@router.post("/scan-inbox", response_model=ScanInboxResponse)
def scan_inbox(_: None = Depends(require_admin_key)) -> ScanInboxResponse:
    """
    Scan Gmail inbox for unprocessed compensation emails.

    For each new message:
    - Creates a case via the same pipeline as POST /cases/intake
    - Labels the message compensai_processed so it won't be re-scanned

    Replaces the n8n  Gmail Trigger → Convert JSON → POST /cases/intake  workflow.
    """
    db = get_supabase()
    try:
        gmail = get_gmail_service(
            credentials_file=settings.gmail_credentials_file,
            token_file=settings.gmail_token_file,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    messages = gmail.list_unprocessed_messages(max_results=50)
    scanned = len(messages)
    created = 0
    skipped = 0
    errors: list[str] = []

    for msg_ref in messages:
        message_id: str = msg_ref["id"]
        try:
            # Skip if already in DB
            if find_case_by_message_id(db, message_id):
                gmail.mark_processed(message_id)
                skipped += 1
                continue

            data = gmail.get_message(message_id)
            subject = data.get("subject", "")
            body = data.get("body_text", "")

            # Step 1: Relevance filter — skip non-claim emails (ads, personal, newsletters)
            if _infer_category(subject, body) is None:
                gmail.mark_processed(message_id)
                skipped += 1
                continue

            created_case = insert_case(
                db,
                source="gmail",
                message_id=data["message_id"],
                thread_id=data["thread_id"],
                from_email=data["from_email"],
                to_email=data["to_email"],
                email_subject=subject,
                email_body=body,
                vendor=None,
                category=None,
                estimated_value=None,
                flight_number=None,
                booking_reference=None,
                incident_date=None,
                status="processing",
            )

            insert_event(
                db,
                case_id=created_case["id"],
                actor="agent1",
                event_type="email_scanned",
                details={
                    "message_id": data["message_id"],
                    "thread_id": data["thread_id"],
                    "source": "gmail",
                    "extracted_fields": {},
                },
            )

            # Step 2: Eligibility check via Agent2
            agent2_result = process_case(created_case, extracted_fields=None)
            updated = update_case(db, created_case["id"], agent2_result.case_updates)

            for event_type, details in agent2_result.events:
                insert_event(db, case_id=created_case["id"], actor="agent2", event_type=event_type, details=details)

            eligibility_result = updated.get("eligibility_result")

            if eligibility_result == "eligible":
                # Step 3a: Auto-fill form if a portal/form URL is available
                form_data = updated.get("form_data") or {}
                portal_url = form_data.get("portal_url") or form_data.get("form_url")
                if portal_url:
                    fields_to_fill = form_data.get("fields_to_fill") or {}
                    # Inject complaint_summary from draft email body if not already present
                    if not fields_to_fill.get("complaint_summary"):
                        draft_body = updated.get("draft_email_body") or ""
                        complaint_summary = None
                        for line in draft_body.splitlines():
                            if line.startswith("Complaint Summary:"):
                                complaint_summary = line.replace("Complaint Summary:", "").strip()
                                break
                        if not complaint_summary and draft_body.strip():
                            complaint_summary = draft_body.strip()[:500]
                        if complaint_summary:
                            fields_to_fill["complaint_summary"] = complaint_summary
                    fill_result = fill_form(
                        portal_url,
                        fields_to_fill,
                        screenshot_dir=SCREENSHOT_DIR,
                        vendor=updated.get("vendor"),
                    )
                    if fill_result.screenshot_path:
                        screenshot_filename = Path(fill_result.screenshot_path).name
                        video_filename = Path(fill_result.video_path).name if fill_result.video_path else None
                        decision_json = updated.get("decision_json") or {}
                        decision_json["form_fill"] = {
                            "screenshot_filename": screenshot_filename,
                            "video_filename": video_filename,
                            "fields_filled": fill_result.fields_filled,
                            "url": fill_result.url,
                            "fields_to_fill": fields_to_fill,
                        }
                        update_case(db, created_case["id"], {"decision_json": decision_json})
                created += 1
            else:
                # Step 3b: Not eligible — keep in DB with explanation, mark not_eligible
                update_case(db, created_case["id"], {"status": "not_eligible"})
                created += 1

            gmail.mark_processed(message_id)

        except Exception as exc:  # noqa: BLE001
            errors.append(f"{message_id}: {exc}")

    return ScanInboxResponse(scanned=scanned, created=created, skipped=skipped, errors=errors)


# ---------------------------------------------------------------------------
# POST /gmail/send/{case_id}
# ---------------------------------------------------------------------------


class SendDraftResponse(BaseModel):
    id: str
    status: str
    sent_to: str


@router.post("/send/{case_id}", response_model=SendDraftResponse)
def send_draft(case_id: UUID, _: None = Depends(require_admin_key)) -> SendDraftResponse:
    """
    Send the AI-drafted email for a case directly via Gmail.

    - Uses contact_email from form_data if available, else falls back to from_email
    - Updates case status to submitted_to_vendor
    - Inserts a submitted_to_vendor event

    Replaces the n8n  Poll Pending Drafts → Gmail Send Draft  workflow.
    """
    db = get_supabase()
    try:
        gmail = get_gmail_service(
            credentials_file=settings.gmail_credentials_file,
            token_file=settings.gmail_token_file,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        case = get_case(db, str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        draft_subject = case.get("draft_email_subject")
        draft_body = case.get("draft_email_body")
        if not draft_subject or not draft_body:
            raise HTTPException(status_code=409, detail="No draft available for this case")

        # Determine recipient — prefer contact_email from form_data
        to_email: str = case.get("from_email") or "unknown@unknown.local"
        form_data = case.get("form_data") or {}
        if isinstance(form_data, str):
            try:
                form_data = _json.loads(form_data)
            except Exception:  # noqa: BLE001
                form_data = {}
        if isinstance(form_data, dict):
            contact = form_data.get("contact_email")
            if contact and isinstance(contact, str) and contact.strip():
                to_email = contact.strip()

        gmail.send_message(to_email, draft_subject, draft_body)

        updated = update_case(db, case["id"], {"status": "submitted_to_vendor"})
        insert_event(
            db,
            case_id=case["id"],
            actor="system",
            event_type="submitted_to_vendor",
            details={"sent_via": "gmail_api", "to_email": to_email},
        )

        return SendDraftResponse(id=str(case_id), status=updated.get("status", "submitted_to_vendor"), sent_to=to_email)

    except HTTPException:
        raise
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc

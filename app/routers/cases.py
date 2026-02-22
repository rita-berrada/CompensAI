from __future__ import annotations

import base64
import re
from decimal import Decimal
from io import BytesIO
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from pydantic.aliases import AliasChoices
from pydantic.config import ConfigDict
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.core.config import settings
from app.core.security import require_admin_key, require_n8n_secret
from app.db.supabase import SupabaseError, get_supabase
from app.repositories.cases import (
    delete_case,
    find_case_by_message_id,
    get_case,
    get_pending_drafts,
    insert_case,
    insert_event,
    update_case,
)
from app.services.agent2 import process_case
from app.services.billing import run_billing_if_resolved


router = APIRouter(prefix="/cases", tags=["cases"])


class CaseIntakeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Accept both our internal names and n8n-friendly aliases:
    # - from_email <-> from
    # - to_email <-> to
    # - email_subject <-> subject
    # - email_body <-> body_text
    source: str = Field(default="gmail", validation_alias=AliasChoices("source", "provider"))
    message_id: str
    thread_id: str | None = None
    from_email: str | None = Field(default=None, validation_alias=AliasChoices("from_email", "from"))
    to_email: str | None = Field(default=None, validation_alias=AliasChoices("to_email", "to"))
    email_subject: str = Field(default="", validation_alias=AliasChoices("email_subject", "subject"))
    email_body: str = Field(default="", validation_alias=AliasChoices("email_body", "body_text"))

    vendor: str | None = None
    category: str | None = None
    estimated_value: Decimal | None = None
    flight_number: str | None = None
    booking_reference: str | None = None
    incident_date: str | None = None  # ISO date (YYYY-MM-DD)

    extracted_fields: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_n8n_payload(cls, data: Any) -> Any:
        # Accept older/alternate shapes coming from n8n "convert to JSON" nodes:
        # - from/to as [{name,email}, ...] -> pick first email
        # - body: {text, html} -> use body.text as body_text
        if not isinstance(data, dict):
            return data

        normalized = dict(data)

        # Normalize empty strings to None for email fields (Fix 2)
        for key in ("from", "from_email", "to", "to_email"):
            value = normalized.get(key)
            if isinstance(value, str) and not value.strip():
                normalized[key] = None

        # Handle from/to as list of objects with email property
        for key in ("from", "to"):
            value = normalized.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                email = value[0].get("email")
                if isinstance(email, str) and email.strip():
                    normalized[key] = email.strip()
                else:
                    normalized[key] = None

        if "body_text" not in normalized and "email_body" not in normalized:
            body = normalized.get("body")
            if isinstance(body, dict):
                text = body.get("text")
                if isinstance(text, str) and text.strip():
                    normalized["body_text"] = text

        extracted_fields = normalized.get("extracted_fields")
        if not isinstance(extracted_fields, dict):
            extracted_fields = {}
            normalized["extracted_fields"] = extracted_fields

        # Accept snippet as body fallback when text/plain extraction is empty.
        snippet = normalized.get("snippet")
        if not isinstance(snippet, str) or not snippet.strip():
            snippet = extracted_fields.get("snippet") if isinstance(extracted_fields.get("snippet"), str) else ""

        body_text = normalized.get("body_text") or normalized.get("email_body")
        if not isinstance(body_text, str) or not body_text.strip():
            if isinstance(snippet, str) and snippet.strip():
                normalized["body_text"] = snippet.strip()
            else:
                # Ensure body field exists even if empty
                normalized["body_text"] = normalized.get("body_text") or ""
        else:
            # Ensure both aliases are set
            if "body_text" not in normalized:
                normalized["body_text"] = body_text
            if "email_body" not in normalized:
                normalized["email_body"] = body_text

        # Subject fallback when n8n fails to map headers.
        # Don't use body text/snippet as subject - only use explicit subject fields
        subject_value = normalized.get("subject") or normalized.get("email_subject")
        if not isinstance(subject_value, str) or not subject_value.strip():
            # Only use extracted_fields.subject if it exists, don't fallback to snippet/body
            subject_hint = extracted_fields.get("subject") if isinstance(extracted_fields.get("subject"), str) else None
            if subject_hint and subject_hint.strip():
                normalized["subject"] = subject_hint.strip()
            else:
                # Ensure subject field exists even if empty
                normalized["subject"] = normalized.get("subject") or ""
        else:
            # Ensure both aliases are set
            if "subject" not in normalized:
                normalized["subject"] = subject_value
            if "email_subject" not in normalized:
                normalized["email_subject"] = subject_value

        return normalized

    @model_validator(mode="after")
    def ensure_email_fields(self) -> "CaseIntakeRequest":
        """Ensure from_email and to_email have fallback values (Fix 1)"""
        if not self.from_email or not self.from_email.strip():
            self.from_email = "unknown@unknown.local"
        if not self.to_email or not self.to_email.strip():
            self.to_email = "unknown@unknown.local"
        return self


class CaseIntakeResponse(BaseModel):
    id: str
    status: str
    case: dict[str, Any]
    existing: bool = False


def _generate_form_pdf(draft_body: str, vendor: str | None = None) -> bytes:
    """
    Generate a PDF form from structured draft body text.
    Parses the format: "Booking Reference: ...\nFlight Number: ...\nComplaint Summary: ..."
    Returns PDF as bytes.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=30,
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#333333'),
        spaceAfter=12,
        spaceBefore=20,
    )
    field_style = ParagraphStyle(
        'CustomField',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#000000'),
        spaceAfter=8,
        leftIndent=20,
    )
    value_style = ParagraphStyle(
        'CustomValue',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#000000'),
        spaceAfter=15,
        leftIndent=40,
        fontName='Helvetica-Bold',
    )
    
    # Title
    title = "Compensation Claim Form"
    if vendor:
        title += f" - {vendor}"
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 0.3 * inch))
    
    # Parse structured text format
    booking_ref = ""
    flight_number = ""
    complaint_summary = ""
    
    lines = draft_body.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("Booking Reference:"):
            booking_ref = line.replace("Booking Reference:", "").strip()
        elif line.startswith("Flight Number:"):
            flight_number = line.replace("Flight Number:", "").strip()
        elif line.startswith("Complaint Summary:"):
            # Get everything after "Complaint Summary:"
            complaint_summary = line.replace("Complaint Summary:", "").strip()
            # Check if there are more lines for the summary
            idx = lines.index(line) if line in lines else -1
            if idx >= 0 and idx + 1 < len(lines):
                # Collect remaining lines as part of summary
                remaining = "\n".join(lines[idx + 1:]).strip()
                if remaining:
                    complaint_summary = complaint_summary + "\n" + remaining if complaint_summary else remaining
    
    # Booking Reference
    if booking_ref:
        story.append(Paragraph("<b>Booking Reference:</b>", heading_style))
        story.append(Paragraph(booking_ref, value_style))
    
    # Flight Number
    if flight_number:
        story.append(Paragraph("<b>Flight Number:</b>", heading_style))
        story.append(Paragraph(flight_number, value_style))
    
    # Complaint Summary
    if complaint_summary:
        story.append(Paragraph("<b>Complaint Summary:</b>", heading_style))
        # Split into paragraphs for better formatting
        summary_paragraphs = complaint_summary.split("\n\n")
        for para in summary_paragraphs:
            if para.strip():
                # Escape HTML and wrap text
                para_escaped = para.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(para_escaped, field_style))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.read()


class PendingDraftResponse(BaseModel):
    id: str
    to: str
    subject: str
    body_text: str
    form_data: dict[str, Any] | None = None
    thread_id: str | None = None
    message_id: str | None = None
    case_id: str
    vendor: str | None = None
    category: str | None = None
    submission_type: Literal["email", "form"] = "email"
    form_url: str | None = None
    pdf_data: str | None = None  # Base64 encoded PDF


@router.post("/intake", response_model=CaseIntakeResponse)
def intake_case(payload: CaseIntakeRequest, _: None = Depends(require_n8n_secret)) -> CaseIntakeResponse:
    db = get_supabase()
    try:
        existing = find_case_by_message_id(db, payload.message_id)
        if existing:
            return CaseIntakeResponse(id=existing["id"], status=existing.get("status", ""), case=existing, existing=True)

        # Ensure email fields are always strings (validator should handle this, but double-check)
        from_email = payload.from_email or "unknown@unknown.local"
        to_email = payload.to_email or "unknown@unknown.local"
        email_subject = payload.email_subject or ""
        email_body = payload.email_body or ""

        created = insert_case(
            db,
            source=payload.source,
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            from_email=from_email,
            to_email=to_email,
            email_subject=email_subject,
            email_body=email_body,
            vendor=payload.vendor,
            category=payload.category,
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
                "extracted_fields": payload.extracted_fields or {},
            },
        )

        agent2_result = process_case(created, extracted_fields=payload.extracted_fields)
        updated = update_case(db, created["id"], agent2_result.case_updates)

        for event_type, details in agent2_result.events:
            insert_event(db, case_id=created["id"], actor="agent2", event_type=event_type, details=details)

        # If category is "unknown", delete the case so it doesn't appear on dashboard
        if updated.get("category") == "unknown":
            delete_case(db, created["id"])
            # Return a response indicating the case was deleted
            return CaseIntakeResponse(
                id=created["id"],
                status="deleted",
                case={"id": created["id"], "category": "unknown", "deleted": True},
            )

        return CaseIntakeResponse(id=updated["id"], status=updated.get("status", ""), case=updated)
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc
    except Exception as exc:  # noqa: BLE001
        # Catch any unexpected errors and log them properly
        import traceback
        error_msg = str(exc)
        error_type = type(exc).__name__
        # Only include traceback in detail if it's safe to serialize
        try:
            tb_str = traceback.format_exc()
        except Exception:  # noqa: BLE001
            tb_str = "Traceback unavailable"
        
        # Ensure detail is JSON-serializable
        error_details = {
            "error": error_msg,
            "type": error_type,
        }
        # Log the full traceback to help debug, but don't send it in response
        print(f"ERROR in /cases/intake: {error_type}: {error_msg}")
        print(tb_str)
        
        raise HTTPException(status_code=500, detail=error_details) from exc


class ApproveRequest(BaseModel):
    approved_by: str | None = None
    notes: str | None = None
    send_via: Literal["email", "form"] = "email"
    dry_run: bool = False


class ApproveResponse(BaseModel):
    id: str
    status: str
    case: dict[str, Any]


@router.post("/{case_id}/approve", response_model=ApproveResponse)
def approve_case(case_id: UUID, payload: ApproveRequest, _: None = Depends(require_admin_key)) -> ApproveResponse:
    db = get_supabase()
    try:
        case = get_case(db, str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        draft_subject = case.get("draft_email_subject")
        draft_body = case.get("draft_email_body")
        if not draft_subject or not draft_body:
            raise HTTPException(status_code=409, detail="No draft available to approve")

        # If Agent2 found a better contact email (e.g. marketplace contact page), use it.
        form_data = case.get("form_data")
        contact_email: str | None = None
        if isinstance(form_data, dict):
            contact_email = form_data.get("contact_email")
        elif isinstance(form_data, str):
            try:
                import json as _json

                parsed = _json.loads(form_data)
                if isinstance(parsed, dict):
                    contact_email = parsed.get("contact_email")
            except Exception:  # noqa: BLE001
                contact_email = None

        to_email = case.get("from_email")
        if payload.send_via == "email" and contact_email:
            to_email = contact_email

        if not settings.agent1_send_webhook_url and not payload.dry_run:
            raise HTTPException(
                status_code=409, detail="AGENT1_SEND_WEBHOOK_URL not configured (or set dry_run=true)"
            )

        webhook_ran = False
        webhook_status: int | None = None
        webhook_error: str | None = None

        if settings.agent1_send_webhook_url and not payload.dry_run:
            try:
                webhook_ran = True
                resp = httpx.post(
                    settings.agent1_send_webhook_url,
                    json={
                        "case_id": case["id"],
                        "send_via": payload.send_via,
                        # For hackathon: reply to the vendor email address we received.
                        "to_email": to_email,
                        "subject": draft_subject,
                        "body": draft_body,
                        "form_data": case.get("form_data"),
                        "thread_id": case.get("thread_id"),
                        "message_id": case.get("message_id"),
                    },
                    timeout=20,
                )
                webhook_status = resp.status_code
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - we want to surface n8n errors clearly
                webhook_error = str(exc)

        if webhook_error:
            insert_event(
                db,
                case_id=case["id"],
                actor="system",
                event_type="submission_failed",
                details={
                    "approved_by": payload.approved_by,
                    "notes": payload.notes,
                    "send_via": payload.send_via,
                    "to_email": to_email,
                    "dry_run": payload.dry_run,
                    "agent1_webhook": {
                        "configured": bool(settings.agent1_send_webhook_url),
                        "ran": webhook_ran,
                        "status": webhook_status,
                        "error": webhook_error,
                    },
                },
            )
            raise HTTPException(status_code=502, detail={"error": "Agent1 webhook failed", "details": webhook_error})

        updated = update_case(db, case["id"], {"status": "submitted_to_vendor"})
        insert_event(
            db,
            case_id=case["id"],
            actor="system",
            event_type="submitted_to_vendor",
            details={
                "approved_by": payload.approved_by,
                "notes": payload.notes,
                "send_via": payload.send_via,
                "to_email": to_email,
                "dry_run": payload.dry_run,
                "agent1_webhook": {
                    "configured": bool(settings.agent1_send_webhook_url),
                    "ran": webhook_ran,
                    "status": webhook_status,
                    "error": webhook_error,
                },
            },
        )

        return ApproveResponse(id=updated["id"], status=updated.get("status", ""), case=updated)
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc


class VendorResponseRequest(BaseModel):
    outcome: Literal["accepted", "rejected", "needs_info", "unknown"] = "unknown"
    resolved: bool | None = None
    recovered_amount: Decimal | None = None
    currency: str | None = "eur"
    evidence: dict[str, Any] | None = None
    message_id: str | None = None
    thread_id: str | None = None


class VendorResponseResponse(BaseModel):
    id: str
    status: str
    case: dict[str, Any]


@router.post("/{case_id}/vendor_response", response_model=VendorResponseResponse)
def vendor_response(case_id: UUID, payload: VendorResponseRequest, _: None = Depends(require_n8n_secret)) -> VendorResponseResponse:
    db = get_supabase()
    try:
        case = get_case(db, str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        status_map = {
            "accepted": "resolved",
            "rejected": "rejected",
            "needs_info": "needs_info",
            "unknown": "vendor_replied",
        }
        next_status = status_map[payload.outcome]
        if payload.resolved is True:
            next_status = "resolved"

        decision_json = case.get("decision_json") or {}
        decision_json["vendor_response"] = {
            "outcome": payload.outcome,
            "resolved": payload.resolved,
            "recovered_amount": float(payload.recovered_amount) if payload.recovered_amount is not None else None,
            "currency": payload.currency,
            "evidence": payload.evidence or {},
            "message_id": payload.message_id,
            "thread_id": payload.thread_id,
        }

        updates: dict[str, Any] = {"status": next_status, "decision_json": decision_json}
        if payload.recovered_amount is not None:
            # Pragmatic hackathon choice: reuse estimated_value as "known recovered amount" once resolved.
            updates["estimated_value"] = float(payload.recovered_amount)

        updated = update_case(db, case["id"], updates)
        insert_event(
            db,
            case_id=case["id"],
            actor="agent1",
            event_type="vendor_replied",
            details=decision_json["vendor_response"],
        )

        if next_status == "resolved":
            run_billing_if_resolved(updated, recovered_amount=payload.recovered_amount, currency=payload.currency)
            updated = get_case(db, case["id"]) or updated
            return VendorResponseResponse(id=updated["id"], status=updated.get("status", ""), case=updated)

        return VendorResponseResponse(id=updated["id"], status=updated.get("status", ""), case=updated)
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc


class RunAgent2Response(BaseModel):
    id: str
    status: str
    case: dict[str, Any]


@router.post("/{case_id}/run_agent2", response_model=RunAgent2Response)
def run_agent2(case_id: UUID, _: None = Depends(require_admin_key)) -> RunAgent2Response:
    db = get_supabase()
    try:
        case = get_case(db, str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        agent2_result = process_case(case)
        updated = update_case(db, case["id"], agent2_result.case_updates)
        insert_event(db, case_id=case["id"], actor="agent2", event_type="agent2_reprocessed", details={})
        for event_type, details in agent2_result.events:
            insert_event(db, case_id=case["id"], actor="agent2", event_type=event_type, details=details)

        return RunAgent2Response(id=updated["id"], status=updated.get("status", ""), case=updated)
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc


@router.get("/email-drafts/pending", response_model=list[PendingDraftResponse])
def get_pending_drafts_endpoint(_: None = Depends(require_n8n_secret)) -> list[PendingDraftResponse]:
    """
    Get all email drafts ready to send (awaiting approval).
    Returns cases with status='awaiting_approval' that have draft emails.
    n8n should poll this endpoint and send the emails via Gmail.
    """
    db = get_supabase()
    try:
        cases = get_pending_drafts(db, limit=100)

        drafts = []
        for case in cases:
            # Determine the 'to' email - prefer contact_email from form_data, fallback to from_email
            to_email = case.get("from_email") or "unknown@unknown.local"

            form_data = case.get("form_data")
            form_url = None
            submission_type: Literal["email", "form"] = "email"
            draft_body = case.get("draft_email_body") or ""

            # Extract form_data and check URL to determine submission type
            if isinstance(form_data, dict):
                contact_email = form_data.get("contact_email")
                if contact_email and isinstance(contact_email, str):
                    to_email = contact_email
                form_url = form_data.get("form_url")
            elif isinstance(form_data, str):
                try:
                    import json as _json
                    parsed = _json.loads(form_data)
                    if isinstance(parsed, dict):
                        contact_email = parsed.get("contact_email")
                        if contact_email and isinstance(contact_email, str):
                            to_email = contact_email
                        form_url = parsed.get("form_url")
                except Exception:  # noqa: BLE001
                    pass

            # Check if draft body is in form format (starts with "Booking Reference:")
            # or check URL: airline-claim.html → form
            pdf_data = None
            if draft_body.startswith("Booking Reference:") or (form_url and "airline-claim.html" in form_url):
                submission_type = "form"
                # Generate PDF from draft body
                try:
                    pdf_bytes = _generate_form_pdf(draft_body, vendor=case.get("vendor"))
                    pdf_data = base64.b64encode(pdf_bytes).decode("utf-8")
                except Exception as exc:  # noqa: BLE001
                    # Log error but don't fail - PDF generation is optional
                    import logging
                    logging.error(f"Failed to generate PDF for case {case['id']}: {exc}")

            drafts.append(
                PendingDraftResponse(
                    id=case["id"],
                    case_id=case["id"],
                    to=to_email,
                    subject=case.get("draft_email_subject") or "",
                    body_text=draft_body,
                    form_data=form_data if isinstance(form_data, dict) else None,
                    thread_id=case.get("thread_id"),
                    message_id=case.get("message_id"),
                    vendor=case.get("vendor"),
                    category=case.get("category"),
                    submission_type=submission_type,
                    form_url=form_url,
                    pdf_data=pdf_data,
                )
            )

        return drafts
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc
    except Exception as exc:  # noqa: BLE001
        import traceback

        error_details = {
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        }
        raise HTTPException(status_code=500, detail=error_details) from exc


@router.post("/email-drafts/{case_id}/mark-sent", response_model=dict[str, Any])
def mark_draft_sent(case_id: UUID, _: None = Depends(require_n8n_secret)) -> dict[str, Any]:
    """
    Mark a draft as sent (update status to 'submitted_to_vendor').
    Call this after successfully sending the email or submitting the form.
    """
    db = get_supabase()
    try:
        case = get_case(db, str(case_id))
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        if case.get("status") != "awaiting_approval":
            raise HTTPException(
                status_code=409,
                detail=f"Case status is '{case.get('status')}', expected 'awaiting_approval'",
            )

        updated = update_case(db, str(case_id), {"status": "submitted_to_vendor"})
        insert_event(
            db,
            case_id=str(case_id),
            actor="agent1",
            event_type="submitted_to_vendor",
            details={"sent_via": "email", "marked_by": "n8n_polling"},
        )

        return {"id": updated["id"], "status": updated.get("status")}
    except SupabaseError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "supabase": exc.body}) from exc

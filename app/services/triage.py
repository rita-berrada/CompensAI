from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.services.claude_client import ALLOWED_CATEGORIES


Decision = Literal["trash", "candidate"]
DomainHint = Literal["flights", "marketplace", "trains"]


class TriageHints(BaseModel):
    domain: DomainHint | None = None
    category_hint: str | None = None
    issue_tags: list[str] = Field(default_factory=list)
    vendor_hint: str | None = None


class TriageOutput(BaseModel):
    decision: Decision
    confidence: float = 0.5
    reasons: list[str] = Field(default_factory=list)
    hints: TriageHints = Field(default_factory=TriageHints)


@dataclass(frozen=True)
class TriageResult:
    output: dict[str, Any]
    model: str
    usage: dict[str, Any]
    error: str | None


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in Claude response")
    return match.group(0)


def _fallback_triage(subject: str, body_text: str) -> TriageResult:
    text = f"{subject}\n{body_text}".lower()

    security_notification_keywords = [
        "google account",
        "security alert",
        "new sign-in",
        "new login",
        "suspicious activity",
        "password reset",
        "2-step verification",
        "verification code",
        "device sign-in",
    ]
    promo_keywords = [
        "unsubscribe",
        "newsletter",
        "sale",
        "discount",
        "promo",
        "promotion",
        "limited time",
        "deal",
        "offer",
    ]
    candidate_keywords = [
        # flights
        "flight",
        "delayed",
        "delay",
        "cancelled",
        "canceled",
        "cancellation",
        "denied boarding",
        "overbook",
        "overbooking",
        "bumped",
        "baggage",
        "luggage",
        # delivery/marketplace
        "delivery",
        "delivered",
        "parcel",
        "tracking",
        "order",
        "missing",
        "not received",
        "never arrived",
        "damaged",
        "broken",
        # trains
        "train",
        "rail",
    ]
    intent_keywords = ["refund", "compensation", "claim", "reimburse", "chargeback", "complaint"]

    promo_hits = [k for k in promo_keywords if k in text]
    security_hits = [k for k in security_notification_keywords if k in text]
    candidate_hits = [k for k in candidate_keywords if k in text]
    intent_hits = [k for k in intent_keywords if k in text]

    if security_hits and not candidate_hits:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.95,
                reasons=[f"Account/security notification indicators: {', '.join(security_hits[:5])}"],
                hints=TriageHints(issue_tags=["account-notification"]),
            ).model_dump(),
            model="fallback",
            usage={},
            error="Claude unavailable; used fallback triage",
        )

    # If clearly promotional, trash it.
    if "unsubscribe" in text and len(promo_hits) >= 2 and not intent_hits:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.9,
                reasons=[f"Promotional email indicators: {', '.join(promo_hits[:5])}"],
                hints=TriageHints(issue_tags=["promotional"]),
            ).model_dump(),
            model="fallback",
            usage={},
            error="Claude unavailable; used fallback triage",
        )

    # Otherwise, prefer candidate (demo-safe).
    reasons: list[str] = []
    if candidate_hits:
        reasons.append(f"Contains issue keywords: {', '.join(candidate_hits[:6])}")
    if intent_hits:
        reasons.append(f"Contains intent keywords: {', '.join(intent_hits[:6])}")
    if not reasons:
        reasons.append("Uncertain; defaulting to candidate for demo safety.")

    # Light hinting only; do not force category/domain for marketplace.
    hints = TriageHints(issue_tags=[])
    if any(k in text for k in ["flight", "eu261", "boarding", "gate"]):
        hints.domain = "flights"
    if any(k in text for k in ["train", "rail", "platform"]):
        hints.domain = "trains"
    if any(k in text for k in ["delivery", "order", "tracking", "parcel"]):
        hints.domain = "marketplace"

    # Add free-form tags for marketplace-like issues (no category_hint forced)
    if "damaged" in text or "broken" in text:
        hints.issue_tags.append("damaged package")
    if "missing" in text or "not received" in text or "never arrived" in text:
        hints.issue_tags.append("missing delivery")
    if "late" in text or "delayed" in text:
        hints.issue_tags.append("delay")
    if "refund" in text:
        hints.issue_tags.append("refund request")

    return TriageResult(
        output=TriageOutput(decision="candidate", confidence=0.6, reasons=reasons, hints=hints).model_dump(),
        model="fallback",
        usage={},
        error="Claude unavailable; used fallback triage",
    )


def triage_email(
    *,
    subject: str,
    body_text: str,
    from_email: str | None = None,
    extracted_fields: dict[str, Any] | None = None,
) -> TriageResult:
    if not settings.anthropic_api_key:
        return _fallback_triage(subject, body_text)

    try:
        from anthropic import Anthropic  # type: ignore
    except Exception:
        return _fallback_triage(subject, body_text)

    prompt_context = {
        "from_email": from_email or "",
        "email_subject": subject,
        "email_body": body_text,
        "extracted_fields": extracted_fields or {},
    }

    instructions = (
        "You are a triage classifier for potential compensation/claims emails.\n"
        "Goal: decide if this email should create a case (candidate) or be ignored (trash).\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{"
        "\"decision\": \"trash\"|\"candidate\", "
        "\"confidence\": number, "
        "\"reasons\": string[], "
        "\"hints\": {"
        "\"domain\": \"flights\"|\"marketplace\"|\"trains\"|null, "
        "\"category_hint\": string|null, "
        "\"issue_tags\": string[], "
        "\"vendor_hint\": string|null"
        "}"
        "}\n"
        "Notes:\n"
        "- Hints are optional; it's OK to set them to null/empty.\n"
        "- For marketplace/delivery emails, prefer using free-form issue_tags like "
        "\"late delivery\" or \"damaged package\" and leave category_hint null if unsure.\n"
        "- Treat account/security notifications (login alerts, verification codes, auth warnings) as trash.\n"
        "- If you set category_hint, it should be one of these values: "
        + ", ".join(sorted(ALLOWED_CATEGORIES))
        + "\n"
        "- If uncertain overall, choose decision='candidate' (demo safety).\n"
    )

    try:
        client = Anthropic(api_key=settings.anthropic_api_key, timeout=settings.anthropic_timeout_seconds)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=500,
            temperature=0,
            system=instructions,
            messages=[{"role": "user", "content": json.dumps(prompt_context, ensure_ascii=True)}],
        )
        text_parts: list[str] = []
        for block in response.content:
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str):
                text_parts.append(block_text)
        raw_text = "\n".join(text_parts).strip()
        payload = json.loads(_extract_json_object(raw_text))

        parsed = TriageOutput.model_validate(payload)
        if parsed.hints.category_hint and parsed.hints.category_hint not in ALLOWED_CATEGORIES:
            parsed.hints.category_hint = None

        usage = {
            "input_tokens": getattr(response.usage, "input_tokens", None),
            "output_tokens": getattr(response.usage, "output_tokens", None),
        }
        return TriageResult(
            output=parsed.model_dump(),
            model=getattr(response, "model", settings.anthropic_model),
            usage=usage,
            error=None,
        )
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        fallback = _fallback_triage(subject, body_text)
        return TriageResult(output=fallback.output, model=settings.anthropic_model, usage={}, error=f"Triage parse failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        fallback = _fallback_triage(subject, body_text)
        return TriageResult(output=fallback.output, model=settings.anthropic_model, usage={}, error=f"Triage Claude call failed: {exc}")

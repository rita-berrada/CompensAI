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

    # Personal/casual keywords that indicate non-claim emails
    personal_keywords = [
        "how are you",
        "how are you?",
        "hi there",
        "hello there",
        "hey there",
        "hey ",
        "just checking",
        "just wanted to say",
        "hope you're well",
        "hope all is well",
        "don't forget",
        "remember to",
        "see you",
        "catch up",
        "meeting",
        "meeting today",
        "meeting tomorrow",
        "call you",
        "call me",
        "thanks",
        "thank you",
        "thanks!",
        "thank you!",
        "regards",
        "best regards",
        "sincerely",
        "talk soon",
        "speak soon",
        "let's",
        "let me know",
    ]
    
    # Check for very short/casual emails that are clearly not claims
    text_length = len(text.strip())
    is_very_short = text_length < 100
    is_casual_greeting = any(phrase in text for phrase in personal_keywords)
    
    # Count how many personal keywords appear (more = more likely personal)
    personal_hits = sum(1 for phrase in personal_keywords if phrase in text)
    
    # If it has multiple personal keywords and no claim keywords, definitely trash
    if personal_hits >= 2 and not candidate_hits and not intent_hits:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.95,
                reasons=[f"Personal/casual email with {personal_hits} personal indicators and no claim keywords"],
                hints=TriageHints(issue_tags=["casual-email", "personal"]),
            ).model_dump(),
            model="fallback",
            usage={},
            error="Claude unavailable; used fallback triage",
        )

    # If it's a very short casual email with no claim keywords, trash it
    if is_very_short and is_casual_greeting and not candidate_hits and not intent_hits:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.9,
                reasons=["Very short casual email with no compensation/claim keywords"],
                hints=TriageHints(issue_tags=["casual-email"]),
            ).model_dump(),
            model="fallback",
            usage={},
            error="Claude unavailable; used fallback triage",
        )

    # If it has personal keywords AND is short/medium length with no claim context, trash it
    if is_casual_greeting and text_length < 200 and not candidate_hits and not intent_hits:
        # Check if it contains any business/claim context words
        has_business_context = any(
            k in text
            for k in [
                "flight",
                "train",
                "delivery",
                "order",
                "booking",
                "ticket",
                "reservation",
                "delay",
                "cancel",
                "refund",
                "compensation",
                "claim",
                "disruption",
                "airline",
                "vendor",
            ]
        )
        if not has_business_context:
            return TriageResult(
                output=TriageOutput(
                    decision="trash",
                    confidence=0.88,
                    reasons=["Personal/casual email with no business or claim-related context"],
                    hints=TriageHints(issue_tags=["casual-email", "personal"]),
                ).model_dump(),
                model="fallback",
                usage={},
                error="Claude unavailable; used fallback triage",
            )

    # If very short and no relevant keywords at all, trash it
    if is_very_short and not candidate_hits and not intent_hits and not any(
        k in text for k in ["flight", "train", "delivery", "order", "booking", "ticket", "reservation"]
    ):
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.85,
                reasons=["Very short email with no compensation-related keywords"],
                hints=TriageHints(issue_tags=["non-claim"]),
            ).model_dump(),
            model="fallback",
            usage={},
            error="Claude unavailable; used fallback triage",
        )

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

    # Only mark as candidate if there are actual claim-related keywords
    reasons: list[str] = []
    if candidate_hits:
        reasons.append(f"Contains issue keywords: {', '.join(candidate_hits[:6])}")
    if intent_hits:
        reasons.append(f"Contains intent keywords: {', '.join(intent_hits[:6])}")
    
    # If no relevant keywords found, trash it instead of defaulting to candidate
    if not reasons:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.7,
                reasons=["No compensation/claim-related keywords found in email"],
                hints=TriageHints(issue_tags=["non-claim"]),
            ).model_dump(),
            model="fallback",
            usage={},
            error="Claude unavailable; used fallback triage",
        )

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


def _quick_precheck_trash(subject: str, body_text: str) -> TriageResult | None:
    """
    Quick pre-check to catch obvious trash emails before calling Claude.
    Returns TriageResult if it's clearly trash, None if we should proceed to Claude.
    """
    text = f"{subject}\n{body_text}".lower()
    text_length = len(text.strip())
    
    # Personal/casual keywords - expanded list (MUST catch all personal emails)
    personal_keywords = [
        "how are you",
        "hi there",
        "hello there",
        "hey there",
        "hey ",
        "hi ",
        "hello ",
        "hi,",
        "hello,",
        "hey,",
        "hi rita",
        "hello rita",
        "hey rita",
        "don't forget",
        "dont forget",
        "remember to",
        "meeting",
        "meeting today",
        "meeting tomorrow",
        "meeting next",
        "meeting ",
        "hope this mail finds you",
        "hope this email finds you",
        "hope you're well",
        "hope all is well",
        "catch up",
        "see you",
        "call you",
        "call me",
        "talk soon",
        "speak soon",
        "best,",
        "best\n",
        "best ",
        "best regards",
        "regards,",
        "sincerely",
        "thanks,",
        "thank you,",
        "cheers",
        "tomorrow",  # Common in personal reminders
    ]
    
    # Claim-related keywords that would make it a candidate
    claim_keywords = [
        "flight",
        "delayed",
        "delay",
        "cancelled",
        "canceled",
        "cancellation",
        "denied boarding",
        "overbook",
        "baggage",
        "luggage",
        "delivery",
        "parcel",
        "tracking",
        "order",
        "refund",
        "compensation",
        "claim",
        "reimburse",
        "chargeback",
        "complaint",
        "disruption",
        "booking",
        "ticket",
        "reservation",
    ]
    
    personal_hits = sum(1 for phrase in personal_keywords if phrase in text)
    claim_hits = sum(1 for phrase in claim_keywords if phrase in text)
    
    # DEBUG: Log what we found (remove in production)
    # print(f"DEBUG: text={text[:100]}, personal_hits={personal_hits}, claim_hits={claim_hits}")
    
    # ULTRA STRICT RULE #1: If ANY personal keyword and NO claim keywords → TRASH immediately
    # This is the MOST IMPORTANT rule - catches "Hi Rita, meeting tomorrow"
    if personal_hits >= 1 and claim_hits == 0:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.99,  # Maximum confidence
                reasons=[f"Pre-check BLOCKED: Personal/casual email with {personal_hits} personal indicator(s) and ZERO claim keywords"],
                hints=TriageHints(issue_tags=["casual-email", "personal", "blocked-by-precheck"]),
            ).model_dump(),
            model="precheck",
            usage={},
            error=None,
        )
    
    # ULTRA STRICT RULE #2: Very short emails with no claim keywords
    if text_length < 150 and claim_hits == 0:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.95,
                reasons=["Pre-check: Short email with no compensation-related keywords"],
                hints=TriageHints(issue_tags=["non-claim"]),
            ).model_dump(),
            model="precheck",
            usage={},
            error=None,
        )
    
    # ULTRA STRICT RULE #3: If no claim keywords at all and email is not very long, likely trash
    if claim_hits == 0 and text_length < 400:
        return TriageResult(
            output=TriageOutput(
                decision="trash",
                confidence=0.9,
                reasons=["Pre-check: No claim-related keywords found in email"],
                hints=TriageHints(issue_tags=["non-claim"]),
            ).model_dump(),
            model="precheck",
            usage={},
            error=None,
        )
    
    return None


def triage_email(
    *,
    subject: str,
    body_text: str,
    from_email: str | None = None,
    extracted_fields: dict[str, Any] | None = None,
) -> TriageResult:
    # Run pre-check first - if it says trash, ALWAYS use it (no exceptions)
    precheck_result = _quick_precheck_trash(subject, body_text)
    if precheck_result and precheck_result.output and precheck_result.output.get("decision") == "trash":
        # ALWAYS use pre-check result if it says trash - no confidence threshold, no exceptions
        return precheck_result
    
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
        "CRITICAL RULES - Mark as TRASH if:\n"
        "- Email is personal/casual (greetings, 'how are you', 'meeting', 'don't forget', etc.) with NO claim-related content\n"
        "- Email is very short (<100 chars) with no compensation keywords\n"
        "- Email contains personal conversation, reminders, or social messages\n"
        "- Email is an account/security notification\n"
        "- Email is promotional/marketing\n"
        "- Email has NO mention of: flights, delays, cancellations, deliveries, orders, refunds, compensation, claims, disruptions\n"
        "\n"
        "ONLY mark as CANDIDATE if:\n"
        "- Email explicitly mentions flight/train/delivery issues, delays, cancellations, refunds, or compensation claims\n"
        "- Email contains booking references, flight numbers, order numbers, or tracking numbers in a claim context\n"
        "- Email is clearly a business communication about a service disruption\n"
        "\n"
        "Notes:\n"
        "- Hints are optional; it's OK to set them to null/empty.\n"
        "- For marketplace/delivery emails, prefer using free-form issue_tags like "
        "\"late delivery\" or \"damaged package\" and leave category_hint null if unsure.\n"
        "- If you set category_hint, it should be one of these values: "
        + ", ".join(sorted(ALLOWED_CATEGORIES))
        + "\n"
        "- When in doubt, ALWAYS choose 'trash' to avoid false positives. Only 'candidate' if clearly a claim.\n"
        "- You MUST set confidence >= 0.7 for candidate decisions. Lower confidence = mark as trash.\n"
        "- If email is ambiguous or unclear, mark as trash.\n"
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

        # Post-validation: If Claude marked as candidate, verify it has claim indicators
        if parsed.decision == "candidate":
            combined_text = f"{subject}\n{body_text}".lower()
            claim_indicators = [
                "flight", "delayed", "delay", "cancelled", "canceled", "cancellation",
                "denied boarding", "overbook", "baggage", "luggage",
                "delivery", "parcel", "tracking", "order", "missing", "damaged", "broken",
                "refund", "compensation", "claim", "reimburse", "chargeback",
                "complaint", "disruption", "booking", "ticket", "reservation",
                "train", "rail", "eu261", "airline", "vendor"
            ]
            has_claim_indicator = any(indicator in combined_text for indicator in claim_indicators)
            
            # If no clear indicators or low confidence, override to trash
            current_confidence = parsed.confidence or 0.0
            if not has_claim_indicator or current_confidence < 0.7:
                parsed.decision = "trash"
                parsed.confidence = max(0.85, current_confidence)
                reason = (
                    "Post-validation: No clear claim indicators found" if not has_claim_indicator
                    else f"Post-validation: Low confidence ({current_confidence}) candidate rejected"
                )
                if not parsed.reasons:
                    parsed.reasons = []
                parsed.reasons.append(reason)

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

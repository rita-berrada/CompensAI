from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings


class ExtractionOutput(BaseModel):
    flight_number: str | None = None
    booking_reference: str | None = None
    incident_date: str | None = None
    delay_minutes: int | None = None
    route: dict[str, Any] = Field(default_factory=dict)
    vendor: str | None = None
    category: str | None = None
    order_number: str | None = None
    tracking_number: str | None = None
    operator: str | None = None


class EligibilityOutput(BaseModel):
    result: str
    reasons: list[str] = Field(default_factory=list)
    confidence: float | None = None


class ClaimOutput(BaseModel):
    estimated_value_eur: float | None = None
    basis: str = "EU261 simplified"


class DraftOutput(BaseModel):
    subject: str
    body: str
    preview: str = ""


class ClaudeAgent2Output(BaseModel):
    extraction: ExtractionOutput
    eligibility: EligibilityOutput
    claim: ClaimOutput
    draft: DraftOutput
    form_data: dict[str, Any] = Field(default_factory=dict)


ALLOWED_CATEGORIES = {
    "flight_delay",
    "flight_cancellation",
    "flight_denied_boarding",
    "flight_baggage",
    "delivery_late",
    "delivery_missing",
    "delivery_damaged",
    "train_delay",
    "train_cancellation",
    "train_baggage",
    "unknown",
}


@dataclass(frozen=True)
class ClaudeAgent2Response:
    output: dict[str, Any] | None
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


def run_claude_agent2(
    *,
    subject: str,
    body: str,
    extracted_fields: dict[str, Any] | None,
    kb: dict[str, Any],
    company_site: dict[str, Any] | None,
) -> ClaudeAgent2Response:
    if not settings.anthropic_api_key:
        return ClaudeAgent2Response(
            output=None,
            model=settings.anthropic_model,
            usage={},
            error="ANTHROPIC_API_KEY is not configured",
        )

    try:
        from anthropic import Anthropic  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return ClaudeAgent2Response(
            output=None,
            model=settings.anthropic_model,
            usage={},
            error=f"Anthropic SDK unavailable: {exc}",
        )

    prompt_context = {
        "email_subject": subject,
        "email_body": body,
        "extracted_fields": extracted_fields or {},
        "kb": kb,
        "company_site": company_site or {},
    }

    instructions = (
        "You are Agent2 helping a customer claim compensation.\n"
        "The email provided was written BY the customer to us — you are acting on behalf of that customer.\n"
        "draft.subject and draft.body MUST be written FROM the customer TO the airline/vendor, "
        "formally claiming compensation. Never write as if you are the company or customer support replying.\n"
        "Classify into one category from this list:\n"
        + ", ".join(sorted(ALLOWED_CATEGORIES))
        + "\n"
        "If uncertain, set extraction.category='unknown' and eligibility.result='needs_info'.\n"
        "If company_site contains policy text or form schema, use it.\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{"
        "\"extraction\": {\"flight_number\": string|null, \"booking_reference\": string|null, "
        "\"incident_date\": \"YYYY-MM-DD\"|null, \"delay_minutes\": int|null, \"route\": object, "
        "\"vendor\": string|null, \"category\": string|null, "
        "\"order_number\": string|null, \"tracking_number\": string|null, \"operator\": string|null}, "
        "\"eligibility\": {\"result\": string, \"reasons\": string[], \"confidence\": number|null}, "
        "\"claim\": {\"estimated_value_eur\": number|null, \"basis\": string}, "
        "\"draft\": {\"subject\": string, \"body\": string, \"preview\": string}, "
        "\"form_data\": {\"form_url\": string|null, \"contact_email\": string|null, "
        "\"fields_to_fill\": object, \"playwright_steps\": any, \"form_schema\": any}"
        "}"
    )

    try:
        client = Anthropic(api_key=settings.anthropic_api_key, timeout=settings.anthropic_timeout_seconds)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            temperature=0,
            system=instructions,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(prompt_context, ensure_ascii=True),
                }
            ],
        )
        text_parts = []
        for block in response.content:
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str):
                text_parts.append(block_text)
        raw_text = "\n".join(text_parts).strip()
        payload = json.loads(_extract_json_object(raw_text))
        parsed = ClaudeAgent2Output.model_validate(payload)
        usage = {
            "input_tokens": getattr(response.usage, "input_tokens", None),
            "output_tokens": getattr(response.usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", None),
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", None),
        }
        return ClaudeAgent2Response(
            output=parsed.model_dump(),
            model=getattr(response, "model", settings.anthropic_model),
            usage=usage,
            error=None,
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        return ClaudeAgent2Response(
            output=None,
            model=settings.anthropic_model,
            usage={},
            error=f"Claude response parsing failed: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return ClaudeAgent2Response(
            output=None,
            model=settings.anthropic_model,
            usage={},
            error=f"Claude call failed: {exc}",
        )

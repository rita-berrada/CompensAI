from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.claude_client import run_claude_agent2


@dataclass(frozen=True)
class Agent2Result:
    case_updates: dict[str, Any]
    events: list[tuple[str, dict[str, Any]]]


FALLBACK_EU261_RULES: dict[str, Any] = {
    "eligibility_rules": {
        "delay_minutes_threshold": 180,
        "possible_exclusions_keywords": [
            "extraordinary circumstances",
            "weather",
            "security risk",
            "air traffic control strike",
            "political instability",
        ],
    },
    "compensation_tiers_eur": [
        {"max_distance_km": 1500, "amount_eur": 250},
        {"max_distance_km": 3500, "amount_eur": 400},
        {"max_distance_km": None, "amount_eur": 600},
    ],
}


@lru_cache(maxsize=1)
def _load_eu261_rules() -> dict[str, Any]:
    kb_path = Path(__file__).resolve().parent.parent / "kb" / "eu261_rules.json"
    try:
        with kb_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:  # noqa: BLE001
        return FALLBACK_EU261_RULES


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _infer_vendor(subject: str, body: str) -> str | None:
    text = f"{subject}\n{body}".lower()
    for vendor in ["ryanair", "easyjet", "lufthansa", "klm", "air france", "british airways", "iberia", "wizz air"]:
        if vendor in text:
            return vendor.title()
    return None


def _infer_category(subject: str, body: str) -> str | None:
    text = f"{subject}\n{body}".lower()
    if any(k in text for k in ["cancelled", "canceled", "cancellation"]):
        return "flight_cancellation"
    if any(k in text for k in ["delay", "delayed", "late arrival"]):
        return "flight_delay"
    return None


def _parse_incident_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _normalize_category(value: str | None, subject: str, body: str) -> str:
    if value in {"flight_delay", "flight_cancellation"}:
        return value
    inferred = _infer_category(subject, body)
    if inferred in {"flight_delay", "flight_cancellation"}:
        return inferred
    return "unknown"


def _extract_delay_minutes(text: str, extracted_fields: dict[str, Any] | None) -> int | None:
    data = extracted_fields or {}
    if isinstance(data.get("delay_minutes"), (int, float)):
        return int(data["delay_minutes"])
    if isinstance(data.get("arrival_delay_minutes"), (int, float)):
        return int(data["arrival_delay_minutes"])
    if isinstance(data.get("delay_hours"), (int, float)):
        return int(float(data["delay_hours"]) * 60)

    delay_match = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)", text, flags=re.IGNORECASE)
    if delay_match:
        return int(delay_match.group(1)) * 60
    minute_match = re.search(r"(\d+)\s*(?:m|min|mins|minute|minutes)", text, flags=re.IGNORECASE)
    if minute_match:
        return int(minute_match.group(1))
    return None


def _extract_route(text: str, extracted_fields: dict[str, Any] | None) -> dict[str, Any]:
    route_value = (extracted_fields or {}).get("route")
    if isinstance(route_value, dict):
        return route_value
    route_match = re.search(r"\b([A-Z]{3})\s*(?:to|->)\s*([A-Z]{3})\b", text)
    if route_match:
        return {"from": route_match.group(1), "to": route_match.group(2)}
    return {}


def _extract_flight_number(text: str) -> str | None:
    match = re.search(r"\b([A-Z]{2}\d{1,4})\b", text)
    if match:
        return match.group(1)
    return None


def _extract_booking_reference(text: str) -> str | None:
    labeled_match = re.search(
        r"(?:booking(?:\s+reference)?|ref(?:erence)?)[:\s]+([A-Z0-9]{5,8})",
        text,
        flags=re.IGNORECASE,
    )
    if labeled_match:
        return labeled_match.group(1).upper()
    return None


def _extract_incident_date(text: str, existing_value: Any) -> date | None:
    parsed = _parse_incident_date(existing_value)
    if parsed:
        return parsed
    for pattern in [
        r"\b(20\d{2}-\d{2}-\d{2})\b",
        r"\b(\d{2}/\d{2}/20\d{2})\b",
    ]:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        if "/" in value:
            day, month, year = value.split("/")
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                continue
        parsed_iso = _parse_incident_date(value)
        if parsed_iso:
            return parsed_iso
    return None


def _contains_exclusion_keyword(text: str, rules: dict[str, Any]) -> bool:
    keywords = (((rules or {}).get("eligibility_rules") or {}).get("possible_exclusions_keywords") or [])
    lower = text.lower()
    for keyword in keywords:
        if str(keyword).lower() in lower:
            return True
    return False


def _eu261_simplified(
    *,
    category: str,
    incident: date | None,
    delay_minutes: int | None,
    body_text: str,
    rules: dict[str, Any],
) -> tuple[str, list[str], float]:
    reasons: list[str] = []
    if category not in {"flight_delay", "flight_cancellation"}:
        return "unknown", ["Category is outside current EU261 scope for Agent2."], 0.3

    if incident:
        years_ago = (date.today() - incident).days / 365.25
        if years_ago > 4:
            return "possibly_ineligible", [f"Incident date appears {years_ago:.1f} years old; may be time-barred."], 0.8

    if category == "flight_delay":
        threshold = int((((rules or {}).get("eligibility_rules") or {}).get("delay_minutes_threshold") or 180))
        if delay_minutes is None:
            return "needs_info", [f"Need arrival delay in minutes to evaluate >= {threshold} minutes threshold."], 0.55
        if delay_minutes >= threshold:
            return "eligible", [f"Arrival delay appears {delay_minutes} minutes (>= {threshold} minutes)."], 0.9
        return "possibly_ineligible", [f"Arrival delay appears {delay_minutes} minutes (< {threshold} minutes)."], 0.85

    if _contains_exclusion_keyword(body_text, rules):
        return "possibly_ineligible", ["Potential extraordinary circumstance keywords found in message text."], 0.7
    return "eligible", ["Cancellation may qualify under EU261 absent extraordinary circumstances."], 0.8


def _estimate_value_eur(
    *,
    eligibility_result: str,
    extracted_fields: dict[str, Any] | None,
    rules: dict[str, Any],
) -> Decimal | None:
    if eligibility_result != "eligible":
        return None
    route_distance = None
    candidate_distance = (extracted_fields or {}).get("route_distance_km")
    if isinstance(candidate_distance, (int, float)):
        route_distance = float(candidate_distance)

    tiers = (rules.get("compensation_tiers_eur") if isinstance(rules, dict) else None) or []
    if not tiers:
        return Decimal("250")
    if route_distance is None:
        first_amount = tiers[0].get("amount_eur", 250)
        return Decimal(str(first_amount))

    for tier in tiers:
        max_distance = tier.get("max_distance_km")
        amount_eur = tier.get("amount_eur", 250)
        if max_distance is None or route_distance <= float(max_distance):
            return Decimal(str(amount_eur))
    return Decimal("250")


def _draft_email(
    *,
    vendor: str | None,
    category: str | None,
    incident_date: date | None,
    flight_number: str | None,
    booking_reference: str | None,
    estimated_value: Decimal | None,
) -> tuple[str, str]:
    vendor_name = vendor or "Customer Support"
    incident_str = incident_date.isoformat() if incident_date else "[INCIDENT_DATE]"
    flight_str = flight_number or "[FLIGHT_NUMBER]"
    booking_str = booking_reference or "[BOOKING_REFERENCE]"
    amount_str = f"{estimated_value} EUR" if estimated_value is not None else "[AMOUNT]"

    subject = f"EU261 Compensation Claim - {flight_str} on {incident_str}"
    body = (
        f"Hello {vendor_name},\n\n"
        f"I am writing to request compensation under EU Regulation 261/2004 for {category or 'a disruption'}.\n\n"
        f"Details:\n"
        f"- Flight: {flight_str}\n"
        f"- Booking reference: {booking_str}\n"
        f"- Date of incident: {incident_str}\n\n"
        f"Based on the available facts, I believe compensation of approximately {amount_str} may apply.\n"
        f"Please confirm receipt of this claim and share next steps.\n\n"
        f"Kind regards,\n"
        f"[YOUR_NAME]\n"
        f"[PHONE]\n"
        f"[ADDRESS]\n"
    )
    return subject, body


def _deterministic_fallback(
    *,
    case: dict[str, Any],
    extracted_fields: dict[str, Any] | None,
    rules: dict[str, Any],
) -> dict[str, Any]:
    subject = case.get("email_subject") or ""
    body = case.get("email_body") or ""
    combined_text = f"{subject}\n{body}"

    inferred_vendor = case.get("vendor") or _infer_vendor(subject, body)
    inferred_category = _normalize_category(_clean_str(case.get("category")), subject, body)
    flight_number = _clean_str(case.get("flight_number")) or _extract_flight_number(combined_text)
    booking_reference = _clean_str(case.get("booking_reference")) or _extract_booking_reference(combined_text)
    incident_date = _extract_incident_date(combined_text, case.get("incident_date"))
    delay_minutes = _extract_delay_minutes(combined_text, extracted_fields)
    route = _extract_route(combined_text, extracted_fields)

    eligibility_result, reasons, confidence = _eu261_simplified(
        category=inferred_category,
        incident=incident_date,
        delay_minutes=delay_minutes,
        body_text=body,
        rules=rules,
    )
    estimated_value = case.get("estimated_value")
    if estimated_value is None:
        estimated_value = _estimate_value_eur(
            eligibility_result=eligibility_result,
            extracted_fields=extracted_fields,
            rules=rules,
        )

    draft_subject, draft_body = _draft_email(
        vendor=inferred_vendor,
        category=inferred_category,
        incident_date=incident_date,
        flight_number=flight_number,
        booking_reference=booking_reference,
        estimated_value=estimated_value,
    )
    preview = draft_body[:220]

    return {
        "extraction": {
            "flight_number": flight_number,
            "booking_reference": booking_reference,
            "incident_date": incident_date.isoformat() if incident_date else None,
            "delay_minutes": delay_minutes,
            "route": route,
            "vendor": inferred_vendor,
            "category": inferred_category,
        },
        "eligibility": {
            "result": eligibility_result,
            "reasons": reasons,
            "confidence": confidence,
        },
        "claim": {
            "estimated_value_eur": float(estimated_value) if isinstance(estimated_value, Decimal) else estimated_value,
            "basis": "EU261 local-rule fallback",
        },
        "draft": {
            "subject": draft_subject,
            "body": draft_body,
            "preview": preview,
        },
        "form_data": {
            "vendor": inferred_vendor,
            "category": inferred_category,
            "incident_date": incident_date.isoformat() if incident_date else None,
            "flight_number": flight_number,
            "booking_reference": booking_reference,
            "delay_minutes": delay_minutes,
            "route": route,
            "claim_basis": "EU261/2004",
            "requested_amount_eur": float(estimated_value) if isinstance(estimated_value, Decimal) else estimated_value,
        },
    }


def _merge_outputs(
    *,
    case: dict[str, Any],
    fallback: dict[str, Any],
    claude_output: dict[str, Any] | None,
    extracted_fields: dict[str, Any] | None,
    rules: dict[str, Any],
) -> dict[str, Any]:
    subject = case.get("email_subject") or ""
    body = case.get("email_body") or ""
    extraction_fallback = fallback["extraction"]
    extraction_ai = (claude_output or {}).get("extraction", {}) if isinstance(claude_output, dict) else {}

    flight_number = _clean_str(case.get("flight_number")) or _clean_str(extraction_ai.get("flight_number")) or extraction_fallback.get("flight_number")
    booking_reference = _clean_str(case.get("booking_reference")) or _clean_str(extraction_ai.get("booking_reference")) or extraction_fallback.get("booking_reference")
    incident_raw = case.get("incident_date") or extraction_ai.get("incident_date") or extraction_fallback.get("incident_date")
    incident_date = _parse_incident_date(incident_raw)
    delay_minutes = extraction_ai.get("delay_minutes")
    if not isinstance(delay_minutes, int):
        delay_minutes = extraction_fallback.get("delay_minutes")
    route = extraction_ai.get("route")
    if not isinstance(route, dict) or not route:
        route = extraction_fallback.get("route", {})
    vendor = _clean_str(case.get("vendor")) or _clean_str(extraction_ai.get("vendor")) or extraction_fallback.get("vendor")
    category = _normalize_category(
        _clean_str(case.get("category")) or _clean_str(extraction_ai.get("category")) or extraction_fallback.get("category"),
        subject,
        body,
    )

    eligibility_ai = (claude_output or {}).get("eligibility", {}) if isinstance(claude_output, dict) else {}
    result = _clean_str(eligibility_ai.get("result")) or fallback["eligibility"]["result"]
    if result not in {"eligible", "needs_info", "possibly_ineligible", "unknown"}:
        result = fallback["eligibility"]["result"]
    reasons = eligibility_ai.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        reasons = fallback["eligibility"]["reasons"]
    confidence = eligibility_ai.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = fallback["eligibility"]["confidence"]

    claim_ai = (claude_output or {}).get("claim", {}) if isinstance(claude_output, dict) else {}
    estimated_value_eur = claim_ai.get("estimated_value_eur")
    if not isinstance(estimated_value_eur, (int, float)):
        estimated_value_eur = fallback["claim"]["estimated_value_eur"]
    if isinstance(estimated_value_eur, (int, float)):
        estimated_value_eur = max(0.0, min(float(estimated_value_eur), 1000.0))
    basis = _clean_str(claim_ai.get("basis")) or fallback["claim"]["basis"]

    draft_ai = (claude_output or {}).get("draft", {}) if isinstance(claude_output, dict) else {}
    draft_subject = _clean_str(draft_ai.get("subject")) or fallback["draft"]["subject"]
    draft_body = _clean_str(draft_ai.get("body")) or fallback["draft"]["body"]
    draft_preview = _clean_str(draft_ai.get("preview")) or (draft_body[:220] if draft_body else "")

    form_data_ai = (claude_output or {}).get("form_data", {}) if isinstance(claude_output, dict) else {}
    form_data = dict(fallback["form_data"])
    if isinstance(form_data_ai, dict):
        form_data.update(form_data_ai)
    form_data.update(
        {
            "vendor": vendor,
            "category": category,
            "incident_date": incident_date.isoformat() if incident_date else None,
            "flight_number": flight_number,
            "booking_reference": booking_reference,
            "delay_minutes": delay_minutes,
            "route": route,
        }
    )

    if estimated_value_eur is None and result == "eligible":
        estimated_from_rules = _estimate_value_eur(
            eligibility_result=result,
            extracted_fields=extracted_fields,
            rules=rules,
        )
        estimated_value_eur = float(estimated_from_rules) if isinstance(estimated_from_rules, Decimal) else estimated_from_rules

    return {
        "extraction": {
            "flight_number": flight_number,
            "booking_reference": booking_reference,
            "incident_date": incident_date.isoformat() if incident_date else None,
            "delay_minutes": delay_minutes,
            "route": route,
            "vendor": vendor,
            "category": category,
        },
        "eligibility": {
            "result": result,
            "reasons": reasons,
            "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
        },
        "claim": {
            "estimated_value_eur": estimated_value_eur,
            "basis": basis,
        },
        "draft": {
            "subject": draft_subject,
            "body": draft_body,
            "preview": draft_preview,
        },
        "form_data": form_data,
    }


def process_case(case: dict[str, Any], extracted_fields: dict[str, Any] | None = None) -> Agent2Result:
    subject = case.get("email_subject") or ""
    body = case.get("email_body") or ""
    rules = _load_eu261_rules()

    fallback_output = _deterministic_fallback(case=case, extracted_fields=extracted_fields, rules=rules)
    claude_result = run_claude_agent2(
        subject=subject,
        body=body,
        extracted_fields=extracted_fields,
        eu_rules=rules,
    )
    merged_output = _merge_outputs(
        case=case,
        fallback=fallback_output,
        claude_output=claude_result.output,
        extracted_fields=extracted_fields,
        rules=rules,
    )

    extraction = merged_output["extraction"]
    eligibility = merged_output["eligibility"]
    claim = merged_output["claim"]
    draft = merged_output["draft"]
    form_data = merged_output["form_data"]

    status_value = "awaiting_approval"
    updates: dict[str, Any] = {
        "vendor": extraction.get("vendor"),
        "category": extraction.get("category"),
        "flight_number": extraction.get("flight_number"),
        "booking_reference": extraction.get("booking_reference"),
        "incident_date": extraction.get("incident_date"),
        "eligibility_result": eligibility.get("result"),
        "decision_json": {
            "version": "agent2-claude-v1",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "email_subject_hash_sha256": _hash_text(subject),
                "email_body_hash_sha256": _hash_text(body),
                "extracted_fields": extracted_fields or {},
            },
            "extraction": extraction,
            "eligibility": eligibility,
            "claim": claim,
            "draft": {
                "subject": draft.get("subject"),
                "preview": draft.get("preview"),
            },
            "agent": {
                "provider": "anthropic",
                "model": claude_result.model,
                "fallback_used": claude_result.output is None,
                "error": claude_result.error,
                "usage": claude_result.usage,
            },
        },
        "estimated_value": claim.get("estimated_value_eur"),
        "draft_email_subject": draft.get("subject"),
        "draft_email_body": draft.get("body"),
        "form_data": form_data,
        "compute_cost": 0,
        "status": status_value,
    }

    events: list[tuple[str, dict[str, Any]]] = [
        (
            "agent2_decision",
            {
                "eligibility_result": eligibility.get("result"),
                "category": extraction.get("category"),
                "estimated_value_eur": claim.get("estimated_value_eur"),
                "fallback_used": claude_result.output is None,
            },
        ),
        ("draft_generated", {"eligibility_result": eligibility.get("result")}),
        ("awaiting_approval", {"status": status_value}),
    ]

    return Agent2Result(case_updates=updates, events=events)

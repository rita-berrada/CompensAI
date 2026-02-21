from __future__ import annotations

from typing import Any, Dict

from regulatory_engine import evaluate_case


def _get(payload: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _default_channel(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _get(payload, "claim_url", "form_url", "support_url"):
        return {
            "channel_type": "form",
            "destination": _get(payload, "claim_url", "form_url", "support_url"),
        }
    if _get(payload, "claim_email", "support_email", "contact_email"):
        return {
            "channel_type": "email",
            "destination": _get(payload, "claim_email", "support_email", "contact_email"),
        }
    return {
        "channel_type": "email",
        "destination": "provider customer support channel",
    }


def _build_subject(case_type: str, payload: Dict[str, Any]) -> str:
    provider = _get(payload, "provider", "carrier", "merchant", "organiser") or "Provider"
    ref = _get(payload, "flight_number", "train_number", "service_number", "order_id", "booking_reference")
    if ref:
        return f"{case_type.replace('_', ' ').title()} refund/compensation claim - {provider} - {ref}"
    return f"{case_type.replace('_', ' ').title()} refund/compensation claim - {provider}"


def _build_body(case_type: str, payload: Dict[str, Any], evaluation: Dict[str, Any], legal_instrument: str) -> str:
    claimant = _get(payload, "passenger_name", "consumer_name", "traveller_name", "name") or "Customer"
    email = _get(payload, "passenger_email", "consumer_email", "traveller_email", "email") or "N/A"
    provider = _get(payload, "provider", "carrier", "merchant", "organiser") or "your company"

    key_pairs = []
    for k in [
        "flight_number",
        "flight_date",
        "departure_airport",
        "arrival_airport",
        "arrival_delay_hours",
        "distance_km",
        "train_number",
        "travel_date",
        "arrival_delay_minutes",
        "departure_station",
        "arrival_station",
        "service_number",
        "journey_distance_km",
        "departure_port",
        "arrival_port",
        "scheduled_journey_hours",
        "order_id",
        "purchase_date",
        "promised_delivery_date",
        "actual_delivery_date",
        "delivery_status",
        "booking_reference",
        "departure_date",
        "destination",
        "amount_paid_eur",
    ]:
        if k in payload and str(payload[k]).strip():
            key_pairs.append(f"- {k}: {payload[k]}")

    details_block = "\n".join(key_pairs) if key_pairs else "- details: provided in original communication"
    hooks = evaluation.get("legal_hooks") or []
    hooks_block = "\n".join([f"- {h}" for h in hooks]) if hooks else "- Applicable legal hooks included in evidence bundle"

    return (
        f"Dear {provider} support team,\n\n"
        f"I am submitting a {case_type.replace('_', ' ')} refund/compensation request under {legal_instrument}.\n\n"
        f"Claimant: {claimant}\n"
        f"Contact: {email}\n\n"
        f"Case details:\n{details_block}\n\n"
        f"Legal hooks considered:\n{hooks_block}\n\n"
        f"Assessment summary: {evaluation.get('rationale')}\n"
        f"Requested remedy: {evaluation.get('expected_outcome')}\n\n"
        "Please confirm receipt and provide your formal response within the applicable legal timeline.\n\n"
        "Kind regards,\n"
        f"{claimant}"
    )


def build_general_claim_plan(payload: Dict[str, Any], case_assessment: Dict[str, Any]) -> Dict[str, Any]:
    case_type = str(case_assessment.get("case_type") or "unknown")
    evaluation = evaluate_case(case_type=case_type, payload=payload)
    legal_instrument = str(evaluation.get("legal_basis") or case_assessment.get("legal_instrument") or "Relevant EU framework")

    channel = _default_channel(payload)
    eligible = bool(evaluation.get("eligible"))
    draft = (
        {
            "subject": _build_subject(case_type, payload),
            "body": _build_body(case_type, payload, evaluation, legal_instrument),
        }
        if eligible
        else None
    )

    filtered_payload = {k: v for k, v in payload.items() if v not in (None, "")}
    return {
        "case_type": case_type,
        "policy_name": case_assessment.get("policy_name"),
        "legal_instrument": legal_instrument,
        "legal_hooks": evaluation.get("legal_hooks") or [],
        "article_references": evaluation.get("article_references") or [],
        "citation_requirement_met": bool(evaluation.get("citation_requirement_met")),
        "draft_generated": eligible,
        "required_fields": case_assessment.get("required_fields") or [],
        "missing_fields": case_assessment.get("missing_fields") or [],
        "eligibility": {
            "eligible": evaluation.get("eligible"),
            "confidence": evaluation.get("confidence"),
            "rationale": evaluation.get("rationale"),
            "expected_outcome": evaluation.get("expected_outcome"),
            "legal_hooks": evaluation.get("legal_hooks") or [],
            "missing_info": evaluation.get("missing_info") or [],
            "article_references": evaluation.get("article_references") or [],
        },
        "citations": evaluation.get("citations") or [],
        "channel": channel,
        "draft": draft,
        "form_payload_preview": {"fields": filtered_payload},
    }

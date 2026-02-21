from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    patterns = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]
    for pattern in patterns:
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


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


def _rail_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    delay = _to_float(_get(payload, "arrival_delay_minutes")) or 0.0
    ticket_price = _to_float(_get(payload, "ticket_price_eur"))

    pct = 0
    if delay >= 120:
        pct = 50
    elif delay >= 60:
        pct = 25

    estimated = round((ticket_price or 0.0) * pct / 100, 2) if ticket_price is not None and pct > 0 else None
    eligible = pct > 0

    rationale = (
        f"Arrival delay reported: {delay:.0f} minutes."
        f" Rail baseline compensation bands are typically 25% (60-119 min) and 50% (120+ min)."
    )
    return {
        "eligible": eligible,
        "confidence": 0.87,
        "rationale": rationale,
        "expected_outcome": (
            f"Estimated compensation: EUR {estimated} ({pct}% of ticket price)."
            if estimated is not None
            else (f"Potential compensation: {pct}% of ticket price." if pct > 0 else "Likely no delay compensation under threshold.")
        ),
    }


def _bus_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    delay = _to_float(_get(payload, "departure_delay_minutes", "arrival_delay_minutes")) or 0.0
    distance = _to_float(_get(payload, "journey_distance_km")) or 0.0
    cancellation = str(_get(payload, "service_status", "status", "disruption_type") or "").lower()

    long_distance = distance >= 250
    major_disruption = delay >= 120 or "cancel" in cancellation
    eligible = long_distance and major_disruption

    rationale = (
        f"Journey distance: {distance:.0f} km, disruption delay: {delay:.0f} minutes."
        " For bus/coach rights, strongest refund/re-routing protection usually applies to regular services of 250+ km with cancellation or 120+ min delay."
    )
    return {
        "eligible": eligible,
        "confidence": 0.81,
        "rationale": rationale,
        "expected_outcome": (
            "Likely eligible for refund or re-routing request."
            if eligible
            else "May be outside main compensation/refund trigger thresholds; still request goodwill review."
        ),
    }


def _sea_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    delay = _to_float(_get(payload, "arrival_delay_minutes")) or 0.0
    scheduled_hours = _to_float(_get(payload, "scheduled_journey_hours"))
    ticket_price = _to_float(_get(payload, "ticket_price_eur"))

    pct = 0
    if scheduled_hours is not None:
        h = scheduled_hours
        if h <= 4 and delay >= 60:
            pct = 25 if delay < 120 else 50
        elif 4 < h <= 8 and delay >= 120:
            pct = 25 if delay < 240 else 50
        elif 8 < h <= 24 and delay >= 180:
            pct = 25 if delay < 360 else 50
        elif h > 24 and delay >= 360:
            pct = 25 if delay < 720 else 50

    estimated = round((ticket_price or 0.0) * pct / 100, 2) if ticket_price is not None and pct > 0 else None
    eligible = pct > 0
    return {
        "eligible": eligible,
        "confidence": 0.76,
        "rationale": "Sea/ferry compensation depends on scheduled journey duration and arrival delay thresholds.",
        "expected_outcome": (
            f"Potential compensation: {pct}% of ticket price"
            + (f" (~EUR {estimated})." if estimated is not None else ".")
            if pct > 0
            else "Delay may be below compensation threshold for this route duration."
        ),
    }


def _parcel_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    promised = _to_date(_get(payload, "promised_delivery_date"))
    actual = _to_date(_get(payload, "actual_delivery_date"))
    status = str(_get(payload, "delivery_status", "status") or "").lower()

    today = date.today()
    overdue = promised is not None and ((actual is None and today > promised) or (actual is not None and actual > promised))
    not_delivered = "not_delivered" in status or "missing" in status or (actual is None and promised is not None and today > promised)
    eligible = overdue or not_delivered

    return {
        "eligible": eligible,
        "confidence": 0.84,
        "rationale": "Consumer delivery rights usually allow escalation when goods are not delivered in agreed time (or default timeline).",
        "expected_outcome": (
            "Request delivery within additional reasonable time, then seek cancellation and refund if still undelivered."
            if eligible
            else "Delivery delay/refund right may not yet be triggered from provided dates/status."
        ),
    }


def _package_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    status = str(_get(payload, "trip_status", "status", "disruption_type") or "").lower()
    cancelled = "cancel" in status or _get(payload, "cancellation_date") not in (None, "")
    amount_paid = _to_float(_get(payload, "amount_paid_eur"))

    return {
        "eligible": cancelled,
        "confidence": 0.83,
        "rationale": "Package travel cancellations and significant changes can trigger refund rights under package travel rules.",
        "expected_outcome": (
            f"Request refund of EUR {amount_paid} within statutory timeline (commonly 14 days)."
            if cancelled and amount_paid is not None
            else ("Request full refund within statutory timeline (commonly 14 days)." if cancelled else "Need cancellation/significant-change evidence to confirm refund entitlement.")
        ),
    }


def _unknown_assessment(_: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "eligible": False,
        "confidence": 0.45,
        "rationale": "Could not map this claim to a supported policy bucket.",
        "expected_outcome": "Manual legal/policy triage required.",
    }


def _build_subject(case_type: str, payload: Dict[str, Any]) -> str:
    provider = _get(payload, "provider", "carrier", "merchant", "organiser") or "Provider"
    ref = _get(payload, "flight_number", "train_number", "service_number", "order_id", "booking_reference")
    if ref:
        return f"{case_type.replace('_', ' ').title()} refund/compensation claim - {provider} - {ref}"
    return f"{case_type.replace('_', ' ').title()} refund/compensation claim - {provider}"


def _build_body(case_type: str, payload: Dict[str, Any], assessment: Dict[str, Any], legal_instrument: str) -> str:
    claimant = _get(payload, "passenger_name", "consumer_name", "traveller_name", "name") or "Customer"
    email = _get(payload, "passenger_email", "consumer_email", "traveller_email", "email") or "N/A"
    provider = _get(payload, "provider", "carrier", "merchant", "organiser") or "your company"

    key_pairs = []
    for k in [
        "flight_number",
        "flight_date",
        "departure_airport",
        "arrival_airport",
        "train_number",
        "travel_date",
        "departure_station",
        "arrival_station",
        "service_number",
        "journey_distance_km",
        "departure_port",
        "arrival_port",
        "order_id",
        "purchase_date",
        "promised_delivery_date",
        "delivery_status",
        "booking_reference",
        "departure_date",
        "destination",
        "amount_paid_eur",
    ]:
        if k in payload and str(payload[k]).strip():
            key_pairs.append(f"- {k}: {payload[k]}")

    details_block = "\n".join(key_pairs) if key_pairs else "- details: provided in original communication"

    return (
        f"Dear {provider} support team,\n\n"
        f"I am submitting a {case_type.replace('_', ' ')} refund/compensation request under {legal_instrument}.\n\n"
        f"Claimant: {claimant}\n"
        f"Contact: {email}\n\n"
        f"Case details:\n{details_block}\n\n"
        f"Assessment summary: {assessment.get('rationale')}\n"
        f"Requested remedy: {assessment.get('expected_outcome')}\n\n"
        "Please confirm receipt and provide your formal response within the applicable legal timeline.\n\n"
        "Kind regards,\n"
        f"{claimant}"
    )


def build_general_claim_plan(payload: Dict[str, Any], case_assessment: Dict[str, Any]) -> Dict[str, Any]:
    case_type = str(case_assessment.get("case_type") or "unknown")
    legal_instrument = str(case_assessment.get("legal_instrument") or "applicable EU framework")
    required_fields = case_assessment.get("required_fields") or []

    if case_type == "rail":
        eligibility = _rail_assessment(payload)
    elif case_type == "bus_coach":
        eligibility = _bus_assessment(payload)
    elif case_type == "sea":
        eligibility = _sea_assessment(payload)
    elif case_type == "parcel_delivery":
        eligibility = _parcel_assessment(payload)
    elif case_type == "package_travel":
        eligibility = _package_assessment(payload)
    else:
        eligibility = _unknown_assessment(payload)

    channel = _default_channel(payload)
    draft = {
        "subject": _build_subject(case_type, payload),
        "body": _build_body(case_type, payload, eligibility, legal_instrument),
    }

    filtered_payload = {k: v for k, v in payload.items() if v not in (None, "")}
    return {
        "case_type": case_type,
        "policy_name": case_assessment.get("policy_name"),
        "legal_instrument": legal_instrument,
        "required_fields": required_fields,
        "missing_fields": case_assessment.get("missing_fields") or [],
        "eligibility": eligibility,
        "channel": channel,
        "draft": draft,
        "form_payload_preview": {"fields": filtered_payload},
    }

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Dict, List, Literal, Optional

CaseType = Literal["flight", "rail", "bus_coach", "sea", "parcel_delivery", "package_travel", "unknown"]


@dataclass(frozen=True)
class PolicySpec:
    case_type: CaseType
    policy_name: str
    legal_instrument: str
    required_fields: List[str]
    notes: str


POLICIES: Dict[CaseType, PolicySpec] = {
    "flight": PolicySpec(
        case_type="flight",
        policy_name="Air passenger rights",
        legal_instrument="Regulation (EC) No 261/2004 (EU261)",
        required_fields=[
            "provider",
            "flight_number",
            "flight_date",
            "departure_airport",
            "arrival_airport",
            "arrival_delay_hours",
            "passenger_name",
            "passenger_email",
        ],
        notes="Compensation brackets are typically EUR 250/400/600 based on distance and disruption conditions.",
    ),
    "rail": PolicySpec(
        case_type="rail",
        policy_name="Rail passenger rights",
        legal_instrument="Regulation (EU) 2021/782",
        required_fields=[
            "carrier",
            "train_number",
            "travel_date",
            "departure_station",
            "arrival_station",
            "arrival_delay_minutes",
            "passenger_name",
            "passenger_email",
        ],
        notes="Delay compensation baseline is 25% (60-119 min) and 50% (120+ min) of ticket price.",
    ),
    "bus_coach": PolicySpec(
        case_type="bus_coach",
        policy_name="Bus and coach passenger rights",
        legal_instrument="Regulation (EU) No 181/2011",
        required_fields=[
            "carrier",
            "service_number",
            "travel_date",
            "departure_station",
            "arrival_station",
            "departure_delay_minutes",
            "journey_distance_km",
            "passenger_name",
            "passenger_email",
        ],
        notes="For long-distance regular services (250+ km), cancellation or 120+ min delay triggers re-routing/refund rights.",
    ),
    "sea": PolicySpec(
        case_type="sea",
        policy_name="Ship and ferry passenger rights",
        legal_instrument="Regulation (EU) No 1177/2010",
        required_fields=[
            "carrier",
            "service_number",
            "travel_date",
            "departure_port",
            "arrival_port",
            "scheduled_journey_hours",
            "arrival_delay_minutes",
            "passenger_name",
            "passenger_email",
        ],
        notes="Arrival-delay compensation is typically 25%-50% of ticket price depending on route duration and delay length.",
    ),
    "parcel_delivery": PolicySpec(
        case_type="parcel_delivery",
        policy_name="Consumer delivery rights for goods",
        legal_instrument="Directive 2011/83/EU (Articles 18 and 20)",
        required_fields=[
            "merchant",
            "order_id",
            "purchase_date",
            "promised_delivery_date",
            "delivery_status",
            "item_value_eur",
            "consumer_name",
            "consumer_email",
        ],
        notes="If goods are not delivered within agreed time (or within 30 days if not agreed), consumer can seek termination/refund after giving additional time.",
    ),
    "package_travel": PolicySpec(
        case_type="package_travel",
        policy_name="Package travel rights",
        legal_instrument="Directive (EU) 2015/2302",
        required_fields=[
            "organiser",
            "booking_reference",
            "departure_date",
            "destination",
            "cancellation_date",
            "traveller_name",
            "traveller_email",
            "amount_paid_eur",
        ],
        notes="Travellers can receive refunds under package-travel rules; typical refund deadline is 14 days after contract termination.",
    ),
    "unknown": PolicySpec(
        case_type="unknown",
        policy_name="Unknown case type",
        legal_instrument="Manual triage required",
        required_fields=[],
        notes="Could not map this JSON to a known EU transport/consumer framework.",
    ),
}

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover
    Anthropic = None


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _contains_any(text: str, words: List[str]) -> bool:
    text_l = _normalize(text)
    if not text_l:
        return False
    # Use word boundaries to avoid false positives like "support" matching "port".
    return any(re.search(rf"\b{re.escape(w)}\b", text_l) is not None for w in words)


def infer_case_type(payload: Dict[str, Any]) -> CaseType:
    explicit = _normalize(str(payload.get("case_type") or payload.get("transport_mode") or payload.get("service_type") or ""))
    if explicit:
        if explicit in {"flight", "air", "airline", "aviation"}:
            return "flight"
        if explicit in {"rail", "train"}:
            return "rail"
        if explicit in {"bus", "coach", "bus_coach", "road"}:
            return "bus_coach"
        if explicit in {"sea", "ferry", "ship", "maritime", "inland_waterway"}:
            return "sea"
        if explicit in {"parcel", "package_delivery", "delivery", "courier", "postal"}:
            return "parcel_delivery"
        if explicit in {"package_travel", "holiday_package", "tour_package"}:
            return "package_travel"

    text = " ".join(
        [
            str(payload.get("email_text") or ""),
            str(payload.get("notes") or ""),
            str(payload.get("description") or ""),
            str(payload.get("subject") or ""),
        ]
    ).lower()

    if payload.get("flight_number") or _contains_any(text, ["flight", "boarding", "airport", "eu261"]):
        return "flight"
    if payload.get("train_number") or _contains_any(text, ["train", "rail", "station", "missed connection"]):
        return "rail"
    if payload.get("service_number") or _contains_any(text, ["bus", "coach", "terminal", "road service"]):
        return "bus_coach"
    if payload.get("departure_port") or _contains_any(text, ["ferry", "ship", "port", "voyage", "maritime"]):
        return "sea"
    if payload.get("order_id") or _contains_any(text, ["parcel", "delivery", "courier", "not delivered", "tracking"]):
        return "parcel_delivery"
    if payload.get("booking_reference") or _contains_any(text, ["package travel", "tour operator", "holiday package"]):
        return "package_travel"

    return "unknown"


def _extract_text_from_anthropic_response(response: Any) -> str:
    parts: List[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join([p for p in parts if p]).strip()


def classify_case_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    heuristic = infer_case_type(payload)
    if not os.getenv("ANTHROPIC_API_KEY") or Anthropic is None:
        return {
            "case_type": heuristic,
            "confidence": 0.65,
            "reasoning": "Heuristic classifier used (LLM unavailable).",
            "mode": "heuristic",
        }

    try:
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        email_text = str(payload.get("email_text") or payload.get("body") or payload.get("message") or "")
        compact_payload = {k: v for k, v in payload.items() if k not in {"email_text", "body", "message"}}
        prompt = (
            "Classify this complaint into exactly one case type: "
            "flight, rail, bus_coach, sea, parcel_delivery, package_travel, unknown.\n"
            "Return strict JSON only with keys: case_type, confidence, reasoning.\n"
            f"Email text:\n{email_text}\n\n"
            f"Other payload fields:\n{json.dumps(compact_payload, ensure_ascii=True)}"
        )
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=220,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text_from_anthropic_response(response)
        start = text.find("{")
        end = text.rfind("}")
        parsed = json.loads(text[start : end + 1]) if start >= 0 and end > start else {}
        case_type = str(parsed.get("case_type", "")).strip().lower()
        if case_type not in POLICIES:
            case_type = heuristic
        confidence = float(parsed.get("confidence", 0.7))
        reasoning = str(parsed.get("reasoning", "")).strip() or "LLM classifier result."
        return {
            "case_type": case_type,
            "confidence": max(0.0, min(1.0, confidence)),
            "reasoning": reasoning,
            "mode": "llm",
        }
    except Exception:
        return {
            "case_type": heuristic,
            "confidence": 0.6,
            "reasoning": "Heuristic fallback used (LLM classification failed).",
            "mode": "heuristic_fallback",
        }


def assess_case_payload(payload: Dict[str, Any], case_type_override: Optional[str] = None) -> Dict[str, Any]:
    case_type = str(case_type_override).strip().lower() if case_type_override else infer_case_type(payload)
    if case_type not in POLICIES:
        case_type = "unknown"
    spec = POLICIES[case_type]

    present_fields: List[str] = []
    missing_fields: List[str] = []
    for field in spec.required_fields:
        value = payload.get(field)
        if value is None or str(value).strip() == "":
            missing_fields.append(field)
        else:
            present_fields.append(field)

    return {
        "case_type": case_type,
        "policy_name": spec.policy_name,
        "legal_instrument": spec.legal_instrument,
        "required_fields": spec.required_fields,
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "notes": spec.notes,
    }

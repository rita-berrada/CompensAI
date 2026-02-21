from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from regulatory_lexical import RegulatoryLexicalRetriever, infer_article_reference
from schemas import RagCitation

RULES_PATH = Path("data/regulatory_rules.json")
KB_PATH = Path("data/regulatory_kb.jsonl")


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
    for pattern in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def load_regulatory_rules() -> Dict[str, Any]:
    if not RULES_PATH.exists():
        return {}
    with RULES_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_regulatory_kb() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not KB_PATH.exists():
        return rows
    with KB_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", (text or "").lower()) if len(t) >= 2]


def retrieve_regulatory_citations(case_type: str, query: str, k: int = 4) -> List[RagCitation]:
    rows = [
        r for r in load_regulatory_kb() if str(r.get("case_type", "")).strip().lower() in {"common", case_type.lower()}
    ]
    if not rows:
        return []

    tokens = set(_tokenize(query))
    scored: List[tuple[float, Dict[str, Any]]] = []
    for row in rows:
        hay = f"{row.get('title', '')} {row.get('text', '')}".lower()
        if not tokens:
            overlap = 0
        else:
            overlap = sum(1 for t in tokens if t in hay)
        score = overlap / max(1, len(tokens))
        if str(row.get("case_type", "")).lower() == case_type.lower():
            score += 0.1
        scored.append((score, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: max(1, int(k))]
    out: List[RagCitation] = []
    for score, row in selected:
        out.append(
            RagCitation(
                chunk_id=str(row.get("id", "unknown")),
                title=str(row.get("title", "Regulatory source")),
                text=str(row.get("text", "")),
                score=max(0.05, min(1.0, score)),
            )
        )
    return out


@lru_cache(maxsize=1)
def _get_lexical_retriever() -> RegulatoryLexicalRetriever:
    return RegulatoryLexicalRetriever()


def _flight_eval(payload: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    delay_h = _to_float(payload.get("arrival_delay_hours"))
    distance_km = _to_float(payload.get("distance_km"))
    threshold = float(rules.get("delay_compensation_threshold_hours", 3))
    missing_info = []
    if delay_h is None:
        missing_info.append("arrival_delay_hours")
    if payload.get("flight_date") in (None, ""):
        missing_info.append("flight_date")
    if payload.get("flight_number") in (None, ""):
        missing_info.append("flight_number")

    eligible = delay_h is not None and delay_h >= threshold
    compensation = None
    if eligible and distance_km is not None:
        for bracket in rules.get("compensation_brackets", []):
            max_distance = bracket.get("max_distance_km")
            if max_distance is None or distance_km <= float(max_distance):
                compensation = int(bracket.get("amount_eur", 0))
                break

    rationale = (
        f"Arrival delay reported: {delay_h:.1f}h; policy trigger from documentation: {threshold:.1f}h."
        if delay_h is not None
        else f"Missing arrival delay; compensation trigger in policy docs is {threshold:.1f}h."
    )
    expected = (
        f"Compensation may apply under EU261. Estimated fixed amount: EUR {compensation}."
        if eligible and compensation is not None
        else (
            "Compensation may apply under EU261, but distance is needed to determine amount."
            if eligible
            else "Reported delay is below documented compensation trigger; compensation likely not due."
        )
    )

    return {
        "eligible": eligible,
        "confidence": 0.9 if not missing_info else 0.78,
        "rationale": rationale,
        "expected_outcome": expected,
        "compensation_eur": compensation,
        "missing_info": missing_info,
    }


def _rail_eval(payload: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    delay_min = _to_float(payload.get("arrival_delay_minutes"))
    if delay_min is None and _to_float(payload.get("arrival_delay_hours")) is not None:
        delay_min = float(_to_float(payload.get("arrival_delay_hours")) or 0) * 60

    ticket_price = _to_float(payload.get("ticket_price_eur"))
    bands = sorted(rules.get("delay_compensation_bands_minutes", []), key=lambda b: float(b.get("min_delay_minutes", 0)))

    pct = 0
    for b in bands:
        if delay_min is not None and delay_min >= float(b.get("min_delay_minutes", 0)):
            pct = int(b.get("percent_ticket_price", pct))

    estimated = round((ticket_price or 0) * pct / 100, 2) if ticket_price is not None and pct > 0 else None
    missing_info = [f for f in ["arrival_delay_minutes", "travel_date", "train_number"] if payload.get(f) in (None, "")]

    rationale = (
        f"Arrival delay reported: {delay_min:.0f} minutes; applicable documented compensation band: {pct}% of ticket price."
        if delay_min is not None
        else "Arrival delay is missing; cannot map to documented rail compensation bands."
    )
    expected = (
        f"Rail delay compensation may apply at {pct}% of ticket price"
        + (f" (~EUR {estimated})." if estimated is not None else ".")
        if pct > 0
        else "Reported delay appears below documented compensation bands."
    )
    return {
        "eligible": pct > 0,
        "confidence": 0.87 if delay_min is not None else 0.65,
        "rationale": rationale,
        "expected_outcome": expected,
        "missing_info": missing_info,
    }


def _bus_eval(payload: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    delay_min = _to_float(payload.get("departure_delay_minutes"))
    if delay_min is None:
        delay_min = _to_float(payload.get("arrival_delay_minutes"))
    distance_km = _to_float(payload.get("journey_distance_km"))
    status = str(payload.get("service_status") or payload.get("status") or payload.get("disruption_type") or "").lower()

    min_distance = float(rules.get("minimum_distance_km", 250))
    major_delay = float(rules.get("major_delay_minutes", 120))

    long_distance = distance_km is not None and distance_km >= min_distance
    major_disruption = (delay_min is not None and delay_min >= major_delay) or "cancel" in status
    eligible = long_distance and major_disruption

    missing_info = [f for f in ["journey_distance_km", "travel_date"] if payload.get(f) in (None, "")]
    rationale = (
        f"Documented triggers checked: journey >= {min_distance:.0f}km and cancellation/>= {major_delay:.0f} min delay."
    )
    expected = (
        "Refund or rerouting request is likely supportable under bus/coach rights."
        if eligible
        else "Provided facts do not clearly meet the documented long-distance major disruption trigger."
    )
    return {
        "eligible": eligible,
        "confidence": 0.82 if distance_km is not None else 0.68,
        "rationale": rationale,
        "expected_outcome": expected,
        "missing_info": missing_info,
    }


def _sea_eval(payload: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    delay_min = _to_float(payload.get("arrival_delay_minutes"))
    journey_h = _to_float(payload.get("scheduled_journey_hours"))
    ticket_price = _to_float(payload.get("ticket_price_eur"))

    pct = 0
    thresholds = rules.get("arrival_delay_thresholds", [])
    for t in thresholds:
        max_h = t.get("max_journey_hours")
        min_delay = float(t.get("min_delay_minutes", 0))
        if delay_min is None or journey_h is None:
            continue
        duration_match = max_h is None or journey_h <= float(max_h)
        if duration_match and delay_min >= min_delay:
            pct = max(pct, int(t.get("percent_ticket_price", 0)))

    estimated = round((ticket_price or 0) * pct / 100, 2) if ticket_price is not None and pct > 0 else None
    missing_info = [f for f in ["scheduled_journey_hours", "arrival_delay_minutes", "travel_date"] if payload.get(f) in (None, "")]

    rationale = "Sea rights assessment uses documented delay bands by journey duration."
    expected = (
        f"Potential compensation: {pct}% of ticket price"
        + (f" (~EUR {estimated})." if estimated is not None else ".")
        if pct > 0
        else "Reported facts do not clearly match documented delay bands for compensation."
    )

    return {
        "eligible": pct > 0,
        "confidence": 0.79 if not missing_info else 0.62,
        "rationale": rationale,
        "expected_outcome": expected,
        "missing_info": missing_info,
    }


def _parcel_eval(payload: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    purchase_d = _to_date(payload.get("purchase_date"))
    promised_d = _to_date(payload.get("promised_delivery_date"))
    actual_d = _to_date(payload.get("actual_delivery_date"))
    status = str(payload.get("delivery_status") or payload.get("status") or "").lower()

    default_days = int(rules.get("default_delivery_days_if_unspecified", 30))
    due_date = promised_d or (purchase_d + timedelta(days=default_days) if purchase_d else None)
    today = date.today()

    late_delivery = due_date is not None and actual_d is not None and actual_d > due_date
    undelivered_overdue = due_date is not None and actual_d is None and today > due_date
    explicit_not_delivered = any(x in status for x in ["not_delivered", "missing", "lost"])
    eligible = late_delivery or undelivered_overdue or explicit_not_delivered

    refund_days = int(rules.get("refund_after_termination_days", 14))
    missing_info = [f for f in ["purchase_date", "order_id"] if payload.get(f) in (None, "")]

    rationale = (
        f"Delivery deadline derived from documentation (agreed date or default {default_days} days where unspecified)."
    )
    expected = (
        f"Consumer can escalate non-delivery/late delivery, then seek termination and refund (typically within {refund_days} days after termination)."
        if eligible
        else "Timeline evidence does not yet clearly show overdue delivery under documented rule framework."
    )
    return {
        "eligible": eligible,
        "confidence": 0.84 if due_date is not None else 0.66,
        "rationale": rationale,
        "expected_outcome": expected,
        "missing_info": missing_info,
    }


def _package_eval(payload: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    status = str(payload.get("trip_status") or payload.get("status") or payload.get("disruption_type") or "").lower()
    cancelled = "cancel" in status or payload.get("cancellation_date") not in (None, "")
    significant_change = any(x in status for x in ["significant change", "major change"])
    refund_days = int(rules.get("refund_after_termination_days", 14))
    amount_paid = _to_float(payload.get("amount_paid_eur"))

    eligible = cancelled or significant_change
    missing_info = [f for f in ["booking_reference", "departure_date"] if payload.get(f) in (None, "")]

    expected = (
        f"Package-travel refund request is likely supportable. Expected refund timeline: about {refund_days} days after termination."
        if eligible
        else "Need cancellation/significant-change evidence to ground package-travel refund entitlement."
    )
    if eligible and amount_paid is not None:
        expected += f" Claimed amount: EUR {amount_paid}."

    return {
        "eligible": eligible,
        "confidence": 0.83 if eligible else 0.7,
        "rationale": "Package travel assessment checks documented cancellation/significant-change refund hooks.",
        "expected_outcome": expected,
        "missing_info": missing_info,
    }


def evaluate_case(case_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    case_key = str(case_type or "unknown").strip().lower()
    rules_all = load_regulatory_rules()
    rules = rules_all.get(case_key, {}) if isinstance(rules_all, dict) else {}

    if case_key == "flight":
        core = _flight_eval(payload, rules)
    elif case_key == "rail":
        core = _rail_eval(payload, rules)
    elif case_key == "bus_coach":
        core = _bus_eval(payload, rules)
    elif case_key == "sea":
        core = _sea_eval(payload, rules)
    elif case_key == "parcel_delivery":
        core = _parcel_eval(payload, rules)
    elif case_key == "package_travel":
        core = _package_eval(payload, rules)
    else:
        core = {
            "eligible": False,
            "confidence": 0.45,
            "rationale": "Unsupported case type for regulatory evaluation.",
            "expected_outcome": "Manual triage required.",
            "missing_info": [],
        }

    legal_instrument = str(rules.get("legal_instrument") or "Relevant EU framework")
    legal_hooks = [str(h) for h in rules.get("hooks", [])] if isinstance(rules.get("hooks", []), list) else []
    query = " ".join(
        [
            case_key,
            str(payload.get("subject") or ""),
            str(payload.get("email_text") or ""),
            str(payload.get("notes") or ""),
            str(payload.get("description") or ""),
        ]
    )
    citations: List[RagCitation] = []
    try:
        citations = _get_lexical_retriever().retrieve(case_key, query, k=4)
    except Exception:
        citations = []
    if not citations:
        citations = retrieve_regulatory_citations(case_key, query, k=4)

    article_refs: List[str] = []
    for c in citations:
        ref = infer_article_reference(c)
        if ref and ref not in article_refs:
            article_refs.append(ref)

    if not citations:
        core["confidence"] = min(float(core.get("confidence", 0.6)), 0.45)
        core["rationale"] = str(core.get("rationale", "")) + " No relevant legal sections were retrieved from loaded regulation documents."
        core["expected_outcome"] = (
            "Insufficient legal citation coverage from local regulation documents. Load full regulation text and retry."
        )

    result = {
        **core,
        "case_type": case_key,
        "legal_basis": legal_instrument,
        "legal_hooks": legal_hooks,
        "article_references": article_refs,
        "citation_requirement_met": bool(citations),
        "citations": [c.model_dump() for c in citations],
    }
    return result

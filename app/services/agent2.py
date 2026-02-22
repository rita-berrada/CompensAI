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
from app.services.company_web import extract_contact_email, extract_form_schema, fetch_html
from app.services.site_registry import DEMO_RETAIL_VENDOR, detect_site_family, registry_urls


@dataclass(frozen=True)
class Agent2Result:
    case_updates: dict[str, Any]
    events: list[tuple[str, dict[str, Any]]]

SUPPORTED_CATEGORIES: set[str] = {
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

URL_RE = re.compile(r"https?://[^\s)>\"]+", flags=re.IGNORECASE)


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


FALLBACK_TRAIN_RULES: dict[str, Any] = {
    "eligibility_rules": {
        "delay_minutes_threshold": 60,
        "possible_exclusions_keywords": ["strike", "extreme weather", "security incident"],
    },
    "notes": "Demo rules only (not legal advice).",
}


@lru_cache(maxsize=1)
def _load_train_rules() -> dict[str, Any]:
    kb_path = Path(__file__).resolve().parent.parent / "kb" / "train_rules.json"
    try:
        with kb_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:  # noqa: BLE001
        return FALLBACK_TRAIN_RULES


MARKETPLACE_BASELINE_KB: dict[str, Any] = {
    "domain": "marketplace",
    "required_info_checklist": [
        "order_number",
        "tracking_number (if available)",
        "promised_delivery_date or purchase date",
        "delivery status (late/missing/damaged)",
        "photos for damage (if applicable)",
    ],
    "notes": "Use company policy text from company_site.policy_text when provided.",
}


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _infer_vendor(subject: str, body: str) -> str | None:
    text = f"{subject}\n{body}".lower()
    if "demoretail" in text or "retail-policy" in text or "retail-contact" in text:
        return DEMO_RETAIL_VENDOR
    for vendor in ["ryanair", "easyjet", "lufthansa", "klm", "air france", "british airways", "iberia", "wizz air"]:
        if vendor in text:
            return vendor.title()
    return None


def _infer_category(subject: str, body: str) -> str | None:
    text = f"{subject}\n{body}".lower()
    if any(k in text for k in ["denied boarding", "deny boarding", "bumped", "overbooked", "overbooking", "not allowed to board"]):
        return "flight_denied_boarding"
    if any(k in text for k in ["lost baggage", "lost luggage", "delayed baggage", "damaged baggage", "damaged luggage", "baggage", "luggage"]):
        if any(k in text for k in ["train", "rail"]):
            return "train_baggage"
        return "flight_baggage"
    if any(k in text for k in ["cancelled", "canceled", "cancellation"]):
        if any(k in text for k in ["train", "rail"]):
            return "train_cancellation"
        return "flight_cancellation"
    if any(k in text for k in ["delay", "delayed", "late arrival", "arrived late"]):
        if any(k in text for k in ["train", "rail"]):
            return "train_delay"
        return "flight_delay"
    if any(k in text for k in ["delivery", "delivered", "parcel", "tracking", "order #", "order number"]):
        if any(k in text for k in ["missing", "never arrived", "not received", "lost package"]):
            return "delivery_missing"
        if any(k in text for k in ["damaged", "broken", "cracked", "defective"]):
            return "delivery_damaged"
        return "delivery_late"
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
    if value in SUPPORTED_CATEGORIES:
        return value
    inferred = _infer_category(subject, body)
    if inferred in SUPPORTED_CATEGORIES:
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

    # Handle "X hours Y minutes" or "X hours, Y minutes" format
    hours_minutes_match = re.search(
        r"(\d+)\s*(?:h|hr|hrs|hour|hours)[,\s]+(\d+)\s*(?:m|min|mins|minute|minutes)",
        text,
        flags=re.IGNORECASE,
    )
    if hours_minutes_match:
        hours = int(hours_minutes_match.group(1))
        minutes = int(hours_minutes_match.group(2))
        return (hours * 60) + minutes

    # Handle "X hours" format
    delay_match = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)", text, flags=re.IGNORECASE)
    if delay_match:
        return int(delay_match.group(1)) * 60

    # Handle "X minutes" or "X mins" format
    minute_match = re.search(r"(\d+)\s*(?:m|min|mins|minute|minutes)", text, flags=re.IGNORECASE)
    if minute_match:
        return int(minute_match.group(1))

    # Handle "X hours Y minutes (Z minutes)" format - extract the Z value in parentheses
    parentheses_match = re.search(r"\((\d+)\s*(?:m|min|mins|minute|minutes)\)", text, flags=re.IGNORECASE)
    if parentheses_match:
        return int(parentheses_match.group(1))

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
    # Try labeled format first: "Booking Reference: ABC123XYZ" or "Ref: ABC123"
    labeled_match = re.search(
        r"(?:booking(?:\s+reference)?|ref(?:erence)?|booking\s+ref)[:\s\-]+([A-Z0-9]{4,12})",
        text,
        flags=re.IGNORECASE,
    )
    if labeled_match:
        return labeled_match.group(1).upper()

    # Try bullet point or list format: "- Booking Reference: ABC123" or "* Ref: ABC123"
    bullet_match = re.search(
        r"[-\*]\s*(?:booking(?:\s+reference)?|ref(?:erence)?)[:\s\-]+([A-Z0-9]{4,12})",
        text,
        flags=re.IGNORECASE,
    )
    if bullet_match:
        return bullet_match.group(1).upper()

    # Try standalone format: "ABC123XYZ" after "Booking" keyword (more flexible)
    standalone_match = re.search(
        r"(?:booking|ref)[:\s\-]+([A-Z0-9]{4,12})",
        text,
        flags=re.IGNORECASE,
    )
    if standalone_match:
        return standalone_match.group(1).upper()

    return None


def _extract_order_number(text: str) -> str | None:
    match = re.search(
        r"(?:order\s*(?:number|no\.?|#)\s*[:\-]?\s*)([A-Z0-9\-]{4,})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


def _extract_tracking_number(text: str) -> str | None:
    match = re.search(
        r"(?:tracking\s*(?:number|no\.?|#)\s*[:\-]?\s*)([A-Z0-9\-]{6,})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    urls = URL_RE.findall(text)
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        url_clean = url.strip().rstrip(").,]>\"'")
        if url_clean in seen:
            continue
        seen.add(url_clean)
        unique.append(url_clean)
    return unique


def _infer_domain(*, category: str, subject: str, body: str, urls: list[str]) -> str:
    if category.startswith("flight_"):
        return "flights"
    if category.startswith("delivery_"):
        return "marketplace"
    if category.startswith("train_"):
        return "trains"

    family = detect_site_family(urls=urls, text=f"{subject}\n{body}")
    if family == "retail":
        return "marketplace"
    if family == "airline":
        return "flights"

    lowered = f"{subject}\n{body}".lower()
    if any(k in lowered for k in ["train", "rail", "platform", "carriage"]):
        return "trains"
    if any(k in lowered for k in ["order", "delivery", "tracking", "parcel"]):
        return "marketplace"
    return "flights"


def _build_company_site_context(*, subject: str, body: str, force_family: str | None = None) -> dict[str, Any] | None:
    urls_in_email = _extract_urls(body)
    family = detect_site_family(urls=urls_in_email, text=f"{subject}\n{body}")
    if not family and force_family in {"airline", "retail"}:
        family = force_family
    if not family:
        return None

    reg = registry_urls(family)
    urls: dict[str, str] = {"family": family, **reg}
    fetches: dict[str, Any] = {}
    policy_text = ""
    contact_email: str | None = None
    form_schema: dict[str, Any] | None = None

    policy_url = reg.get("policy_url")
    if policy_url:
        policy_fetch = fetch_html(policy_url)
        fetches["policy_url"] = {
            "url": policy_fetch.url,
            "ok": policy_fetch.ok,
            "status": policy_fetch.status,
            "error": policy_fetch.error,
        }
        policy_text = (policy_fetch.text or "")[:6000]

    if family == "airline":
        claim_form_url = reg.get("claim_form_url")
        if claim_form_url:
            form_fetch = fetch_html(claim_form_url)
            fetches["claim_form_url"] = {
                "url": form_fetch.url,
                "ok": form_fetch.ok,
                "status": form_fetch.status,
                "error": form_fetch.error,
            }
            form_schema = extract_form_schema(form_fetch.html)
    else:
        contact_url = reg.get("contact_url")
        if contact_url:
            contact_fetch = fetch_html(contact_url)
            fetches["contact_url"] = {
                "url": contact_fetch.url,
                "ok": contact_fetch.ok,
                "status": contact_fetch.status,
                "error": contact_fetch.error,
            }
            contact_email = extract_contact_email(contact_fetch.text or "") or extract_contact_email(policy_text or "")

    return {
        "urls_in_email": urls_in_email,
        "urls": urls,
        "fetches": fetches,
        "policy_text": policy_text,
        "contact_email": contact_email,
        "form_schema": form_schema,
    }


def _extract_incident_date(text: str, existing_value: Any) -> date | None:
    parsed = _parse_incident_date(existing_value)
    if parsed:
        return parsed

    # Try various date formats
    patterns = [
        # ISO format: 2026-02-15
        (r"\b(20\d{2}-\d{2}-\d{2})\b", lambda m: _parse_incident_date(m.group(1))),
        # US format: 02/15/2026
        (r"\b(\d{2}/\d{2}/20\d{2})\b", lambda m: _parse_date_slash(m.group(1))),
        # European format: 15/02/2026
        (r"\b(\d{2}/\d{2}/20\d{2})\b", lambda m: _parse_date_slash_eu(m.group(1))),
        # Written format: February 15, 2026 or 15 February 2026
        (r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b", lambda m: _parse_date_written(m.group(0))),
        # Date with context: "on 2026-02-15" or "scheduled for February 15, 2026"
        (r"(?:on|for|date|scheduled|departure|arrival)[:\s]+(20\d{2}-\d{2}-\d{2})", lambda m: _parse_incident_date(m.group(1))),
        # Date in parentheses: (2026-02-15)
        (r"\((\d{4}-\d{2}-\d{2})\)", lambda m: _parse_incident_date(m.group(1))),
    ]

    for pattern, parser in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                result = parser(match)
                if result:
                    return result
            except (ValueError, AttributeError):
                continue

    return None


def _parse_date_slash(value: str) -> date | None:
    """Parse MM/DD/YYYY format"""
    try:
        parts = value.split("/")
        if len(parts) == 3:
            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
            return date(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def _parse_date_slash_eu(value: str) -> date | None:
    """Parse DD/MM/YYYY format (European)"""
    try:
        parts = value.split("/")
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            return date(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def _parse_date_written(value: str) -> date | None:
    """Parse written date format like 'February 15, 2026'"""
    try:
        from datetime import datetime
        # Try common formats
        for fmt in ["%B %d, %Y", "%d %B %Y", "%B %d %Y"]:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.date()
            except ValueError:
                continue
    except Exception:
        pass
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
    if category not in {"flight_delay", "flight_cancellation", "flight_denied_boarding", "flight_baggage"}:
        return "unknown", ["Category is outside current flight scope for Agent2."], 0.3

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

    if category == "flight_denied_boarding":
        lowered = body_text.lower()
        if any(k in lowered for k in ["voluntary", "accepted voucher", "accepted compensation"]):
            return "needs_info", ["Message suggests a voluntary arrangement; need details to assess EU261 denied boarding rights."], 0.6
        if _contains_exclusion_keyword(body_text, rules):
            return "needs_info", ["Possible exclusion keywords present; need clarification on circumstances."], 0.55
        return "eligible", ["Denied boarding/overbooking may qualify under EU261 if involuntary."], 0.8

    if category == "flight_baggage":
        return "needs_info", ["Baggage claims often require PIR and details; use airline policy and/or Montreal Convention."], 0.55

    if _contains_exclusion_keyword(body_text, rules):
        return "possibly_ineligible", ["Potential extraordinary circumstance keywords found in message text."], 0.7
    return "eligible", ["Cancellation may qualify under EU261 absent extraordinary circumstances."], 0.8


def _train_simplified(
    *,
    category: str,
    incident: date | None,
    delay_minutes: int | None,
    body_text: str,
    rules: dict[str, Any],
) -> tuple[str, list[str], float]:
    if category not in {"train_delay", "train_cancellation", "train_baggage"}:
        return "unknown", ["Category is outside current train scope for Agent2."], 0.3

    if incident:
        years_ago = (date.today() - incident).days / 365.25
        if years_ago > 2:
            return "possibly_ineligible", [f"Incident date appears {years_ago:.1f} years old; may be time-barred."], 0.75

    if category == "train_delay":
        threshold = int((((rules or {}).get("eligibility_rules") or {}).get("delay_minutes_threshold") or 60))
        if delay_minutes is None:
            return "needs_info", [f"Need arrival delay in minutes to evaluate >= {threshold} minutes threshold."], 0.55
        if delay_minutes >= threshold:
            return "eligible", [f"Arrival delay appears {delay_minutes} minutes (>= {threshold} minutes)."], 0.75
        return "possibly_ineligible", [f"Arrival delay appears {delay_minutes} minutes (< {threshold} minutes)."], 0.75

    if category == "train_baggage":
        return "needs_info", ["Need details (ticket, itinerary, and report) to evaluate train baggage responsibility."], 0.55

    if _contains_exclusion_keyword(body_text, rules):
        return "needs_info", ["Possible exclusion keywords present; need clarification on circumstances."], 0.55
    return "eligible", ["Cancellation may qualify under rail passenger rights absent exclusions."], 0.65


def _delivery_simplified(*, category: str, body_text: str) -> tuple[str, list[str], float]:
    lowered = body_text.lower()
    if category not in {"delivery_late", "delivery_missing", "delivery_damaged"}:
        return "unknown", ["Category is outside current delivery scope for Agent2."], 0.3
    if category == "delivery_missing":
        return "eligible", ["Package appears not received; request investigation or refund per company policy."], 0.7
    if category == "delivery_damaged":
        return "eligible", ["Item appears damaged; request replacement/refund per company policy."], 0.7
    if any(k in lowered for k in ["late", "delayed", "past due", "missed delivery", "not arrived on time"]):
        return "eligible", ["Delivery appears late; request refund/compensation per company policy."], 0.6
    return "needs_info", ["Need the promised delivery date and current status to assess late delivery policy."], 0.55


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
    form_url: str | None = None,
    original_email_body: str | None = None,
) -> tuple[str, str]:
    vendor_name = vendor or "Customer Support"
    incident_str = incident_date.isoformat() if incident_date else "[INCIDENT_DATE]"
    flight_str = flight_number or "[FLIGHT_NUMBER]"
    booking_str = booking_reference or "[BOOKING_REFERENCE]"
    amount_str = f"{estimated_value} EUR" if estimated_value is not None else "[AMOUNT]"

    # Check if form format is needed (airline-claim.html)
    is_form_format = form_url and "airline-claim.html" in form_url

    if is_form_format:
        # Generate structured form format
        # Extract complaint summary from original email body
        complaint_summary = _extract_complaint_summary(original_email_body or "", flight_number, booking_reference)
        
        subject = f"Compensation Claim Form - {flight_str}"
        body = (
            f"Booking Reference: {booking_str}\n"
            f"Flight Number: {flight_str}\n"
            f"Complaint Summary: {complaint_summary}"
        )
    else:
        # Generate regular email format
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


def _extract_complaint_summary(email_body: str, flight_number: str | None, booking_reference: str | None) -> str:
    """
    Extract a simple complaint summary from the original email body.
    Returns a concise summary of the flight disruption.
    """
    if not email_body or not email_body.strip():
        return "Flight disruption requiring compensation under EU Regulation 261/2004."
    
    # Remove URLs and signatures
    import re
    cleaned = re.sub(r"https?://[^\s]+", "", email_body)
    cleaned = re.sub(r"(?i)(best regards|sincerely|kind regards|regards)[^.]*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"(?i)(customer support|customer service)[^.]*$", "", cleaned, flags=re.MULTILINE)
    
    # Find sentences about delay/cancellation/disruption
    sentences = re.split(r"[.!?]\s+", cleaned)
    relevant = []
    
    keywords = ["delay", "delayed", "cancelled", "canceled", "disruption", "disrupted", "technical", "maintenance"]
    
    for sentence in sentences:
        sentence_lower = sentence.lower().strip()
        if any(keyword in sentence_lower for keyword in keywords):
            # Skip policy/contact references
            if not any(skip in sentence_lower for skip in ["policy", "contact", "visit", "website", "form"]):
                relevant.append(sentence.strip())
                if len(relevant) >= 2:  # Take first 2 relevant sentences
                    break
    
    if relevant:
        summary = ". ".join(relevant)
        if not summary.endswith((".", "!", "?")):
            summary += "."
        return summary
    
    # Fallback: use first paragraph
    paragraphs = cleaned.split("\n\n")
    if paragraphs:
        first_para = paragraphs[0].strip()
        # Limit length
        if len(first_para) > 300:
            first_para = first_para[:300] + "..."
        return first_para
    
    return "Flight disruption requiring compensation under EU Regulation 261/2004."


def _draft_delivery_email(
    *,
    vendor: str | None,
    category: str,
    order_number: str | None,
    tracking_number: str | None,
) -> tuple[str, str]:
    vendor_name = vendor or DEMO_RETAIL_VENDOR
    order_str = order_number or "[ORDER_NUMBER]"
    tracking_str = tracking_number or "[TRACKING_NUMBER]"
    subject = f"Support request: {category.replace('_', ' ')} - order {order_str}"
    body = (
        f"Hello {vendor_name} Support,\n\n"
        f"I need help with a {category.replace('_', ' ')}.\n\n"
        f"Details:\n"
        f"- Order number: {order_str}\n"
        f"- Tracking number: {tracking_str}\n\n"
        f"Please confirm the next steps under your policy (refund/replacement/investigation).\n\n"
        f"Kind regards,\n"
        f"[YOUR_NAME]\n"
        f"[PHONE]\n"
        f"[ADDRESS]\n"
    )
    return subject, body


def _draft_train_email(
    *,
    operator: str | None,
    category: str,
    incident_date: date | None,
    estimated_value: Decimal | None,
) -> tuple[str, str]:
    operator_name = operator or "Train Operator"
    incident_str = incident_date.isoformat() if incident_date else "[INCIDENT_DATE]"
    amount_str = f"{estimated_value} EUR" if estimated_value is not None else "[AMOUNT]"
    subject = f"Passenger rights request: {category.replace('_', ' ')} on {incident_str}"
    body = (
        f"Hello {operator_name},\n\n"
        f"I am requesting assistance/compensation regarding a {category.replace('_', ' ')}.\n\n"
        f"Date: {incident_str}\n"
        f"Requested amount (if applicable): {amount_str}\n\n"
        f"Please confirm the applicable passenger rights policy and next steps.\n\n"
        f"Kind regards,\n"
        f"[YOUR_NAME]\n"
    )
    return subject, body


def _deterministic_fallback(
    *,
    case: dict[str, Any],
    extracted_fields: dict[str, Any] | None,
    kb: dict[str, Any],
    company_site: dict[str, Any] | None,
    domain: str,
) -> dict[str, Any]:
    subject = case.get("email_subject") or ""
    body = case.get("email_body") or ""
    combined_text = f"{subject}\n{body}"

    inferred_category = _normalize_category(_clean_str(case.get("category")), subject, body)
    inferred_vendor = case.get("vendor") or _infer_vendor(subject, body)
    if domain == "marketplace":
        inferred_vendor = inferred_vendor or DEMO_RETAIL_VENDOR

    flight_number = _clean_str(case.get("flight_number")) or _extract_flight_number(combined_text)
    booking_reference = _clean_str(case.get("booking_reference")) or _extract_booking_reference(combined_text)
    incident_date = _extract_incident_date(combined_text, case.get("incident_date"))
    delay_minutes = _extract_delay_minutes(combined_text, extracted_fields)
    route = _extract_route(combined_text, extracted_fields)
    order_number = _extract_order_number(combined_text)
    tracking_number = _extract_tracking_number(combined_text)
    operator = _clean_str((extracted_fields or {}).get("operator")) or _clean_str((extracted_fields or {}).get("train_operator"))

    if domain == "trains":
        eligibility_result, reasons, confidence = _train_simplified(
            category=inferred_category,
            incident=incident_date,
            delay_minutes=delay_minutes,
            body_text=body,
            rules=kb,
        )
    elif domain == "marketplace":
        eligibility_result, reasons, confidence = _delivery_simplified(category=inferred_category, body_text=body)
    else:
        eligibility_result, reasons, confidence = _eu261_simplified(
            category=inferred_category,
            incident=incident_date,
            delay_minutes=delay_minutes,
            body_text=body,
            rules=kb,
        )

    estimated_value = case.get("estimated_value")
    if estimated_value is None and domain == "flights":
        estimated_value = _estimate_value_eur(
            eligibility_result=eligibility_result,
            extracted_fields=extracted_fields,
            rules=kb,
        )
    if estimated_value is None:
        candidate_value = (extracted_fields or {}).get("estimated_value_eur") or (extracted_fields or {}).get("order_value_eur")
        if isinstance(candidate_value, (int, float, str)):
            try:
                estimated_value = Decimal(str(candidate_value))
            except Exception:  # noqa: BLE001
                estimated_value = None

    if domain == "marketplace":
        draft_subject, draft_body = _draft_delivery_email(
            vendor=inferred_vendor,
            category=inferred_category,
            order_number=order_number,
            tracking_number=tracking_number,
        )
    elif domain == "trains":
        draft_subject, draft_body = _draft_train_email(
            operator=operator or inferred_vendor,
            category=inferred_category,
            incident_date=incident_date,
            estimated_value=estimated_value,
        )
    else:
        # Get form_url before calling _draft_email
        form_url = None
        urls = (company_site or {}).get("urls")
        if isinstance(urls, dict):
            form_url = _clean_str(urls.get("claim_form_url"))
        
        draft_subject, draft_body = _draft_email(
            vendor=inferred_vendor,
            category=inferred_category,
            incident_date=incident_date,
            flight_number=flight_number,
            booking_reference=booking_reference,
            estimated_value=estimated_value,
            form_url=form_url,
            original_email_body=body,
        )
    preview = draft_body[:220]

    contact_email = _clean_str((company_site or {}).get("contact_email"))
    if domain == "marketplace" and not contact_email:
        contact_email = _clean_str(case.get("from_email"))
    form_schema = (company_site or {}).get("form_schema")
    # form_url already extracted above for flights domain
    if domain != "flights":
        form_url = None
        urls = (company_site or {}).get("urls")
        if isinstance(urls, dict):
            form_url = _clean_str(urls.get("claim_form_url"))

    return {
        "extraction": {
            "flight_number": flight_number,
            "booking_reference": booking_reference,
            "incident_date": incident_date.isoformat() if incident_date else None,
            "delay_minutes": delay_minutes,
            "route": route,
            "vendor": inferred_vendor,
            "category": inferred_category,
            "order_number": order_number,
            "tracking_number": tracking_number,
            "operator": operator,
        },
        "eligibility": {
            "result": eligibility_result,
            "reasons": reasons,
            "confidence": confidence,
        },
        "claim": {
            "estimated_value_eur": float(estimated_value) if isinstance(estimated_value, Decimal) else estimated_value,
            "basis": ("EU261 local-rule fallback" if domain == "flights" else f"{domain} local-rule fallback"),
        },
        "draft": {
            "subject": draft_subject,
            "body": draft_body,
            "preview": preview,
        },
        "form_data": {
            "form_url": form_url,
            "contact_email": contact_email,
            "form_schema": form_schema,
            "fields_to_fill": {
                "vendor": inferred_vendor,
                "category": inferred_category,
                "incident_date": incident_date.isoformat() if incident_date else None,
                "flight_number": flight_number,
                "booking_reference": booking_reference,
                "delay_minutes": delay_minutes,
                "route": route,
                "order_number": order_number,
                "tracking_number": tracking_number,
                "operator": operator,
                "requested_amount_eur": float(estimated_value) if isinstance(estimated_value, Decimal) else estimated_value,
            },
            "playwright_steps": [
                {"note": "V1 demo: store a fill plan only (no auto-submit)."},
                {"action": "open_url", "url": form_url} if form_url else {"action": "send_email", "to": contact_email},
            ],
        },
    }


def _merge_outputs(
    *,
    case: dict[str, Any],
    fallback: dict[str, Any],
    claude_output: dict[str, Any] | None,
    extracted_fields: dict[str, Any] | None,
    kb: dict[str, Any],
    domain: str,
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
    if isinstance(delay_minutes, (int, float)):
        delay_minutes = int(delay_minutes)
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
    order_number = _clean_str(extraction_ai.get("order_number")) or extraction_fallback.get("order_number")
    tracking_number = _clean_str(extraction_ai.get("tracking_number")) or extraction_fallback.get("tracking_number")
    operator = _clean_str(extraction_ai.get("operator")) or extraction_fallback.get("operator")

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
            "order_number": order_number,
            "tracking_number": tracking_number,
            "operator": operator,
        }
    )

    if domain == "flights" and estimated_value_eur is None and result == "eligible":
        estimated_from_rules = _estimate_value_eur(
            eligibility_result=result,
            extracted_fields=extracted_fields,
            rules=kb,
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
            "order_number": order_number,
            "tracking_number": tracking_number,
            "operator": operator,
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

    category_hint = _normalize_category(_clean_str(case.get("category")), subject, body)
    urls_in_email = _extract_urls(body)
    domain = _infer_domain(category=category_hint, subject=subject, body=body, urls=urls_in_email)

    if domain == "trains":
        kb = _load_train_rules()
        company_site = None
    elif domain == "marketplace":
        kb = dict(MARKETPLACE_BASELINE_KB)
        company_site = _build_company_site_context(subject=subject, body=body, force_family="retail")
    else:
        kb = _load_eu261_rules()
        company_site = _build_company_site_context(subject=subject, body=body, force_family="airline")

    fallback_output = _deterministic_fallback(
        case=case,
        extracted_fields=extracted_fields,
        kb=kb,
        company_site=company_site,
        domain=domain,
    )
    claude_result = run_claude_agent2(
        subject=subject,
        body=body,
        extracted_fields=extracted_fields,
        kb=kb,
        company_site=company_site,
    )
    merged_output = _merge_outputs(
        case=case,
        fallback=fallback_output,
        claude_output=claude_result.output,
        extracted_fields=extracted_fields,
        kb=kb,
        domain=domain,
    )

    extraction = merged_output["extraction"]
    eligibility = merged_output["eligibility"]
    claim = merged_output["claim"]
    draft = merged_output["draft"]
    form_data = merged_output["form_data"]

    if domain == "marketplace":
        extraction["vendor"] = DEMO_RETAIL_VENDOR
        form_data["vendor"] = DEMO_RETAIL_VENDOR

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
            "company_site": company_site or {},
            "domain": domain,
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

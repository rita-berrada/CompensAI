from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime
from typing import Any, Dict, Optional

import streamlit as st

from db import init_db, log_event
from general_claims import build_general_claim_plan
from policy_router import assess_case_payload, classify_case_payload
from tools import load_providers, log_human_review


st.set_page_config(page_title="EU Transport & Delivery Claims Agent", layout="wide")
init_db()


def _get_nested_value(payload: Dict[str, Any], path: str) -> Any:
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _first_value(payload: Dict[str, Any], candidates: list[str]) -> Any:
    for key in candidates:
        if "." in key:
            value = _get_nested_value(payload, key)
            if value is not None:
                return value
        elif key in payload and payload[key] is not None:
            return payload[key]
    return None


def _coerce_date(value: Any) -> Optional[date]:
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


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_from_email_text(email_text: str) -> Dict[str, Any]:
    text = email_text or ""
    lower_text = text.lower()

    provider = None
    for provider_cfg in load_providers():
        names = [provider_cfg.get("name", "")] + provider_cfg.get("aliases", [])
        for name in names:
            if name and name.lower() in lower_text:
                provider = provider_cfg.get("name")
                break
        if provider:
            break

    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    flight_match = re.search(r"\b([A-Z]{2,3}\s?\d{2,4})\b", text)
    route_match = re.search(r"\b([A-Z]{3})\s*(?:->|-|to)\s*([A-Z]{3})\b", text, flags=re.IGNORECASE)
    delay_match = re.search(
        r"(?:arrival\s+)?delay(?:ed)?[^0-9]{0,12}(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)",
        lower_text,
    )
    distance_match = re.search(r"(\d{3,5}(?:\.\d+)?)\s*(?:km|kilometers|kilometres)\b", lower_text)
    name_match = re.search(r"(?:passenger|name)\s*[:\-]\s*([^\n,]+)", text, flags=re.IGNORECASE)

    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if date_match is None:
        date_match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
    if date_match is None:
        date_match = re.search(r"\b(\d{2}-\d{2}-\d{4})\b", text)

    return {
        "provider": provider,
        "flight_number": flight_match.group(1).replace(" ", "") if flight_match else None,
        "flight_date": _coerce_date(date_match.group(1)) if date_match else None,
        "departure_airport": route_match.group(1).upper() if route_match else None,
        "arrival_airport": route_match.group(2).upper() if route_match else None,
        "arrival_delay_hours": _coerce_float(delay_match.group(1)) if delay_match else None,
        "distance_km": _coerce_float(distance_match.group(1)) if distance_match else None,
        "passenger_name": name_match.group(1).strip() if name_match else None,
        "passenger_email": email_match.group(0) if email_match else None,
        "notes": text.strip(),
    }


def _parse_intake_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    email_text = _first_value(payload, ["email_text", "email.body", "email.text", "message", "body", "text"])
    from_email = _extract_from_email_text(str(email_text)) if email_text else {}

    provider = _first_value(payload, ["provider", "airline", "carrier"]) or from_email.get("provider")
    flight_number = _first_value(payload, ["flight_number", "flightNo", "flight.no"]) or from_email.get("flight_number")
    flight_date_raw = _first_value(payload, ["flight_date", "date", "flight.date"]) or from_email.get("flight_date")
    departure_airport = _first_value(payload, ["departure_airport", "origin", "from", "route.from"]) or from_email.get("departure_airport")
    arrival_airport = _first_value(payload, ["arrival_airport", "destination", "to", "route.to"]) or from_email.get("arrival_airport")
    arrival_delay_hours = _first_value(payload, ["arrival_delay_hours", "delay_hours", "delay", "delay_h"]) or from_email.get("arrival_delay_hours")
    distance_km = _first_value(payload, ["distance_km", "distance", "distanceKm"]) or from_email.get("distance_km")
    passenger_name = _first_value(payload, ["passenger_name", "name", "passenger.name"]) or from_email.get("passenger_name")
    passenger_email = _first_value(payload, ["passenger_email", "email", "passenger.email"]) or from_email.get("passenger_email")
    notes = _first_value(payload, ["notes", "description", "issue"]) or from_email.get("notes") or ""

    return {
        "provider": str(provider).strip() if provider is not None else None,
        "flight_number": str(flight_number).strip() if flight_number is not None else None,
        "flight_date": _coerce_date(flight_date_raw),
        "departure_airport": str(departure_airport).strip().upper() if departure_airport is not None else None,
        "arrival_airport": str(arrival_airport).strip().upper() if arrival_airport is not None else None,
        "arrival_delay_hours": _coerce_float(arrival_delay_hours),
        "distance_km": _coerce_float(distance_km),
        "passenger_name": str(passenger_name).strip() if passenger_name is not None else None,
        "passenger_email": str(passenger_email).strip() if passenger_email is not None else None,
        "notes": str(notes).strip(),
    }


st.title("EU Transport & Delivery Claims Agent")
st.caption("JSON-first claims agent with case-type routing, regulatory analysis, and human-in-the-loop drafting.")

if os.getenv("ANTHROPIC_API_KEY"):
    st.success("Mode: LLM-first classification + document-grounded evaluation")
else:
    st.warning("Mode: Heuristic classification fallback + document-grounded evaluation (no ANTHROPIC_API_KEY)")

with st.sidebar:
    st.header("Claim Intake")
    intake_data: Dict[str, Any] = {}
    case_assessment: Optional[Dict[str, Any]] = None
    case_classification: Optional[Dict[str, Any]] = None
    source_payload: Dict[str, Any] = {}
    uploaded = st.file_uploader("Upload intake JSON", type=["json"])
    if uploaded is not None:
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Root JSON value must be an object")
            source_payload = dict(payload)
            intake_data = _parse_intake_json(payload)
            assessment_payload = dict(payload)
            assessment_payload.update({k: v for k, v in intake_data.items() if v is not None and str(v).strip()})
            case_classification = classify_case_payload(assessment_payload)
            case_assessment = assess_case_payload(
                assessment_payload,
                case_type_override=str(case_classification.get("case_type", "")),
            )
            st.caption("Case type classification")
            st.json(case_classification)
            st.caption("Extracted intake values")
            st.json(intake_data)
            st.caption("Detected policy and case requirements")
            st.json(case_assessment)
        except Exception as exc:
            st.error(f"Failed to parse JSON: {exc}")

    run_agent = st.button("Run Agent", type="primary")

if run_agent:
    if not intake_data:
        st.error("Upload a valid JSON file first.")
        st.stop()

    claim_id = str(uuid.uuid4())
    merged_payload = dict(source_payload)
    merged_payload.update({k: v for k, v in intake_data.items() if v not in (None, "")})
    general_plan = build_general_claim_plan(merged_payload, case_assessment or {})
    st.session_state["general_plan"] = general_plan
    st.session_state["claim_plan"] = None
    st.session_state["claim_id"] = claim_id
    log_event(claim_id, "claim_intake", merged_payload)
    log_event(claim_id, "general_claim_plan", general_plan)
    st.success(f"Agent completed for claim_id={claim_id}")

general_plan = st.session_state.get("general_plan")
if general_plan is not None:
    st.subheader("Policy Match")
    st.write(f"**Case type:** {general_plan.get('case_type')}")
    st.write(f"**Policy:** {general_plan.get('legal_instrument')}")
    if general_plan.get("legal_hooks"):
        st.write("**Legal hooks:**")
        for hook in general_plan.get("legal_hooks") or []:
            st.write(f"- {hook}")
    missing_fields = general_plan.get("missing_fields") or []
    st.write(f"**Missing fields:** {', '.join(missing_fields) if missing_fields else 'None'}")

    eligibility = general_plan.get("eligibility") or {}
    st.subheader("Eligibility")
    c1, c2, c3 = st.columns(3)
    c1.metric("Potentially Eligible", "Yes" if eligibility.get("eligible") else "No")
    c2.metric("Confidence", f"{float(eligibility.get('confidence', 0.0)):.2f}")
    c3.metric("Case Type", str(general_plan.get("case_type", "unknown")).replace("_", " ").title())
    st.write(f"**Rationale:** {eligibility.get('rationale', 'N/A')}")
    st.write(f"**Expected outcome:** {eligibility.get('expected_outcome', 'N/A')}")
    if eligibility.get("missing_info"):
        st.write(f"**Missing info:** {', '.join(eligibility.get('missing_info') or [])}")

    channel = general_plan.get("channel") or {}
    st.subheader("Submission Channel")
    st.write(f"**Channel:** {channel.get('channel_type', 'unknown')}")
    st.write(f"**Destination:** {channel.get('destination', 'N/A')}")

    draft = general_plan.get("draft") or {}
    st.subheader("Draft Claim (Human-in-the-loop)")
    edited_subject = st.text_input("Subject", value=draft.get("subject", ""))
    edited_body = st.text_area("Body", value=draft.get("body", ""), height=280)
    if st.button("Approve & Simulate Submission", key="approve_non_flight"):
        claim_id = st.session_state.get("claim_id", str(uuid.uuid4()))
        log_human_review(claim_id, True, edited_subject, edited_body)
        log_event(
            claim_id,
            "submission_simulated",
            {"channel": channel.get("channel_type"), "destination": channel.get("destination"), "subject": edited_subject},
        )
        st.success("Approved and simulated submission logged.")

    if channel.get("channel_type") == "form":
        st.subheader("Form Payload Preview")
        form_preview = general_plan.get("form_payload_preview", {}).get("fields", {})
        st.json(form_preview)

    st.write(f"**Citation requirement met:** {'Yes' if general_plan.get('citation_requirement_met') else 'No'}")
    if general_plan.get("article_references"):
        st.write(f"**Article references:** {', '.join(general_plan.get('article_references') or [])}")

    citations = general_plan.get("citations") or []
    if citations:
        st.subheader("Regulatory Citations")
        for cite in citations:
            st.write(f"- {cite.get('chunk_id')} | {cite.get('title')} | score={float(cite.get('score', 0.0)):.3f}")
            st.caption(str(cite.get("text", "")))
else:
    st.info("Upload intake JSON and click 'Run Agent'.")

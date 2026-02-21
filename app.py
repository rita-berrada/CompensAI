from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime
from typing import Any, Dict, Optional

import streamlit as st
from pydantic import ValidationError

from agent import run_claim_agent
from db import init_db, log_event
from general_claims import build_general_claim_plan
from policy_router import assess_case_payload
from schemas import ClaimIntake
from tools import load_providers, log_human_review


st.set_page_config(page_title="EU261 Compensation Claim Agent", layout="wide")
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


st.title("EU261 Compensation Claim Agent")
st.caption("Hackathon demo app with tool-calling orchestrator + deterministic fallback mode.")

if os.getenv("ANTHROPIC_API_KEY"):
    st.success("Mode: Claude tool-calling")
else:
    st.warning("Mode: Deterministic fallback (no ANTHROPIC_API_KEY)")

with st.sidebar:
    st.header("Claim Intake")
    intake_mode = st.radio("Input Mode", options=["JSON file", "Manual"], horizontal=True)
    intake_data: Dict[str, Any] = {}
    case_assessment: Optional[Dict[str, Any]] = None
    source_payload: Dict[str, Any] = {}

    if intake_mode == "JSON file":
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
                case_assessment = assess_case_payload(assessment_payload)
                st.caption("Extracted intake values")
                st.json(intake_data)
                st.caption("Detected policy and case requirements")
                st.json(case_assessment)
            except Exception as exc:
                st.error(f"Failed to parse JSON: {exc}")
    else:
        provider = st.text_input("Airline/Provider", value="Lufthansa")
        flight_number = st.text_input("Flight Number", value="LH123")
        flight_date = st.date_input("Flight Date", value=date.today())
        departure_airport = st.text_input("Departure Airport", value="FRA")
        arrival_airport = st.text_input("Arrival Airport", value="MAD")
        arrival_delay_hours = st.number_input("Arrival Delay (hours)", min_value=0.0, max_value=24.0, value=3.5, step=0.5)
        distance_km = st.number_input("Distance (km, optional)", min_value=0.0, value=1450.0, step=10.0)
        use_distance = st.checkbox("Include distance", value=True)
        passenger_name = st.text_input("Passenger Name", value="Jane Doe")
        passenger_email = st.text_input("Passenger Email", value="jane.doe@example.com")
        notes = st.text_area("Notes", value="Flight arrived late due to operational issues.")
        intake_data = {
            "provider": provider,
            "flight_number": flight_number,
            "flight_date": flight_date,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
            "arrival_delay_hours": arrival_delay_hours,
            "distance_km": distance_km if use_distance else None,
            "passenger_name": passenger_name,
            "passenger_email": passenger_email,
            "notes": notes,
        }
        source_payload = dict(intake_data)
        case_assessment = assess_case_payload(
            {
                "case_type": "flight",
                **intake_data,
            }
        )

    run_agent = st.button("Run Agent", type="primary")

if run_agent:
    if intake_mode == "JSON file" and not intake_data:
        st.error("Upload a valid JSON file first.")
        st.stop()

    claim_id = str(uuid.uuid4())
    case_type = (case_assessment or {}).get("case_type", "unknown")
    if case_type != "flight":
        merged_payload = dict(source_payload)
        merged_payload.update({k: v for k, v in intake_data.items() if v not in (None, "")})
        general_plan = build_general_claim_plan(merged_payload, case_assessment or {})
        st.session_state["general_plan"] = general_plan
        st.session_state["claim_plan"] = None
        st.session_state["claim_id"] = claim_id
        log_event(claim_id, "claim_intake_non_flight", merged_payload)
        log_event(claim_id, "general_claim_plan", general_plan)
        st.success(f"Agent completed for claim_id={claim_id}")
    else:
        try:
            intake = ClaimIntake(
                claim_id=claim_id,
                provider=intake_data.get("provider"),
                flight_number=intake_data.get("flight_number"),
                flight_date=intake_data.get("flight_date"),
                departure_airport=intake_data.get("departure_airport"),
                arrival_airport=intake_data.get("arrival_airport"),
                arrival_delay_hours=intake_data.get("arrival_delay_hours"),
                distance_km=intake_data.get("distance_km"),
                passenger_name=intake_data.get("passenger_name"),
                passenger_email=intake_data.get("passenger_email"),
                notes=intake_data.get("notes", ""),
            )
        except ValidationError as e:
            st.error(f"Invalid intake data: {e}")
            st.stop()

        log_event(claim_id, "claim_intake", intake.model_dump(mode="json"))
        with st.spinner("Running orchestrator agent..."):
            plan = run_claim_agent(intake)
        st.session_state["claim_plan"] = plan
        st.session_state["general_plan"] = None
        st.session_state["claim_id"] = claim_id
        st.success(f"Agent completed for claim_id={claim_id}")

general_plan = st.session_state.get("general_plan")
if general_plan is not None:
    st.subheader("Policy Match")
    st.write(f"**Case type:** {general_plan.get('case_type')}")
    st.write(f"**Policy:** {general_plan.get('legal_instrument')}")
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

plan = st.session_state.get("claim_plan")
if plan is not None:
    st.subheader("Eligibility")
    c1, c2, c3 = st.columns(3)
    c1.metric("Eligible", "Yes" if plan.eligibility.eligible else "No")
    c2.metric("Compensation (EUR)", plan.eligibility.compensation_eur if plan.eligibility.compensation_eur else "N/A")
    c3.metric("Confidence", f"{plan.eligibility.confidence:.2f}")
    st.write(f"**Legal basis:** {plan.eligibility.legal_basis}")
    st.write(f"**Rationale:** {plan.eligibility.rationale}")
    if plan.eligibility.missing_info:
        st.write(f"**Missing info:** {', '.join(plan.eligibility.missing_info)}")

    st.subheader("RAG Citations")
    if plan.rag_citations:
        for cite in plan.rag_citations:
            with st.expander(f"{cite.chunk_id} | {cite.title} | score={cite.score:.3f}"):
                st.write(cite.text)
    else:
        st.info("No citations found.")

    st.subheader("Submission Channel")
    st.write(f"**Provider:** {plan.channel.provider}")
    st.write(f"**Channel:** {plan.channel.channel_type}")
    if plan.channel.destination:
        st.write(f"**Destination:** {plan.channel.destination}")
    if plan.channel.required_fields:
        st.write(f"**Required fields:** {', '.join(plan.channel.required_fields)}")
    if plan.channel.notes:
        st.write(f"**Notes:** {plan.channel.notes}")

    claim_id = st.session_state.get("claim_id", plan.intake.claim_id)
    if plan.channel.channel_type == "email" and plan.draft:
        st.subheader("Draft Email (Human-in-the-loop)")
        edited_subject = st.text_input("Subject", value=plan.draft.subject)
        edited_body = st.text_area("Body", value=plan.draft.body, height=280)
        if st.button("Approve & Simulate Submission"):
            log_human_review(claim_id, True, edited_subject, edited_body)
            log_event(
                claim_id,
                "submission_simulated",
                {"channel": "email", "destination": plan.channel.destination, "subject": edited_subject},
            )
            st.success("Approved and simulated email submission logged.")
    elif plan.channel.channel_type == "form" and plan.form_payload_preview:
        st.subheader("Form Payload Preview")
        st.json(plan.form_payload_preview.fields)
        if st.button("Approve & Simulate Submission"):
            log_human_review(claim_id, True, "(form submission)", str(plan.form_payload_preview.fields))
            log_event(
                claim_id,
                "submission_simulated",
                {"channel": "form", "destination": plan.channel.destination, "payload": plan.form_payload_preview.fields},
            )
            st.success("Approved and simulated form submission logged.")
    else:
        st.info("Unknown provider channel. Add it in data/providers.json.")

    with st.expander("Tool Trace"):
        for t in plan.tool_trace:
            st.code(t)
else:
    st.info("Upload JSON or fill manual intake, then click 'Run Agent'.")

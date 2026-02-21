from __future__ import annotations

import os
import uuid
from datetime import date

import streamlit as st
from pydantic import ValidationError

from agent import run_claim_agent
from db import init_db, log_event
from schemas import ClaimIntake
from tools import log_human_review


st.set_page_config(page_title="EU261 Compensation Claim Agent", layout="wide")
init_db()

st.title("EU261 Compensation Claim Agent")
st.caption("Hackathon demo app with tool-calling orchestrator + deterministic fallback mode.")

if os.getenv("ANTHROPIC_API_KEY"):
    st.success("Mode: Claude tool-calling")
else:
    st.warning("Mode: Deterministic fallback (no ANTHROPIC_API_KEY)")

with st.sidebar:
    st.header("Claim Intake")
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
    run_agent = st.button("Run Agent", type="primary")

if run_agent:
    claim_id = str(uuid.uuid4())
    try:
        intake = ClaimIntake(
            claim_id=claim_id,
            provider=provider,
            flight_number=flight_number,
            flight_date=flight_date,
            departure_airport=departure_airport,
            arrival_airport=arrival_airport,
            arrival_delay_hours=arrival_delay_hours,
            distance_km=(distance_km if use_distance else None),
            passenger_name=passenger_name,
            passenger_email=passenger_email,
            notes=notes,
        )
    except ValidationError as e:
        st.error(f"Invalid intake data: {e}")
        st.stop()

    log_event(claim_id, "claim_intake", intake.model_dump(mode="json"))
    with st.spinner("Running orchestrator agent..."):
        plan = run_claim_agent(intake)
    st.session_state["claim_plan"] = plan
    st.session_state["claim_id"] = claim_id
    st.success(f"Agent completed for claim_id={claim_id}")

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
    st.info("Fill intake fields in the sidebar and click 'Run Agent'.")

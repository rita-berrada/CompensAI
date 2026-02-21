from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import log_event
from rag import Eu261RAG
from schemas import ClaimChannel, ClaimIntake, EmailDraft, EligibilityResult, FormPayloadPreview

PROVIDERS_PATH = Path("data/providers.json")


def load_providers() -> List[Dict[str, Any]]:
    return _load_providers_cached()


@lru_cache(maxsize=1)
def _load_providers_cached() -> List[Dict[str, Any]]:
    if not PROVIDERS_PATH.exists():
        return []
    with PROVIDERS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def rag_policy(rag: Eu261RAG, query: str, k: int = 4) -> Dict[str, Any]:
    cites = rag.retrieve(query, k=k)
    return {"citations": [c.model_dump() for c in cites]}


def check_eu261(intake: ClaimIntake) -> EligibilityResult:
    legal_basis = "EU261/2004 compensation typically applies for arrival delays >= 3 hours."
    missing_info: List[str] = []
    if intake.distance_km is None:
        missing_info.append("distance_km")
    if intake.arrival_delay_hours < 3:
        return EligibilityResult(
            eligible=False,
            compensation_eur=None,
            rationale=f"Reported arrival delay is {intake.arrival_delay_hours:.1f}h, below the 3h threshold.",
            legal_basis=legal_basis,
            missing_info=missing_info,
            confidence=0.86,
        )

    comp = None
    if intake.distance_km is not None:
        d = intake.distance_km
        if d <= 1500:
            comp = 250
        elif d <= 3500:
            comp = 400
        else:
            comp = 600

    rationale = "Arrival delay meets >=3h heuristic."
    if comp is not None:
        rationale += f" Distance {intake.distance_km:.0f}km suggests {comp} EUR bracket."
    else:
        rationale += " Distance missing; compensation bracket cannot be finalized."

    return EligibilityResult(
        eligible=True,
        compensation_eur=comp,
        rationale=rationale,
        legal_basis=legal_basis,
        missing_info=missing_info,
        confidence=0.79 if comp is None else 0.9,
    )


def find_claim_channel(provider: str) -> ClaimChannel:
    providers = load_providers()
    lower = (provider or "").strip().lower()
    if not lower:
        return ClaimChannel(provider=provider or "Unknown", channel_type="unknown", notes="Provider is missing.")
    for p in providers:
        aliases = [str(p.get("name", "")).lower()] + [str(a).lower() for a in p.get("aliases", [])]
        if lower in aliases:
            ch = p.get("channel", {})
            ch_type = ch.get("type", "unknown")
            return ClaimChannel(
                provider=p.get("name", provider),
                channel_type=ch_type,
                destination=ch.get("destination"),
                required_fields=ch.get("required_fields", []),
                notes=ch.get("notes", ""),
            )
    return ClaimChannel(provider=provider, channel_type="unknown", notes="Provider not found in local directory.")


def draft_email(intake: ClaimIntake, eligibility: EligibilityResult, channel: ClaimChannel) -> EmailDraft:
    compensation_line = (
        f"I request compensation of EUR {eligibility.compensation_eur} under EU261."
        if eligibility.compensation_eur is not None
        else "I request compensation under EU261 and ask you to confirm the applicable amount."
    )
    subject = f"EU261 compensation claim - {intake.flight_number} on {intake.flight_date.isoformat()}"
    distance_line = f"Distance: {intake.distance_km:.0f} km\n" if intake.distance_km is not None else ""
    body = (
        f"Dear {channel.provider} claims team,\n\n"
        f"I am submitting a compensation claim under EU Regulation 261/2004.\n\n"
        f"Passenger: {intake.passenger_name}\n"
        f"Email: {intake.passenger_email}\n"
        f"Flight: {intake.flight_number}\n"
        f"Date: {intake.flight_date.isoformat()}\n"
        f"Route: {intake.departure_airport} -> {intake.arrival_airport}\n"
        f"Reported arrival delay: {intake.arrival_delay_hours:.1f} hours\n"
        f"{distance_line}"
        f"Notes: {intake.notes or 'N/A'}\n\n"
        f"{compensation_line}\n\n"
        "Please process this claim and confirm receipt.\n\n"
        "Kind regards,\n"
        f"{intake.passenger_name}"
    )
    return EmailDraft(subject=subject, body=body)


def build_form_payload_preview(
    intake: ClaimIntake, eligibility: EligibilityResult, channel: ClaimChannel
) -> FormPayloadPreview:
    payload = {
        "provider": channel.provider,
        "flight_number": intake.flight_number,
        "flight_date": intake.flight_date.isoformat(),
        "route": f"{intake.departure_airport}-{intake.arrival_airport}",
        "arrival_delay_hours": intake.arrival_delay_hours,
        "distance_km": intake.distance_km,
        "passenger_name": intake.passenger_name,
        "passenger_email": str(intake.passenger_email),
        "notes": intake.notes,
        "eu261_eligible": eligibility.eligible,
        "requested_compensation_eur": eligibility.compensation_eur,
    }
    filtered = {k: v for k, v in payload.items() if v is not None}
    return FormPayloadPreview(fields=filtered)


def log_human_review(claim_id: str, approved: bool, edited_subject: str, edited_body: str) -> Dict[str, Any]:
    payload = {
        "approved": approved,
        "edited_subject": edited_subject,
        "edited_body": edited_body,
    }
    log_event(claim_id, "human_review", payload)
    return {"ok": True, "payload": payload}

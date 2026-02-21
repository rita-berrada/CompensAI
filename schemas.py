from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class ClaimIntake(BaseModel):
    claim_id: str
    provider: str
    flight_number: str
    flight_date: date
    departure_airport: str
    arrival_airport: str
    arrival_delay_hours: float
    distance_km: Optional[float] = None
    passenger_name: str
    passenger_email: EmailStr
    notes: Optional[str] = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RagCitation(BaseModel):
    chunk_id: str
    title: str
    score: float
    text: str


class EligibilityResult(BaseModel):
    eligible: bool
    compensation_eur: Optional[int]
    rationale: str
    legal_basis: str
    missing_info: List[str] = Field(default_factory=list)
    confidence: float


class ClaimChannel(BaseModel):
    provider: str
    channel_type: Literal["email", "form", "unknown"]
    destination: Optional[str] = None
    required_fields: List[str] = Field(default_factory=list)
    notes: Optional[str] = ""


class EmailDraft(BaseModel):
    subject: str
    body: str


class FormPayloadPreview(BaseModel):
    fields: Dict[str, Any]


class ClaimPlan(BaseModel):
    intake: ClaimIntake
    eligibility: EligibilityResult
    channel: ClaimChannel
    draft: Optional[EmailDraft] = None
    form_payload_preview: Optional[FormPayloadPreview] = None
    rag_citations: List[RagCitation] = Field(default_factory=list)
    tool_trace: List[str] = Field(default_factory=list)


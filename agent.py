from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from db import log_event
from rag import Eu261RAG
from schemas import ClaimChannel, ClaimIntake, ClaimPlan, EmailDraft, EligibilityResult, FormPayloadPreview, RagCitation
from tools import (
    build_form_payload_preview,
    check_eu261,
    draft_email,
    find_claim_channel,
    rag_policy,
)

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


SYSTEM_PROMPT = (
    "You are an AI claims agent grounded in EU261. "
    "You must use tools to gather policy snippets, assess eligibility, choose submission channel, "
    "and prepare either email draft or form payload. Return a structured plan."
)


def _build_openai_client() -> Optional[object]:
    if not os.getenv("OPENAI_API_KEY") or OpenAI is None:
        return None
    return OpenAI()


def _tool_spec() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "rag_policy",
            "description": "Retrieve relevant EU261 policy snippets with citations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": "check_eu261",
            "description": "Heuristic EU261 eligibility check with compensation bracket.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "find_claim_channel",
            "description": "Find airline claim submission route from local provider directory.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "draft_email",
            "description": "Draft EU261 complaint email.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "form_payload_preview",
            "description": "Generate form payload preview for provider forms.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ]


def _extract_text(response: Any) -> str:
    out = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", None) in {"output_text", "text"}:
                    out.append(getattr(c, "text", ""))
    return "\n".join([x for x in out if x]).strip()


def _fallback_plan(intake: ClaimIntake, rag: Eu261RAG) -> ClaimPlan:
    citations = rag.retrieve(
        query=f"EU261 delay {intake.arrival_delay_hours}h flight {intake.flight_number} {intake.provider}", k=4
    )
    eligibility = check_eu261(intake)
    channel = find_claim_channel(intake.provider)
    draft: Optional[EmailDraft] = None
    form_preview: Optional[FormPayloadPreview] = None
    if channel.channel_type == "email":
        draft = draft_email(intake, eligibility, channel)
    elif channel.channel_type == "form":
        form_preview = build_form_payload_preview(intake, eligibility, channel)
    return ClaimPlan(
        intake=intake,
        eligibility=eligibility,
        channel=channel,
        draft=draft,
        form_payload_preview=form_preview,
        rag_citations=citations,
        tool_trace=["fallback::check_eu261", "fallback::find_claim_channel", "fallback::draft_or_form"],
    )


def run_claim_agent(intake: ClaimIntake, max_iters: int = 7) -> ClaimPlan:
    client = _build_openai_client()
    rag = Eu261RAG(openai_client=client)
    if client is None:
        plan = _fallback_plan(intake, rag)
        log_event(intake.claim_id, "agent_run", {"mode": "fallback", "tool_trace": plan.tool_trace})
        return plan

    eligibility: Optional[EligibilityResult] = None
    channel: Optional[ClaimChannel] = None
    draft: Optional[EmailDraft] = None
    form_preview: Optional[FormPayloadPreview] = None
    citations: List[RagCitation] = []
    tool_trace: List[str] = []

    def call_local_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal eligibility, channel, draft, form_preview, citations
        if name == "rag_policy":
            res = rag_policy(rag, query=arguments.get("query", ""), k=int(arguments.get("k", 4)))
            citations = [RagCitation(**c) for c in res.get("citations", [])]
            return res
        if name == "check_eu261":
            eligibility = check_eu261(intake)
            return eligibility.model_dump()
        if name == "find_claim_channel":
            channel = find_claim_channel(intake.provider)
            return channel.model_dump()
        if name == "draft_email":
            if eligibility is None:
                eligibility = check_eu261(intake)
            if channel is None:
                channel = find_claim_channel(intake.provider)
            draft = draft_email(intake, eligibility, channel)
            return draft.model_dump()
        if name == "form_payload_preview":
            if eligibility is None:
                eligibility = check_eu261(intake)
            if channel is None:
                channel = find_claim_channel(intake.provider)
            form_preview = build_form_payload_preview(intake, eligibility, channel)
            return form_preview.model_dump()
        return {"error": f"unknown tool: {name}"}

    user_prompt = (
        "Create claim plan for the intake below. Must call rag_policy, check_eu261, find_claim_channel, "
        "and then either draft_email or form_payload_preview.\n"
        f"Intake JSON:\n{intake.model_dump_json(indent=2)}"
    )
    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=SYSTEM_PROMPT,
        input=user_prompt,
        tools=_tool_spec(),
        tool_choice="auto",
    )

    for _ in range(max_iters):
        function_calls = [o for o in (response.output or []) if getattr(o, "type", None) == "function_call"]
        if not function_calls:
            break
        outputs = []
        for call in function_calls:
            tool_name = call.name
            args = json.loads(call.arguments or "{}")
            result = call_local_tool(tool_name, args)
            tool_trace.append(f"{tool_name}({args})")
            outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)})

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            previous_response_id=response.id,
            input=outputs,
            tools=_tool_spec(),
            tool_choice="auto",
        )

    if eligibility is None:
        eligibility = check_eu261(intake)
    if channel is None:
        channel = find_claim_channel(intake.provider)
    if not citations:
        citations = rag.retrieve(f"EU261 delay rules for {intake.provider} {intake.flight_number}", k=4)
    if channel.channel_type == "email" and draft is None:
        draft = draft_email(intake, eligibility, channel)
    if channel.channel_type == "form" and form_preview is None:
        form_preview = build_form_payload_preview(intake, eligibility, channel)

    plan = ClaimPlan(
        intake=intake,
        eligibility=eligibility,
        channel=channel,
        draft=draft,
        form_payload_preview=form_preview,
        rag_citations=citations,
        tool_trace=tool_trace + ([f"assistant_summary::{_extract_text(response)[:180]}"] if _extract_text(response) else []),
    )
    log_event(
        intake.claim_id,
        "agent_run",
        {"mode": "openai_tools", "tool_trace": plan.tool_trace, "response_id": getattr(response, "id", None)},
    )
    return plan


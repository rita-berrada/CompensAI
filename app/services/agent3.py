from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


SUCCESS_FEE_RATE = Decimal("0.10")
INVOICE_CURRENCY = "eur"
INVOICE_DESCRIPTION = "ClearClaim: 10% Success Fee for Dispute Resolution"
RESOLVED_STATUS = "RESOLVED_SUCCESS"


class Agent3Error(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise Agent3Error(f"Missing required env var: {name}")
    return value


def _require_state_key(state: dict[str, Any], key: str) -> Any:
    if key not in state:
        raise Agent3Error(f"Missing required state key: {key}")
    value = state.get(key)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise Agent3Error(f"State key {key!r} is empty")
    return value


def _to_decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise Agent3Error(f"Invalid decimal in state key {field_name!r}: {value!r}") from exc


def _fee_cents_from_recovered(recovered_amount_eur: Decimal) -> int:
    if recovered_amount_eur <= 0:
        raise Agent3Error("recovered_amount_eur must be greater than 0")
    fee_eur = (recovered_amount_eur * SUCCESS_FEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(fee_eur * 100)


def _create_and_send_stripe_invoice(*, user_email: str, fee_cents: int) -> tuple[str, str, str]:
    import stripe  # type: ignore

    stripe.api_key = _require_env("STRIPE_SECRET_KEY")

    customer = stripe.Customer.create(email=user_email)
    stripe.InvoiceItem.create(
        customer=customer.id,
        amount=fee_cents,
        currency=INVOICE_CURRENCY,
        description=INVOICE_DESCRIPTION,
    )
    invoice = stripe.Invoice.create(
        customer=customer.id,
        collection_method="send_invoice",
        days_until_due=7,
    )
    sent_invoice = stripe.Invoice.send_invoice(invoice.id)

    hosted_invoice_url = getattr(sent_invoice, "hosted_invoice_url", None) or sent_invoice.get("hosted_invoice_url")
    if not hosted_invoice_url:
        raise Agent3Error(f"Stripe invoice {invoice.id} did not return hosted_invoice_url")
    return customer.id, invoice.id, str(hosted_invoice_url)


def _load_draft_payload_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _update_supabase_dispute(*, dispute_id: str, stripe_invoice_url: str) -> None:
    from supabase import create_client  # type: ignore

    supabase = create_client(
        _require_env("SUPABASE_URL"),
        _require_env("SUPABASE_SERVICE_ROLE_KEY"),
    )

    existing = supabase.table("disputes").select("draft_payload_json").eq("id", dispute_id).limit(1).execute()
    rows = existing.data or []
    if not rows:
        raise Agent3Error(f"No disputes row found for id={dispute_id}")

    draft_payload_json = _load_draft_payload_json(rows[0].get("draft_payload_json"))
    draft_payload_json["stripe_invoice_url"] = stripe_invoice_url

    updated = (
        supabase.table("disputes")
        .update(
            {
                "status": RESOLVED_STATUS,
                "draft_payload_json": draft_payload_json,
            }
        )
        .eq("id", dispute_id)
        .execute()
    )
    if not updated.data:
        raise Agent3Error(f"Failed to update disputes row for id={dispute_id}")


def run_agent3(state: dict[str, Any]) -> dict[str, Any]:
    """
    Agent 3 node for LangGraph:
    - reads dispute_id, user_email, recovered_amount_eur from state
    - creates/sends Stripe invoice (10% success fee)
    - updates Supabase disputes.status + disputes.draft_payload_json.stripe_invoice_url
    - returns state with agent3 metadata
    """

    dispute_id = str(_require_state_key(state, "dispute_id"))
    user_email = str(_require_state_key(state, "user_email"))
    recovered_amount_eur = _to_decimal(_require_state_key(state, "recovered_amount_eur"), field_name="recovered_amount_eur")

    fee_cents = _fee_cents_from_recovered(recovered_amount_eur)
    customer_id, invoice_id, hosted_invoice_url = _create_and_send_stripe_invoice(
        user_email=user_email,
        fee_cents=fee_cents,
    )

    _update_supabase_dispute(dispute_id=dispute_id, stripe_invoice_url=hosted_invoice_url)

    return {
        **state,
        "agent3": {
            "success": True,
            "dispute_id": dispute_id,
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "stripe_invoice_url": hosted_invoice_url,
            "fee_cents": fee_cents,
        },
    }

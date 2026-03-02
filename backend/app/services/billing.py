from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.db.supabase import get_supabase
from app.repositories.cases import insert_event, update_case


def run_billing_if_resolved(case: dict[str, Any], *, recovered_amount: Decimal | None, currency: str | None) -> None:
    """
    Demo-friendly billing: Calculate recovered amount and 10% fee.
    No Stripe integration - just stores financial data for dashboard display.
    """
    db = get_supabase()

    # Get recovered amount (from vendor_response or fallback to estimated_value)
    recovered = recovered_amount
    if recovered is None:
        # Fallback to "estimated_value as recovered" for demo
        try:
            recovered = Decimal(str(case.get("estimated_value") or "0"))
        except Exception:  # noqa: BLE001
            recovered = Decimal("0")

    # Calculate 10% fee (hardcoded for demo)
    fee_rate = Decimal("0.1")  # 10% fee rate
    fee_amount = (recovered * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    currency_value = (currency or "eur").lower()

    # Store billing info in decision_json
    decision_json = case.get("decision_json") or {}
    decision_json["billing"] = {
        "recovered_amount": float(recovered),
        "currency": currency_value,
        "success_fee_rate": float(fee_rate),
        "success_fee_amount": float(fee_amount),
        "status": "resolved",
    }

    # Update case with financial fields for dashboard
    updates: dict[str, Any] = {
        "status": "resolved",
        "decision_json": decision_json,
        # Top-level financial fields for easy dashboard access
        "recovered_amount": float(recovered),
        "fee_amount": float(fee_amount),
    }

    insert_event(db, case_id=case["id"], actor="system", event_type="resolved", details={"status": "resolved"})
    update_case(db, case["id"], updates)
    insert_event(db, case_id=case["id"], actor="agent3", event_type="billing_created", details=decision_json["billing"])


def calculate_fee_and_create_payment_link(case: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate the 10% success fee from estimated_value and (if Stripe is configured)
    create a Checkout Session so the customer can pay CompensAI.

    Does NOT change case status — call this from the approve endpoint so the fee
    and payment link are visible on the dashboard immediately after approval.
    Returns a dict of DB fields ready to pass to update_case().
    """
    from app.core.config import settings  # late import avoids circular dependency

    try:
        estimated = Decimal(str(case.get("estimated_value") or "0"))
    except Exception:  # noqa: BLE001
        estimated = Decimal("0")

    fee_rate = Decimal("0.1")
    fee_amount = (estimated * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    updates: dict[str, Any] = {
        "fee_amount": float(fee_amount),
        "recovered_amount": float(estimated),
    }

    if settings.stripe_secret_key:
        try:
            import stripe as _stripe  # noqa: PLC0415
            _stripe.api_key = settings.stripe_secret_key
            fee_cents = int(fee_amount * 100)
            if fee_cents > 0:
                session = _stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": "eur",
                            "product_data": {"name": f"CompensAI Success Fee — Case {case['id']}"},
                            "unit_amount": fee_cents,
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    success_url=settings.stripe_success_url,
                    cancel_url=settings.stripe_cancel_url,
                )
                updates["stripe_checkout_url"] = session.url
                updates["stripe_checkout_session_id"] = session.id
        except Exception:  # noqa: BLE001
            pass  # Stripe unavailable — fee_amount is still saved

    return updates

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.core.config import settings
from app.db.supabase import get_supabase
from app.repositories.cases import insert_event, update_case


def _money_to_cents(amount: Decimal) -> int:
    q = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(q * 100)


def _maybe_create_stripe_checkout_session(*, fee_amount: Decimal, currency: str, case_id: str) -> dict[str, Any] | None:
    if not settings.stripe_secret_key:
        return None
    try:
        import stripe  # type: ignore

        stripe.api_key = settings.stripe_secret_key
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "product_data": {"name": "CompensAI success fee"},
                        "unit_amount": _money_to_cents(fee_amount),
                    },
                    "quantity": 1,
                }
            ],
            success_url=settings.stripe_success_url,
            cancel_url=settings.stripe_cancel_url,
            metadata={"case_id": case_id},
        )
        return {"checkout_session_id": session.id, "url": session.url}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def run_billing_if_resolved(case: dict[str, Any], *, recovered_amount: Decimal | None, currency: str | None) -> None:
    # Minimal: always create a billing_created event once the case is resolved.
    db = get_supabase()

    recovered = recovered_amount
    if recovered is None:
        # Fallback to "estimated_value as recovered" heuristic.
        try:
            recovered = Decimal(str(case.get("estimated_value") or "0"))
        except Exception:  # noqa: BLE001
            recovered = Decimal("0")

    fee_rate = Decimal(str(settings.success_fee_rate))
    fee_amount = (recovered * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    currency_value = (currency or "eur").lower()

    stripe_info = None
    billing_link = None
    if fee_amount > 0:
        stripe_info = _maybe_create_stripe_checkout_session(fee_amount=fee_amount, currency=currency_value, case_id=case["id"])
        if stripe_info and stripe_info.get("url"):
            billing_link = stripe_info["url"]
        else:
            billing_link = f"billing://case/{case['id']}"

    decision_json = case.get("decision_json") or {}
    decision_json["billing"] = {
        "recovered_amount": float(recovered),
        "currency": currency_value,
        "success_fee_rate": float(fee_rate),
        "success_fee_amount": float(fee_amount),
        "billing_link": billing_link,
        "stripe": stripe_info,
    }

    insert_event(db, case_id=case["id"], actor="system", event_type="resolved", details={"status": "resolved"})
    update_case(db, case["id"], {"status": "resolved", "decision_json": decision_json})
    insert_event(db, case_id=case["id"], actor="agent3", event_type="billing_created", details=decision_json["billing"])

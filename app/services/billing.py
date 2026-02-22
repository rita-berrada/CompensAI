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

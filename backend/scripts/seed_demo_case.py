"""
One-shot script: inserts a pre-resolved HackAir lost-luggage demo case into Supabase.

Usage:
    cd backend && python scripts/seed_demo_case.py

Requires env vars (loaded from .env):
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    STRIPE_SECRET_KEY  (optional — if missing, stripe_checkout_url is left null)
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# Allow importing from backend/app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=False)

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# ── financial values ──────────────────────────────────────────────────────────
ESTIMATED_VALUE = Decimal("100.00")
FEE_RATE = Decimal("0.10")
FEE_AMOUNT = (ESTIMATED_VALUE * FEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# ── build Stripe checkout session (if key is present) ─────────────────────────
stripe_checkout_url: str | None = None
stripe_session_id: str | None = None

if STRIPE_SECRET_KEY:
    try:
        import stripe as _stripe  # noqa: PLC0415

        _stripe.api_key = STRIPE_SECRET_KEY
        fee_cents = int(FEE_AMOUNT * 100)
        session = _stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": "CompensAI Success Fee — HackAir Demo"},
                        "unit_amount": fee_cents,
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=os.getenv("STRIPE_SUCCESS_URL", "https://compensai.com/success"),
            cancel_url=os.getenv("STRIPE_CANCEL_URL", "https://compensai.com/cancel"),
        )
        stripe_checkout_url = session.url
        stripe_session_id = session.id
        print(f"Stripe session created: {stripe_session_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not create Stripe session ({exc}). Continuing without payment link.")
else:
    print("STRIPE_SECRET_KEY not set — skipping Stripe checkout session.")

# ── build case payload ─────────────────────────────────────────────────────────
case_id = str(uuid.uuid4())
now = datetime.now(timezone.utc).isoformat()

case = {
    "id": case_id,
    "status": "resolved",
    "vendor": "HackAir",
    "category": "damaged_parcel",
    "email_subject": "Lost Luggage Claim — HackAir Flight HA1234",
    "email_body": (
        "Dear HackAir Customer Service,\n\n"
        "I am writing to report that my checked luggage was lost on flight HA1234 "
        "from Paris (CDG) to London (LHR) on 15 January 2026. "
        "The bag contained clothing and personal items valued at approximately €100. "
        "I filed a Property Irregularity Report at the airport (ref: HA-PIR-20260115-4872).\n\n"
        "Please confirm receipt and advise on next steps.\n\n"
        "Kind regards,\nRita Berrada"
    ),
    "flight_number": "HA1234",
    "booking_reference": "HA-PIR-20260115-4872",
    "estimated_value": float(ESTIMATED_VALUE),
    "recovered_amount": float(ESTIMATED_VALUE),
    "fee_amount": float(FEE_AMOUNT),
    "stripe_checkout_url": stripe_checkout_url,
    "stripe_checkout_session_id": stripe_session_id,
    "draft_email_subject": "Lost Luggage Claim — HackAir Flight HA1234",
    "draft_email_body": (
        "Dear HackAir Customer Service,\n\n"
        "I am writing to formally claim compensation for lost luggage on flight HA1234 "
        "(CDG \u2192 LHR, 15 January 2026). Under EU Regulation 261/2004 and the Montreal Convention, "
        "I am entitled to compensation up to 1,288 SDR for lost checked baggage.\n\n"
        "My bag has not been recovered after 21 days. I hereby request reimbursement of \u20ac100 "
        "for the contents.\n\n"
        "Reference: HA-PIR-20260115-4872\n\n"
        "Sincerely,\nRita Berrada"
    ),
    "decision_json": {
        "eligibility": {
            "eligible": True,
            "reasons": [
                "Flight HA1234 confirmed as HackAir operated route.",
                "PIR reference HA-PIR-20260115-4872 filed within 7 days — meets Montreal Convention deadline.",
                "Claim value \u20ac100 is within the per-kg liability limit.",
                "21-day elapsed time satisfies 'lost baggage' threshold under Montreal Convention Art. 17.",
            ],
        },
        "billing": {
            "recovered_amount": float(ESTIMATED_VALUE),
            "currency": "eur",
            "success_fee_rate": float(FEE_RATE),
            "success_fee_amount": float(FEE_AMOUNT),
            "status": "resolved",
        },
    },
    "created_at": now,
    "updated_at": now,
}

# ── insert into Supabase via REST API ──────────────────────────────────────────
import httpx  # noqa: E402 (stdlib-first ordering)

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

url = f"{SUPABASE_URL}/rest/v1/cases"
resp = httpx.post(url, json=case, headers=headers, timeout=15)

if resp.status_code in (200, 201):
    print(f"\nDemo case created successfully!")
    print(f"  Case ID : {case_id}")
    print(f"  Vendor  : HackAir")
    print(f"  Status  : resolved")
    print(f"  Recovered: €{ESTIMATED_VALUE}")
    print(f"  Fee     : €{FEE_AMOUNT}")
    if stripe_checkout_url:
        print(f"  Payment : {stripe_checkout_url}")
    else:
        print("  Payment : (no Stripe link — set STRIPE_SECRET_KEY to generate one)")
else:
    print(f"\nFailed to insert case: {resp.status_code}")
    print(resp.text)
    sys.exit(1)

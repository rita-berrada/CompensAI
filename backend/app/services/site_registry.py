from __future__ import annotations

# Demo vendor registry (mock websites). Agent2 can also detect these URLs inside email text.

from typing import Literal

_BASE = "https://skill-deploy-x4cr0r1eo8-codex-agent-deploys.vercel.app"

AIRLINE_PORTAL_URL = f"{_BASE}/index.html"        # multi-vendor index — Playwright starts here
AIRLINE_POLICY_URL = f"{_BASE}/airline.html"
AIRLINE_CLAIM_FORM_URL = f"{_BASE}/airline-claim.html"

RETAIL_POLICY_URL = f"{_BASE}/retail-policy.html"
RETAIL_CONTACT_URL = f"{_BASE}/retail-contact.html"

DEMO_RETAIL_VENDOR = "DemoRetail"

SiteFamily = Literal["airline", "retail"]


def detect_site_family(*, urls: list[str], text: str) -> SiteFamily | None:
    haystack = (text or "").lower()
    url_text = " ".join(urls).lower()

    if any("airline" in u for u in urls) or "airline-claim" in url_text:
        return "airline"
    if any("retail" in u for u in urls) or "retail-policy" in url_text or "retail-contact" in url_text:
        return "retail"

    # Heuristics when URLs aren't present
    if any(k in haystack for k in ["order", "delivery", "tracking", "parcel", "refund", "demoretail"]):
        return "retail"
    if any(k in haystack for k in ["flight", "boarding", "gate", "baggage", "eu261"]):
        return "airline"

    return None


def registry_urls(family: SiteFamily) -> dict[str, str]:
    if family == "airline":
        return {
            "portal_url": AIRLINE_PORTAL_URL,
            "policy_url": AIRLINE_POLICY_URL,
            "claim_form_url": AIRLINE_CLAIM_FORM_URL,
        }
    return {"policy_url": RETAIL_POLICY_URL, "contact_url": RETAIL_CONTACT_URL}

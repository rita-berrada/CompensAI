from __future__ import annotations

# Demo vendor registry (mock websites). Agent2 can also detect these URLs inside email text.

from typing import Literal

AIRLINE_POLICY_URL = "https://skill-deploy-z31gmu05km-codex-agent-deploys.vercel.app/airline.html"
AIRLINE_CLAIM_FORM_URL = "https://skill-deploy-z31gmu05km-codex-agent-deploys.vercel.app/airline-claim.html"

RETAIL_POLICY_URL = "https://skill-deploy-z31gmu05km-codex-agent-deploys.vercel.app/retail-policy.html"
RETAIL_CONTACT_URL = "https://skill-deploy-z31gmu05km-codex-agent-deploys.vercel.app/retail-contact.html"

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
        return {"policy_url": AIRLINE_POLICY_URL, "claim_form_url": AIRLINE_CLAIM_FORM_URL}
    return {"policy_url": RETAIL_POLICY_URL, "contact_url": RETAIL_CONTACT_URL}

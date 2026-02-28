from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

# Ordered list of link/button text fragments that indicate a path toward the claim form.
# Earlier entries take priority.
_CLAIM_NAV_KEYWORDS = [
    "start compensation claim",
    "compensation claim",
    "submit claim",
    "start claim",
    "file claim",
    "claim form",
    "claim",
]


def _navigate_to_form(page: Any, *, vendor: str | None = None, max_hops: int = 3) -> None:
    """
    Walk from a portal/index page toward an HTML <form> by clicking links or buttons.

    Strategy per hop:
      1. If the current page already has a <form>, stop immediately.
      2. If a vendor name is known, click the first link whose text contains that name
         (e.g. "Open HackAir" when vendor="HackAir").
      3. Otherwise click the first link/button whose text matches a claim-related keyword.
    Gives up silently after max_hops if no form is found.
    """
    for _ in range(max_hops):
        if page.query_selector("form"):
            return  # already on the right page

        clicked = False

        # Step 1 – vendor portal link (e.g. "Open HackAir")
        if vendor and not clicked:
            el = page.query_selector(f'a:has-text("{vendor}")')
            if el:
                el.click()
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
                clicked = True

        # Step 2 – generic claim keywords
        if not clicked:
            for kw in _CLAIM_NAV_KEYWORDS:
                el = page.query_selector(
                    f'a:has-text("{kw}"), button:has-text("{kw}")'
                )
                if el:
                    el.click()
                    page.wait_for_load_state("domcontentloaded", timeout=15_000)
                    clicked = True
                    break

        if not clicked:
            break  # no navigable element found — give up


@dataclass
class FormFillResult:
    success: bool
    url: str
    fields_filled: list[str] = field(default_factory=list)
    fields_skipped: list[str] = field(default_factory=list)
    screenshot_path: str | None = None
    error: str | None = None


def _match_field_value(name: str, type_: str | None, data: dict[str, Any]) -> str | None:
    """Map a form field name to a value from fields_to_fill. Returns None if no match."""
    name_lower = name.lower().replace("-", "_").replace(" ", "_")

    # 1. Exact key match (case-insensitive)
    for key, value in data.items():
        if value is None:
            continue
        if key.lower() == name_lower:
            return str(value)

    # 2. Keyword-based matching
    route = data.get("route") if isinstance(data.get("route"), dict) else {}

    patterns: list[tuple[list[str], Any]] = [
        (["booking", "reference", "pnr", "reserv", "booking_ref"], data.get("booking_reference")),
        (["flight_no", "flight_num", "flightno", "flightnum", "flight"], data.get("flight_number")),
        (
            ["incident_date", "travel_date", "departure_date", "date_of_travel", "flight_date", "date"],
            data.get("incident_date"),
        ),
        (["delay_min", "delay_time", "delay_hour", "delay"], data.get("delay_minutes")),
        (["airline", "carrier", "vendor", "company_name", "operator"], data.get("vendor")),
        (["origin", "from_airport", "departure_city", "from_city"], route.get("from")),
        (["destination", "to_airport", "arrival_city", "to_city"], route.get("to")),
        (["order_num", "order_no", "order_id", "ordernum", "order"], data.get("order_number")),
        (["tracking_num", "tracking_no", "track_id", "tracking"], data.get("tracking_number")),
        (["amount", "claim_amount", "requested_amount", "compensation"], data.get("requested_amount_eur")),
        (["category", "claim_type", "issue_type", "type_of_claim"], data.get("category")),
        # Complaint / summary textarea
        (
            ["complaint", "summary", "description", "details", "message", "comments", "text"],
            data.get("complaint_summary"),
        ),
    ]

    for keywords, value in patterns:
        if any(kw in name_lower for kw in keywords):
            if value is not None:
                return str(value)

    return None


def fill_form(
    url: str,
    fields_to_fill: dict[str, Any],
    *,
    screenshot_dir: Path,
    vendor: str | None = None,
) -> FormFillResult:
    """
    Navigate to url with Playwright, navigate to the claim form if needed
    (e.g. starting from an index/portal page), fill every recognisable field,
    save a full-page screenshot, and return the result.

    The form is NOT submitted — fill-only for human review.

    Args:
        url: Starting URL.  Can be a portal index page (e.g. index.html) or
             the claim form directly.
        fields_to_fill: Extracted case data to fill into the form.
        screenshot_dir: Directory where the PNG screenshot is saved.
        vendor: Vendor name (e.g. "HackAir") used to click the correct portal
                link when starting from a multi-vendor index page.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return FormFillResult(
            success=False,
            url=url,
            error="playwright is not installed. Run: pip install playwright && playwright install chromium",
        )

    filled: list[str] = []
    skipped: list[str] = []
    screenshot_path: str | None = None

    try:
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(url, timeout=30_000)
            page.wait_for_load_state("domcontentloaded", timeout=30_000)

            # Navigate from portal/index to the actual form if needed
            if not page.query_selector("form"):
                _navigate_to_form(page, vendor=vendor, max_hops=3)

            elements = page.query_selector_all("input[name], textarea[name], select[name]")

            for el in elements:
                tag: str = el.evaluate("el => el.tagName.toLowerCase()")
                name: str = el.get_attribute("name") or ""
                type_: str | None = el.get_attribute("type") if tag == "input" else None

                # Skip non-fillable input types
                if type_ in ("hidden", "submit", "button", "reset", "file", "image", "checkbox", "radio"):
                    skipped.append(name)
                    continue

                value = _match_field_value(name, type_, fields_to_fill)
                if value is None:
                    skipped.append(name)
                    continue

                try:
                    if tag == "select":
                        try:
                            el.select_option(value=value)
                        except Exception:  # noqa: BLE001
                            el.select_option(label=value)
                    else:
                        el.fill(value)
                    filled.append(name)
                except Exception:  # noqa: BLE001
                    skipped.append(name)

            # Full-page screenshot saved to disk
            screenshot_file = screenshot_dir / f"fill_{uuid4().hex[:8]}.png"
            page.screenshot(path=str(screenshot_file), full_page=True)
            screenshot_path = str(screenshot_file)

            browser.close()

        return FormFillResult(
            success=True,
            url=url,
            fields_filled=filled,
            fields_skipped=skipped,
            screenshot_path=screenshot_path,
        )

    except Exception as exc:  # noqa: BLE001
        return FormFillResult(success=False, url=url, error=str(exc))

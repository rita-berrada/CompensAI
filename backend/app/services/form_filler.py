from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

# Ordered keyword list used to find navigation links toward the claim form.
# Longer/more specific phrases first; "start compensation" matches the known HackAir button.
_CLAIM_NAV_KEYWORDS = [
    "start compensation",
    "start compensation claim",
    "compensation claim",
    "submit claim",
    "start claim",
    "file claim",
    "claim form",
    "compensation form",
    "claim compensation",
    "make a claim",
    "open claim",
    "compensation request",
    "refund request",
    "claim refund",
    "report issue",
    "report a problem",
    "passenger rights",
    "compensation",
    "claim",
    "refund",
]

# Field name fragments specific to claim forms — deliberately excludes ambiguous names
# like "destination", "origin", "flight", "departure" that also appear in search/booking forms.
_CLAIM_FIELD_PATTERNS = [
    "booking_ref", "booking_num", "booking_code", "booking_id",
    "booking",
    "pnr",
    "reserv",
    "flight_no", "flight_num", "flightno", "flightnum",
    "delay",
    "incident",
    "complaint",
    "claim",
    "compensation",
    "tracking",
    "parcel",
    "order_no", "order_num", "order_id",
    "passenger",
]


def _is_claim_form(page: Any) -> bool:
    """
    Return True only if the current page looks like an actual claim/compensation form.
    Requires ≥3 fillable inputs AND at least one field whose name matches a claim-specific pattern.
    Deliberately excludes ambiguous names (destination, origin, flight) shared with search forms.
    """
    elements = page.query_selector_all(
        "input[name]:not([type=hidden]):not([type=submit]):not([type=button]),"
        "textarea[name], select[name]"
    )
    if len(elements) < 3:
        return False
    for el in elements:
        name = (el.get_attribute("name") or "").lower().replace("-", "_").replace(" ", "_")
        if any(pat in name for pat in _CLAIM_FIELD_PATTERNS):
            return True
    return False


def _navigate_to_form(page: Any, *, vendor: str | None = None, max_hops: int = 4) -> None:
    """
    Walk from a portal/index page toward an HTML <form> by clicking links or buttons.

    Strategy per hop:
      1. On the FIRST hop always navigate — never assume the landing page is the claim form.
      2. On subsequent hops, stop if _is_claim_form() returns True.
      3. Try clicking a link/button that mentions the vendor name.
      4. Try clicking a link/button matching claim-related keywords.
      5. JavaScript fallback: scan ALL clickable elements for any keyword.
    Gives up silently after max_hops if no navigable element is found.
    """
    for hop in range(max_hops):
        print(f"[form_filler] hop={hop} url={page.url}")

        # Wait briefly for any JS-rendered content to appear
        page.wait_for_timeout(800)

        # Dump all clickable text so we can see what's on the page
        all_text: list[str] = page.evaluate(
            """() => {
                const els = [...document.querySelectorAll('a, button, [onclick], [role="button"]')];
                return els.map(e => (e.textContent || e.value || '').trim()).filter(t => t.length > 0);
            }"""
        )
        print(f"[form_filler] clickable elements: {all_text[:30]}")

        # Always navigate at least once — skip the form check on the very first hop.
        if hop > 0 and _is_claim_form(page):
            print("[form_filler] claim form detected — stopping navigation")
            return

        clicked = False

        # Step 1 – vendor name link or button (e.g. "Open HackAir")
        # Only on hop 0 (the index/portal page). On subsequent pages the vendor
        # name appears in the site header/logo and clicking it loops back to the
        # same page, preventing us from ever reaching the claim form.
        if hop == 0 and vendor and not clicked:
            vendor_first = vendor.split()[0] if vendor else vendor
            for vtxt in ([vendor] if vendor_first == vendor else [vendor, vendor_first]):
                el = page.query_selector(f'a:has-text("{vtxt}"), button:has-text("{vtxt}")')
                if el:
                    print(f"[form_filler] clicking vendor element: {vtxt!r}")
                    el.click()
                    page.wait_for_load_state("load", timeout=15_000)
                    clicked = True
                    break

        # Step 2 – generic claim keywords (both <a> and <button>)
        if not clicked:
            for kw in _CLAIM_NAV_KEYWORDS:
                el = page.query_selector(f'a:has-text("{kw}"), button:has-text("{kw}")')
                if el:
                    print(f"[form_filler] clicking keyword element: {kw!r}")
                    el.click()
                    page.wait_for_load_state("load", timeout=15_000)
                    clicked = True
                    break

        # Step 3 – JavaScript fallback: case-insensitive search across ALL clickable elements
        #           including <a> without href, [onclick], [role="button"], etc.
        if not clicked:
            nav_result: str | None = page.evaluate(
                """(keywords) => {
                    const candidates = [
                        ...document.querySelectorAll('a'),
                        ...document.querySelectorAll('button'),
                        ...document.querySelectorAll('[onclick]'),
                        ...document.querySelectorAll('[role="button"]'),
                    ];
                    const txt = el => (el.textContent || el.value || el.title || el.getAttribute('aria-label') || '').toLowerCase().trim();
                    for (const kw of keywords) {
                        const el = candidates.find(e => txt(e).includes(kw));
                        if (el) {
                            const href = el.getAttribute('href');
                            if (href && !href.startsWith('#') && !href.startsWith('javascript')) {
                                return href.startsWith('http') ? href : window.location.origin + href;
                            }
                            el.click();
                            return '__clicked__';
                        }
                    }
                    return null;
                }""",
                _CLAIM_NAV_KEYWORDS,
            )
            if nav_result == "__clicked__":
                print("[form_filler] JS fallback clicked element")
                page.wait_for_load_state("load", timeout=15_000)
                clicked = True
            elif nav_result:
                print(f"[form_filler] JS fallback navigating to: {nav_result}")
                page.goto(nav_result, timeout=15_000)
                page.wait_for_load_state("load", timeout=15_000)
                clicked = True
            else:
                print("[form_filler] JS fallback found nothing to click")

        if not clicked:
            print("[form_filler] no clickable element found — giving up")
            break


@dataclass
class FormFillResult:
    success: bool
    url: str
    fields_filled: list[str] = field(default_factory=list)
    fields_skipped: list[str] = field(default_factory=list)
    screenshot_path: str | None = None
    video_path: str | None = None
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
    video_path: str | None = None

    try:
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, slow_mo=1200)
            context = browser.new_context(record_video_dir=str(screenshot_dir))
            page = context.new_page()

            page.goto(url, timeout=30_000)
            page.wait_for_load_state("load", timeout=30_000)

            # Always navigate from portal/index to the actual claim form
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

            # Hold on the filled form so it's readable in the video recording
            page.wait_for_timeout(4000)

            # Full-page screenshot saved to disk
            screenshot_file = screenshot_dir / f"fill_{uuid4().hex[:8]}.png"
            page.screenshot(path=str(screenshot_file), full_page=True)
            screenshot_path = str(screenshot_file)

            # Close page first so Playwright finalises the video file
            page.close()
            video_path = str(page.video.path()) if page.video else None
            context.close()
            browser.close()

        return FormFillResult(
            success=True,
            url=url,
            fields_filled=filled,
            fields_skipped=skipped,
            screenshot_path=screenshot_path,
            video_path=video_path,
        )

    except Exception as exc:  # noqa: BLE001
        return FormFillResult(success=False, url=url, error=str(exc))


def submit_form(
    url: str,
    fields_to_fill: dict[str, Any],
    *,
    screenshot_dir: Path,
    vendor: str | None = None,
) -> FormFillResult:
    """
    Same as fill_form but also clicks the Submit button after filling all fields.
    Takes a post-submission screenshot (captures the confirmation/thank-you page).
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
    video_path: str | None = None

    try:
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, slow_mo=0)
            context = browser.new_context()
            page = context.new_page()

            page.goto(url, timeout=30_000)
            page.wait_for_load_state("load", timeout=30_000)

            # Always navigate from portal/index to the actual claim form
            _navigate_to_form(page, vendor=vendor, max_hops=3)

            elements = page.query_selector_all("input[name], textarea[name], select[name]")

            for el in elements:
                tag: str = el.evaluate("el => el.tagName.toLowerCase()")
                name: str = el.get_attribute("name") or ""
                type_: str | None = el.get_attribute("type") if tag == "input" else None

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

            # Click the submit button
            submit_btn = page.query_selector(
                'button[type="submit"], input[type="submit"], button:has-text("Submit")'
            )
            if submit_btn:
                submit_btn.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:  # noqa: BLE001
                    pass  # still take screenshot even if timeout

            # Post-submission screenshot
            screenshot_file = screenshot_dir / f"submit_{uuid4().hex[:8]}.png"
            page.screenshot(path=str(screenshot_file), full_page=True)
            screenshot_path = str(screenshot_file)

            final_url = page.url

            page.close()
            context.close()
            browser.close()

        return FormFillResult(
            success=True,
            url=final_url,
            fields_filled=filled,
            fields_skipped=skipped,
            screenshot_path=screenshot_path,
            video_path=video_path,
        )

    except Exception as exc:  # noqa: BLE001
        return FormFillResult(success=False, url=url, error=str(exc))

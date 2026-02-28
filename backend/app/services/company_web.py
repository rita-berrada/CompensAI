from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class FetchResult:
    url: str
    ok: bool
    status: int | None
    error: str | None
    html: str
    text: str


def _strip_html_to_text(html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", html)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"(?is)<br\\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p\\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html_lib.unescape(cleaned)
    cleaned = re.sub(r"[ \\t\\r\\f\\v]+", " ", cleaned)
    cleaned = re.sub(r"\\n\\s*\\n+", "\n\n", cleaned)
    return cleaned.strip()


def fetch_html(url: str, *, timeout_seconds: float = 15.0) -> FetchResult:
    try:
        resp = httpx.get(url, timeout=timeout_seconds, follow_redirects=True)
        html = resp.text if isinstance(resp.text, str) else ""
        text = _strip_html_to_text(html)
        return FetchResult(url=url, ok=200 <= resp.status_code < 300, status=resp.status_code, error=None, html=html, text=text)
    except Exception as exc:  # noqa: BLE001
        return FetchResult(url=url, ok=False, status=None, error=str(exc), html="", text="")


def extract_contact_email(text: str) -> str | None:
    match = re.search(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,})", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def extract_form_schema(html: str) -> dict[str, Any]:
    schema: dict[str, Any] = {"action": None, "method": None, "fields": []}
    if not html:
        return schema

    form_match = re.search(r"(?is)<form\\b([^>]*)>", html)
    if form_match:
        attrs = form_match.group(1)
        action_match = re.search(r'\\baction\\s*=\\s*["\\\']([^"\\\']+)["\\\']', attrs, flags=re.IGNORECASE)
        method_match = re.search(r'\\bmethod\\s*=\\s*["\\\']([^"\\\']+)["\\\']', attrs, flags=re.IGNORECASE)
        schema["action"] = action_match.group(1) if action_match else None
        schema["method"] = (method_match.group(1).upper() if method_match else None)

    fields: list[dict[str, Any]] = []
    for tag, tag_name in [
        ("input", "input"),
        ("textarea", "textarea"),
        ("select", "select"),
    ]:
        for match in re.finditer(rf"(?is)<{tag}\\b([^>]*)>", html):
            attrs = match.group(1)
            name_match = re.search(r'\\bname\\s*=\\s*["\\\']([^"\\\']+)["\\\']', attrs, flags=re.IGNORECASE)
            if not name_match:
                continue
            field_name = name_match.group(1)
            type_match = re.search(r'\\btype\\s*=\\s*["\\\']([^"\\\']+)["\\\']', attrs, flags=re.IGNORECASE)
            required = bool(re.search(r"\\brequired\\b", attrs, flags=re.IGNORECASE))
            fields.append(
                {
                    "name": field_name,
                    "tag": tag_name,
                    "type": (type_match.group(1).lower() if type_match else None),
                    "required": required,
                }
            )

    # De-dupe by name, preserve order
    seen: set[str] = set()
    unique_fields: list[dict[str, Any]] = []
    for field in fields:
        name = str(field.get("name"))
        if name in seen:
            continue
        seen.add(name)
        unique_fields.append(field)

    schema["fields"] = unique_fields
    return schema

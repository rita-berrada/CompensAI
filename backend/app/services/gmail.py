from __future__ import annotations

import base64
import email as email_lib
import html as html_lib
import re
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_PROCESSED_LABEL = "compensai_processed"


def _strip_html(html: str) -> str:
    """Minimal HTML → plain text for email body fallback."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _decode_body(part: dict[str, Any]) -> str:
    """Base64url-decode a Gmail message part body."""
    data = (part.get("body") or {}).get("data", "")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")


def _extract_body(payload: dict[str, Any]) -> str:
    """
    Walk the MIME tree and return the best plain-text body.
    Prefers text/plain, falls back to text/html stripped to text.
    """
    mime_type: str = payload.get("mimeType", "")
    parts: list[dict[str, Any]] = payload.get("parts", [])

    if mime_type == "text/plain":
        return _decode_body(payload)

    if mime_type == "text/html":
        return _strip_html(_decode_body(payload))

    # multipart/* — recurse
    plain = ""
    html_fallback = ""
    for part in parts:
        sub_mime = part.get("mimeType", "")
        if sub_mime == "text/plain":
            plain = _decode_body(part)
        elif sub_mime == "text/html" and not plain:
            html_fallback = _strip_html(_decode_body(part))
        elif sub_mime.startswith("multipart/"):
            nested = _extract_body(part)
            if nested and not plain:
                plain = nested

    return plain or html_fallback


def _header_value(headers: list[dict[str, str]], name: str) -> str:
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _first_email_address(raw: str) -> str:
    """Extract the bare email address from a From/To header value."""
    if not raw:
        return ""
    m = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", raw, flags=re.IGNORECASE)
    return m.group(0) if m else raw.strip()


class GmailService:
    """Thin wrapper around the Gmail REST API using OAuth2 user credentials."""

    def __init__(self, *, credentials_file: str = "client_secret.json", token_file: str = "gmail_token.json") -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = Path(token_file)
        if not token_path.exists():
            raise RuntimeError(
                f"Gmail token not found at '{token_file}'. "
                "Run 'python scripts/gmail_auth.py' once to authorise."
            )

        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())

        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._label_id: str | None = None  # cached label ID for compensai_processed

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def list_unprocessed_messages(self, max_results: int = 50) -> list[dict[str, str]]:
        """Return up to max_results unprocessed inbox messages as {id, threadId}."""
        query = f"in:inbox -label:{_PROCESSED_LABEL}"
        result = (
            self._svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return result.get("messages", [])

    def get_message(self, message_id: str) -> dict[str, Any]:
        """
        Fetch a message and return a normalised dict ready for /cases/intake.
        Keys: message_id, thread_id, from_email, to_email, subject, body_text, snippet
        """
        raw = (
            self._svc.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers: list[dict[str, str]] = (raw.get("payload") or {}).get("headers", [])
        payload: dict[str, Any] = raw.get("payload") or {}

        from_raw = _header_value(headers, "from")
        to_raw = _header_value(headers, "to")
        subject = _header_value(headers, "subject")
        body_text = _extract_body(payload) or raw.get("snippet", "")

        return {
            "message_id": raw.get("id", message_id),
            "thread_id": raw.get("threadId"),
            "from_email": _first_email_address(from_raw) or "unknown@unknown.local",
            "to_email": _first_email_address(to_raw) or "unknown@unknown.local",
            "subject": subject,
            "body_text": body_text,
            "snippet": raw.get("snippet", ""),
        }

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_message(self, to: str, subject: str, body_text: str) -> dict[str, Any]:
        """Send a plain-text email and return the sent message metadata."""
        msg = MIMEText(body_text)
        msg["to"] = to
        msg["subject"] = subject
        encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        result = (
            self._svc.users()
            .messages()
            .send(userId="me", body={"raw": encoded})
            .execute()
        )
        return result

    # ------------------------------------------------------------------
    # Labelling
    # ------------------------------------------------------------------

    def _get_or_create_label_id(self) -> str:
        """Return the Gmail label ID for compensai_processed, creating it if needed."""
        if self._label_id:
            return self._label_id

        labels = self._svc.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label.get("name", "").lower() == _PROCESSED_LABEL:
                self._label_id = label["id"]
                return self._label_id

        # Create it
        new_label = (
            self._svc.users()
            .labels()
            .create(userId="me", body={"name": _PROCESSED_LABEL, "labelListVisibility": "labelHide", "messageListVisibility": "hide"})
            .execute()
        )
        self._label_id = new_label["id"]
        return self._label_id

    def mark_processed(self, message_id: str) -> None:
        """Add the compensai_processed label so this message is skipped next scan."""
        label_id = self._get_or_create_label_id()
        self._svc.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: GmailService | None = None


def get_gmail_service(
    *,
    credentials_file: str = "client_secret.json",
    token_file: str = "gmail_token.json",
) -> GmailService:
    """Return the shared GmailService instance, initialising it on first call."""
    global _instance
    if _instance is None:
        _instance = GmailService(credentials_file=credentials_file, token_file=token_file)
    return _instance

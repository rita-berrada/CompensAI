from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

import httpx

from app.db.supabase import SupabaseError, get_supabase


DEFAULT_THANK_YOU_TEXT = """Hello Dear User,

Thank you for accepting the CompensAI Terms & Conditions.

This email confirms that you have successfully agreed to use CompensAI as your AI-powered claims assistant.

Here is a summary of what this means:

- CompensAI may analyze authorized email metadata and relevant correspondence to identify potential disputes and draft claim letters on your behalf.
- No claim will ever be submitted without your explicit review and approval.
- CompensAI provides automated assistance only and does not offer legal representation or legal advice.
- You remain responsible for reviewing all generated drafts and confirming that submitted information is accurate.
- We process your data solely for dispute detection and claim generation purposes, in compliance with applicable data protection laws, including GDPR.
- We do not sell your data and only share necessary information with entities directly involved in resolving your dispute.
- A service fee of up to 10% may apply only if compensation is successfully recovered. No fee applies to unsuccessful claims.

You may stop using the service at any time and request deletion of your data whenever you choose.

If you have any questions about your account, privacy, or how CompensAI works, please contact us at liminalityapps@gmail.com.

We're excited to help you recover what you're entitled to.

Best regards,
The CompensAI Team
"""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    return int(raw)


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _looks_email(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return "@" in text and "." in text.split("@")[-1]


@dataclass(frozen=True)
class TermsCondAgentConfig:
    table_name: str
    terms_field: str
    id_field: str
    fixed_to_email: str | None
    recipient_fields: tuple[str, ...]

    send_subject: str
    send_body: str
    send_webhook_url: str | None
    send_timeout_seconds: float

    smtp_host: str | None
    smtp_port: int
    smtp_use_tls: bool
    smtp_username: str | None
    smtp_password: str | None
    smtp_from_email: str | None

    mark_sent: bool
    sent_flag_fields: tuple[str, ...]
    sent_at_fields: tuple[str, ...]

    max_rows_per_run: int
    poll_interval_seconds: float


@dataclass(frozen=True)
class TermsCondRunResult:
    scanned: int
    eligible: int
    sent: int
    skipped: int
    failed: int
    errors: tuple[str, ...]


def load_terms_cond_agent_config() -> TermsCondAgentConfig:
    recipient_fields = tuple(
        part.strip()
        for part in os.getenv("TERMS_COND_RECIPIENT_FIELDS", "user_email,email,to_email").split(",")
        if part.strip()
    )
    sent_flag_fields = tuple(
        part.strip()
        for part in os.getenv(
            "TERMS_COND_SENT_FLAG_FIELDS",
            "terms_cond_email_sent,confirmation_email_sent,email_sent,notification_sent",
        ).split(",")
        if part.strip()
    )
    sent_at_fields = tuple(
        part.strip()
        for part in os.getenv(
            "TERMS_COND_SENT_AT_FIELDS",
            "terms_cond_email_sent_at,confirmation_email_sent_at,email_sent_at,notification_sent_at",
        ).split(",")
        if part.strip()
    )

    return TermsCondAgentConfig(
        table_name=os.getenv("TERMS_COND_TABLE", "terms_cond"),
        terms_field=os.getenv("TERMS_COND_FIELD", "terms_cond"),
        id_field=os.getenv("TERMS_COND_ID_FIELD", "id"),
        fixed_to_email=os.getenv("TERMS_COND_TO_EMAIL", "client.compensai@gmail.com"),
        recipient_fields=recipient_fields,
        send_subject=os.getenv("TERMS_COND_EMAIL_SUBJECT", "Terms and Conditions"),
        send_body=os.getenv("TERMS_COND_EMAIL_BODY", DEFAULT_THANK_YOU_TEXT),
        send_webhook_url=os.getenv("TERMS_COND_SEND_WEBHOOK_URL") or os.getenv("AGENT1_SEND_WEBHOOK_URL") or None,
        send_timeout_seconds=_env_float("TERMS_COND_SEND_TIMEOUT_SECONDS", 20.0),
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=_env_int("SMTP_PORT", 587),
        smtp_use_tls=_env_bool("SMTP_USE_TLS", True),
        smtp_username=os.getenv("SMTP_USERNAME") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        smtp_from_email=os.getenv("SMTP_FROM_EMAIL") or None,
        mark_sent=_env_bool("TERMS_COND_MARK_SENT", True),
        sent_flag_fields=sent_flag_fields,
        sent_at_fields=sent_at_fields,
        max_rows_per_run=_env_int("TERMS_COND_MAX_ROWS_PER_RUN", 200),
        poll_interval_seconds=_env_float("TERMS_COND_POLL_INTERVAL_SECONDS", 30.0),
    )


def _find_recipient(row: dict[str, Any], candidate_fields: tuple[str, ...]) -> str | None:
    for field in candidate_fields:
        value = row.get(field)
        if _looks_email(value):
            return str(value).strip()
    return None


def _already_sent(row: dict[str, Any], flag_fields: tuple[str, ...], at_fields: tuple[str, ...]) -> bool:
    for field in flag_fields:
        if field in row and _is_truthy(row.get(field)):
            return True
    for field in at_fields:
        if field in row and row.get(field) not in (None, "", False):
            return True
    return False


def _build_mark_sent_payload(row: dict[str, Any], flag_fields: tuple[str, ...], at_fields: tuple[str, ...]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in flag_fields:
        if field in row:
            payload[field] = True
    now_iso = datetime.now(timezone.utc).isoformat()
    for field in at_fields:
        if field in row:
            payload[field] = now_iso
    return payload


def _send_via_webhook(*, config: TermsCondAgentConfig, to_email: str, row: dict[str, Any]) -> None:
    if not config.send_webhook_url:
        raise RuntimeError("No webhook configured")
    payload = {
        "send_via": "email",
        "to_email": to_email,
        "subject": config.send_subject,
        "body": config.send_body,
        "source": "terms_cond_agent",
        "table": config.table_name,
        "row_id": row.get(config.id_field),
    }
    response = httpx.post(config.send_webhook_url, json=payload, timeout=config.send_timeout_seconds)
    response.raise_for_status()


def _send_via_smtp(*, config: TermsCondAgentConfig, to_email: str) -> None:
    if not config.smtp_host:
        raise RuntimeError("SMTP_HOST is not configured")
    if not config.smtp_from_email:
        raise RuntimeError("SMTP_FROM_EMAIL is not configured")

    msg = EmailMessage()
    msg["From"] = config.smtp_from_email
    msg["To"] = to_email
    msg["Subject"] = config.send_subject
    msg.set_content(config.send_body)

    if config.smtp_use_tls:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.send_timeout_seconds) as server:
            server.starttls()
            if config.smtp_username and config.smtp_password:
                server.login(config.smtp_username, config.smtp_password)
            server.send_message(msg)
        return

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.send_timeout_seconds) as server:
        if config.smtp_username and config.smtp_password:
            server.login(config.smtp_username, config.smtp_password)
        server.send_message(msg)


def _send_email(*, config: TermsCondAgentConfig, to_email: str, row: dict[str, Any]) -> None:
    if config.send_webhook_url:
        _send_via_webhook(config=config, to_email=to_email, row=row)
        return
    _send_via_smtp(config=config, to_email=to_email)


def run_terms_cond_agent(config: TermsCondAgentConfig, *, dry_run: bool = False) -> TermsCondRunResult:
    db = get_supabase()
    rows = db.select(
        config.table_name,
        filters={config.terms_field: "eq.true"},
        columns="*",
        limit=config.max_rows_per_run,
    )

    scanned = len(rows)
    eligible = 0
    sent = 0
    skipped = 0
    failed = 0
    errors: list[str] = []

    for row in rows:
        if not _is_truthy(row.get(config.terms_field)):
            skipped += 1
            continue
        if _already_sent(row, config.sent_flag_fields, config.sent_at_fields):
            skipped += 1
            continue

        recipient = config.fixed_to_email or _find_recipient(row, config.recipient_fields)
        if not recipient:
            failed += 1
            errors.append(f"Missing recipient email for row {row.get(config.id_field)!r}")
            continue

        eligible += 1
        if dry_run:
            sent += 1
            continue

        try:
            _send_email(config=config, to_email=recipient, row=row)
            sent += 1

            if config.mark_sent:
                updates = _build_mark_sent_payload(row, config.sent_flag_fields, config.sent_at_fields)
                row_id = row.get(config.id_field)
                if updates and row_id not in (None, ""):
                    db.update(config.table_name, filters={config.id_field: f"eq.{row_id}"}, payload=updates)
        except SupabaseError as exc:
            failed += 1
            errors.append(f"Supabase error for row {row.get(config.id_field)!r}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"Send failed for row {row.get(config.id_field)!r}: {exc}")

    return TermsCondRunResult(
        scanned=scanned,
        eligible=eligible,
        sent=sent,
        skipped=skipped,
        failed=failed,
        errors=tuple(errors),
    )

"""Resend HTTPS email delivery for event passes.

Uses the official Resend Python SDK over HTTPS (no SMTP).
Docs: https://resend.com/docs/send-with-python
Attachments: https://resend.com/docs/dashboard/emails/attachments
"""

from __future__ import annotations

import base64
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Optional

import resend

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Prevent indefinite hangs on the Resend HTTPS call
RESEND_TIMEOUT_SECONDS = 30


class EmailError(Exception):
    """Raised when email delivery fails."""


def build_pass_email_body(
    *,
    attendee_name: str,
    ticket_id: str,
    settings: Settings,
) -> str:
    return (
        f"Hello {attendee_name},\n\n"
        f"Thank you for registering for {settings.event_name}.\n\n"
        "Your event pass is attached to this email.\n\n"
        f"Event:\n{settings.event_name}\n\n"
        f"Date:\n{settings.event_date}\n\n"
        f"Time:\n{settings.event_time}\n\n"
        f"Venue:\n{settings.event_venue}\n\n"
        f"Ticket ID:\n{ticket_id}\n\n"
        "Please keep this pass available on your phone and present the QR code at the event.\n\n"
        "We look forward to welcoming you.\n\n"
        f"Regards,\n{settings.ngo_name}\n"
    )


def _mask_email(address: str) -> str:
    if not address or "@" not in address:
        return "***"
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def send_pass_email(
    *,
    to_email: str,
    attendee_name: str,
    ticket_id: str,
    pass_png: bytes,
    settings: Settings | None = None,
    pass_url: str | None = None,
) -> None:
    """Send the event pass PNG via Resend HTTPS API (same interface as before).

    ``pass_url`` is optional and unused in the body today (kept for compatibility).
    The personalized PNG in ``pass_png`` is attached — not regenerated.
    """
    settings = settings or get_settings()
    _ = pass_url  # reserved; attachment uses existing pass_png bytes only

    if not settings.email_enabled:
        logger.info(
            "[EMAIL] Email disabled (EMAIL_ENABLED=false) — skipping send ticket=%s",
            ticket_id,
        )
        raise EmailError("Email delivery is disabled (EMAIL_ENABLED=false)")

    if not settings.resend_api_key.strip() or not settings.email_from.strip():
        raise EmailError(
            "Email is not configured. Set RESEND_API_KEY and EMAIL_FROM."
        )

    if not pass_png:
        raise EmailError("Pass PNG bytes are missing — cannot attach event pass")

    subject = f"Your {settings.event_name} Event Pass"
    body = build_pass_email_body(
        attendee_name=attendee_name,
        ticket_id=ticket_id,
        settings=settings,
    )

    filename = f"{ticket_id}-event-pass.png"
    attachment_b64 = base64.b64encode(pass_png).decode("ascii")

    params: resend.Emails.SendParams = {
        "from": settings.email_from,
        "to": [to_email],
        "subject": subject,
        "text": body,
        "attachments": [
            {
                "filename": filename,
                "content": attachment_b64,
            }
        ],
    }

    logger.info(
        "[EMAIL] Resend send started ticket=%s to=%s from=%s attachment=%s bytes=%s timeout=%ss",
        ticket_id,
        _mask_email(to_email),
        _mask_email(settings.email_from),
        filename,
        len(pass_png),
        RESEND_TIMEOUT_SECONDS,
    )

    try:
        resend.api_key = settings.resend_api_key

        def _send() -> object:
            return resend.Emails.send(params)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_send)
            email = future.result(timeout=RESEND_TIMEOUT_SECONDS)

    except FuturesTimeout as exc:
        logger.error(
            "[EMAIL] Resend send timed out after %ss ticket=%s",
            RESEND_TIMEOUT_SECONDS,
            ticket_id,
        )
        raise EmailError(
            f"Resend send timed out after {RESEND_TIMEOUT_SECONDS}s"
        ) from exc
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        # Never log API key
        logger.error(
            "[EMAIL] Resend send failed ticket=%s type=%s msg=%s",
            ticket_id,
            type(exc).__name__,
            exc,
        )
        raise EmailError(
            f"Resend send failed ({type(exc).__name__}: {exc})"
        ) from exc

    email_id = None
    if isinstance(email, dict):
        email_id = email.get("id")
    else:
        email_id = getattr(email, "id", None)

    logger.info(
        "[EMAIL] Email sent successfully ticket=%s resend_id=%s",
        ticket_id,
        email_id or "(unknown)",
    )


def resolve_email_status(email: Optional[str]) -> str:
    if not email:
        return "NOT_PROVIDED"
    return "PENDING"

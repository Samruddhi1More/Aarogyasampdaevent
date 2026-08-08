"""Gmail SMTP email delivery for event passes."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)


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


def send_pass_email(
    *,
    to_email: str,
    attendee_name: str,
    ticket_id: str,
    pass_png: bytes,
    settings: Settings | None = None,
) -> None:
    """Send the event pass PNG as an email attachment via Gmail SMTP (STARTTLS)."""
    settings = settings or get_settings()

    if not settings.email_configured:
        raise EmailError("Email is not configured. Set EMAIL_* environment variables.")

    subject = f"Your {settings.event_name} Event Pass"
    body = build_pass_email_body(
        attendee_name=attendee_name,
        ticket_id=ticket_id,
        settings=settings,
    )

    message = MIMEMultipart()
    message["From"] = settings.email_from
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    attachment = MIMEImage(pass_png, _subtype="png")
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"{ticket_id}-event-pass.png",
    )
    message.attach(attachment)

    try:
        context = ssl.create_default_context()
        logger.info(
            "[diag] step=11 smtp_connection_started host=%s port=%s",
            settings.email_host,
            settings.email_port,
        )
        with smtplib.SMTP(settings.email_host, settings.email_port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            logger.info("[diag] step=12 starttls_succeeded")
            server.ehlo()
            try:
                server.login(settings.email_username, settings.email_password)
                logger.info("[diag] step=13 smtp_authentication_succeeded")
            except Exception as auth_exc:  # noqa: BLE001
                logger.error(
                    "[diag] step=13 smtp_authentication_failed type=%s msg=%s",
                    type(auth_exc).__name__,
                    auth_exc,
                )
                raise
            server.sendmail(settings.email_from, [to_email], message.as_string())
            logger.info("[diag] step=14 email_sendmail_accepted ticket=%s", ticket_id)
    except Exception as exc:  # noqa: BLE001
        # Never log credentials
        logger.error(
            "[diag] step=14 email_failed ticket=%s type=%s msg=%s",
            ticket_id,
            type(exc).__name__,
            exc,
        )
        raise EmailError("Failed to send event pass email") from exc


def resolve_email_status(email: Optional[str]) -> str:
    if not email:
        return "NOT_PROVIDED"
    return "PENDING"

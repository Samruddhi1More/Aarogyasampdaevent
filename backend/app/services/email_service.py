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

# Explicit socket timeout so production cannot hang indefinitely on SMTP
SMTP_TIMEOUT_SECONDS = 20


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

    host = settings.email_host
    port = int(settings.email_port)
    context = ssl.create_default_context()
    server: smtplib.SMTP | None = None

    try:
        logger.info(
            "[EMAIL] SMTP connection started host=%s port=%s timeout=%ss ticket=%s to=%s",
            host,
            port,
            SMTP_TIMEOUT_SECONDS,
            ticket_id,
            _mask_email(to_email),
        )
        try:
            server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[EMAIL] SMTP connection failed type=%s msg=%s",
                type(exc).__name__,
                exc,
            )
            raise EmailError(
                f"SMTP connection failed ({type(exc).__name__}: {exc})"
            ) from exc

        logger.info("[EMAIL] SMTP connection established")

        try:
            server.ehlo()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[EMAIL] SMTP EHLO failed type=%s msg=%s",
                type(exc).__name__,
                exc,
            )
            raise EmailError(f"SMTP EHLO failed ({type(exc).__name__}: {exc})") from exc

        logger.info("[EMAIL] STARTTLS started")
        try:
            server.starttls(context=context)
            server.ehlo()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[EMAIL] STARTTLS failed type=%s msg=%s",
                type(exc).__name__,
                exc,
            )
            raise EmailError(f"STARTTLS failed ({type(exc).__name__}: {exc})") from exc

        logger.info("[EMAIL] STARTTLS completed")

        logger.info("[EMAIL] SMTP login started user=%s", _mask_email(settings.email_username))
        try:
            server.login(settings.email_username, settings.email_password)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[EMAIL] SMTP login failed type=%s msg=%s",
                type(exc).__name__,
                exc,
            )
            raise EmailError(f"SMTP login failed ({type(exc).__name__}: {exc})") from exc

        logger.info("[EMAIL] SMTP login completed")

        logger.info("[EMAIL] Email send started ticket=%s", ticket_id)
        try:
            server.sendmail(settings.email_from, [to_email], message.as_string())
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[EMAIL] Email send failed type=%s msg=%s",
                type(exc).__name__,
                exc,
            )
            raise EmailError(f"Email send failed ({type(exc).__name__}: {exc})") from exc

        logger.info("[EMAIL] Email sent successfully ticket=%s", ticket_id)

    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        # Never log credentials
        logger.error(
            "[EMAIL] Unexpected email failure ticket=%s type=%s msg=%s",
            ticket_id,
            type(exc).__name__,
            exc,
        )
        raise EmailError("Failed to send event pass email") from exc
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                try:
                    server.close()
                except Exception:  # noqa: BLE001
                    pass


def resolve_email_status(email: Optional[str]) -> str:
    if not email:
        return "NOT_PROVIDED"
    return "PENDING"

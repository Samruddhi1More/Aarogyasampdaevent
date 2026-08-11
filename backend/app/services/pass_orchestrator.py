"""Orchestrates ticket → QR → pass → Cloudinary → sheet update → email → WhatsApp.

Idempotent: reuses existing Ticket ID + Pass URL when present.
Email / WhatsApp failures never fail the overall registration.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.app.config import Settings, get_settings
from backend.app.services.cloudinary_service import CloudinaryError, upload_pass_png
from backend.app.services.email_service import EmailError, send_pass_email
from backend.app.services.google_sheets import (
    GoogleSheetsError,
    find_row_by_registration_id,
    remember_ticket_id,
    ticket_id_exists,
    update_registration_fields,
)
from backend.app.services.pass_service import PassGenerationError, generate_pass_png
from backend.app.services.ticket_service import generate_ticket_id
from backend.app.services.whatsapp_service import (
    WHATSAPP_STATUS_FAILED,
    WHATSAPP_STATUS_NOT_ATTEMPTED,
    WHATSAPP_STATUS_NOT_PROVIDED,
    WHATSAPP_STATUS_SENDING,
    WHATSAPP_STATUS_SENT,
    get_whatsapp_notifier,
)

logger = logging.getLogger(__name__)


def _mask_email(email: Optional[str]) -> str:
    if not email:
        return "(none)"
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


@dataclass
class PassResult:
    ticket_id: Optional[str] = None
    qr_url: Optional[str] = None
    pass_url: Optional[str] = None
    pass_generation_status: str = "PENDING"
    email_status: str = "NOT_PROVIDED"
    whatsapp_status: str = WHATSAPP_STATUS_NOT_ATTEMPTED
    reused_existing: bool = False


def _unique_ticket_id(settings: Settings, attempts: int = 8) -> str:
    for _ in range(attempts):
        candidate = generate_ticket_id()
        if not ticket_id_exists(candidate, settings=settings):
            remember_ticket_id(candidate)
            return candidate
    candidate = generate_ticket_id(length=10)
    remember_ticket_id(candidate)
    return candidate


def _send_whatsapp_after_pass(
    *,
    registration_id: str,
    phone: str,
    name: str,
    ticket_id: str,
    pass_url: str,
    existing_whatsapp_status: str,
    settings: Settings,
    pass_png: bytes | None = None,
) -> str:
    """Send WhatsApp using the SAME personalized pass as email.

    Uses Cloudinary Pass URL for the template header and the exact PNG bytes
    (same as the email attachment) via WATI sendSessionFile. Never regenerates.
    """
    prior = (existing_whatsapp_status or "").strip().upper()
    if prior == WHATSAPP_STATUS_SENT:
        logger.info(
            "[BACKGROUND] WhatsApp skipped — already SENT for %s",
            registration_id,
        )
        return WHATSAPP_STATUS_SENT

    if not phone or not str(phone).strip():
        _safe_sheet_update(
            registration_id,
            {"WhatsApp": WHATSAPP_STATUS_NOT_PROVIDED},
            settings,
        )
        return WHATSAPP_STATUS_NOT_PROVIDED

    if not pass_url:
        _safe_sheet_update(
            registration_id,
            {"WhatsApp": WHATSAPP_STATUS_FAILED},
            settings,
        )
        return WHATSAPP_STATUS_FAILED

    logger.info(
        "[BACKGROUND] WhatsApp using same pass as email ticket=%s bytes=%s url_prefix=%s",
        ticket_id,
        len(pass_png) if pass_png else 0,
        pass_url[:80],
    )
    if ticket_id and ticket_id not in (pass_url or ""):
        logger.error(
            "[BACKGROUND] Refusing WhatsApp — pass_url does not contain ticket=%s",
            ticket_id,
        )
        _safe_sheet_update(
            registration_id,
            {"WhatsApp": WHATSAPP_STATUS_FAILED},
            settings,
        )
        return WHATSAPP_STATUS_FAILED

    _safe_sheet_update(
        registration_id,
        {"WhatsApp": WHATSAPP_STATUS_SENDING},
        settings,
    )

    try:
        outcome = get_whatsapp_notifier(settings).send_pass_notification(
            phone=phone,
            attendee_name=name,
            ticket_id=ticket_id,
            pass_url=pass_url,
            pass_png=pass_png,
        )
        status = outcome.status or WHATSAPP_STATUS_FAILED
        # Dry-run with disabled WATI → NOT_ATTEMPTED (do not claim SENT)
        if outcome.dry_run and status == WHATSAPP_STATUS_NOT_ATTEMPTED:
            _safe_sheet_update(
                registration_id,
                {"WhatsApp": WHATSAPP_STATUS_NOT_ATTEMPTED},
                settings,
            )
            logger.info(
                "[BACKGROUND] WhatsApp dry-run complete for %s: %s",
                registration_id,
                outcome.message,
            )
            return WHATSAPP_STATUS_NOT_ATTEMPTED

        _safe_sheet_update(registration_id, {"WhatsApp": status}, settings)
        logger.info(
            "[BACKGROUND] WhatsApp finished for %s status=%s msg=%s",
            registration_id,
            status,
            outcome.message,
        )
        return status
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[BACKGROUND] WhatsApp failed type=%s msg=%s",
            type(exc).__name__,
            exc,
        )
        _safe_sheet_update(
            registration_id,
            {"WhatsApp": WHATSAPP_STATUS_FAILED},
            settings,
        )
        return WHATSAPP_STATUS_FAILED


def process_pass_for_registration(
    *,
    registration_id: str,
    name: str,
    phone: str,
    email: Optional[str],
    settings: Settings | None = None,
    existing_row: Optional[dict] = None,
    skip_lookup: bool = False,
    preassigned_ticket_id: Optional[str] = None,
) -> PassResult:
    """Generate/upload pass and update the existing sheet row.

    Never creates a duplicate registration row.
    """
    settings = settings or get_settings()
    result = PassResult(email_status="NOT_PROVIDED" if not email else "PENDING")

    logger.info(
        "[BACKGROUND] Started processing registration: %s email=%s cloudinary_configured=%s email_configured=%s wati_enabled=%s",
        registration_id,
        _mask_email(email),
        settings.cloudinary_configured,
        settings.email_configured,
        settings.wati_enabled,
    )

    existing = existing_row
    if existing is None and not skip_lookup:
        try:
            existing = find_row_by_registration_id(registration_id, settings=settings)
        except GoogleSheetsError as exc:
            logger.error(
                "[BACKGROUND] Lookup failed type=%s msg=%s",
                type(exc).__name__,
                exc,
            )
            existing = None

    if existing and existing.get("ticket_id") and existing.get("pass_url"):
        result.ticket_id = existing["ticket_id"]
        result.pass_url = existing["pass_url"]
        result.qr_url = existing.get("qr_url") or None
        result.pass_generation_status = existing.get("pass_generation_status") or "SUCCESS"
        result.reused_existing = True
        result.email_status = existing.get("email_status") or result.email_status
        prior_wa = existing.get("whatsapp_status") or ""
        logger.info(
            "[BACKGROUND] Reusing existing ticket=%s pass_url_set=%s",
            result.ticket_id,
            bool(result.pass_url),
        )

        if email and result.email_status != "SENT":
            result.email_status = _send_email_safe(
                email=email,
                name=name,
                ticket_id=result.ticket_id,
                settings=settings,
                registration_id=registration_id,
            )
        elif not email:
            result.email_status = "NOT_PROVIDED"
            _safe_sheet_update(
                registration_id,
                {"Email Status": "NOT_PROVIDED"},
                settings,
            )

        result.whatsapp_status = _send_whatsapp_after_pass(
            registration_id=registration_id,
            phone=phone,
            name=name,
            ticket_id=result.ticket_id or "",
            pass_url=result.pass_url or "",
            existing_whatsapp_status=prior_wa,
            settings=settings,
        )
        return result

    ticket_id = (
        preassigned_ticket_id
        or (existing or {}).get("ticket_id")
        or _unique_ticket_id(settings)
    )
    if preassigned_ticket_id:
        remember_ticket_id(preassigned_ticket_id)
    result.ticket_id = ticket_id
    logger.info("[BACKGROUND] Ticket generated: %s", ticket_id)

    pass_png: bytes | None = None
    try:
        pass_png, qr_url = generate_pass_png(
            attendee_name=name,
            ticket_id=ticket_id,
            settings=settings,
        )
        result.qr_url = qr_url
        logger.info("[BACKGROUND] QR generated: %s", qr_url)
        logger.info("[BACKGROUND] Pass generated bytes=%s", len(pass_png))

        tmp_path = Path(tempfile.gettempdir()) / f"{ticket_id}-event-pass.png"
        tmp_path.write_bytes(pass_png)

        logger.info("[BACKGROUND] Cloudinary upload started ticket=%s", ticket_id)
        upload = upload_pass_png(pass_png, ticket_id=ticket_id, settings=settings)
        pass_url = upload["secure_url"]
        result.pass_url = pass_url
        result.pass_generation_status = "SUCCESS"
        logger.info(
            "[BACKGROUND] Cloudinary upload successful public_id=%s version=%s url_prefix=%s",
            upload.get("public_id"),
            upload.get("version"),
            pass_url[:80],
        )
        logger.info(
            "[BACKGROUND] Cloudinary pass URL generated for ticket=%s public_id=%s",
            ticket_id,
            upload.get("public_id"),
        )
        logger.info(
            "[BACKGROUND] Pass event data event=%s date=%s time=%s venue=%s",
            settings.event_name,
            settings.event_date,
            settings.event_time,
            (settings.event_venue or "")[:60],
        )

        sheet_fields = {
            "Ticket ID": ticket_id,
            "QR URL": qr_url,
            "Pass URL": pass_url,
            "Pass Generation Status": "SUCCESS",
            "WhatsApp": WHATSAPP_STATUS_NOT_ATTEMPTED,
        }
        if not email:
            sheet_fields["Email Status"] = "NOT_PROVIDED"
            result.email_status = "NOT_PROVIDED"
        update_registration_fields(registration_id, sheet_fields, settings=settings)
        logger.info("[BACKGROUND] Google Sheet updated fields=%s", list(sheet_fields.keys()))

    except (PassGenerationError, CloudinaryError) as exc:
        cause = exc.__cause__
        logger.error(
            "[BACKGROUND] Pass generation failed: type=%s msg=%s cause_type=%s cause_msg=%s",
            type(exc).__name__,
            exc,
            type(cause).__name__ if cause else None,
            cause if cause else None,
        )
        result.pass_generation_status = "FAILED"
        fail_fields = {
            "Ticket ID": ticket_id,
            "Pass Generation Status": "FAILED",
            "Email Status": "NOT_PROVIDED" if not email else "FAILED",
            "WhatsApp": WHATSAPP_STATUS_FAILED,
        }
        if result.qr_url:
            fail_fields["QR URL"] = result.qr_url
        result.email_status = fail_fields["Email Status"]
        result.whatsapp_status = WHATSAPP_STATUS_FAILED
        _safe_sheet_update(registration_id, fail_fields, settings)
        return result
    except GoogleSheetsError as exc:
        logger.error(
            "[BACKGROUND] Google Sheet update failed after upload type=%s msg=%s",
            type(exc).__name__,
            exc,
        )
        result.pass_generation_status = "SUCCESS"
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "[BACKGROUND] Pass generation failed: type=%s msg=%s",
            type(exc).__name__,
            exc,
        )
        result.pass_generation_status = "FAILED"
        _safe_sheet_update(
            registration_id,
            {
                "Ticket ID": ticket_id,
                "Pass Generation Status": "FAILED",
                "WhatsApp": WHATSAPP_STATUS_FAILED,
            },
            settings,
        )
        result.whatsapp_status = WHATSAPP_STATUS_FAILED
        return result

    # WhatsApp only after a valid Cloudinary Pass URL exists (independent of email)
    if result.pass_generation_status == "SUCCESS" and result.pass_url:
        prior_wa = (existing or {}).get("whatsapp_status") or WHATSAPP_STATUS_NOT_ATTEMPTED
        result.whatsapp_status = _send_whatsapp_after_pass(
            registration_id=registration_id,
            phone=phone,
            name=name,
            ticket_id=ticket_id,
            pass_url=result.pass_url,
            existing_whatsapp_status=prior_wa,
            settings=settings,
            pass_png=pass_png,
        )
    else:
        result.whatsapp_status = WHATSAPP_STATUS_FAILED

    if email and result.pass_generation_status == "SUCCESS" and result.pass_url and pass_png:
        logger.info("[BACKGROUND] Email sending started to=%s", _mask_email(email))
        result.email_status = _send_email_with_bytes(
            email=email,
            name=name,
            ticket_id=ticket_id,
            pass_png=pass_png,
            settings=settings,
            registration_id=registration_id,
        )
    elif not email:
        result.email_status = "NOT_PROVIDED"
        logger.info("[BACKGROUND] Email skipped (NOT_PROVIDED)")
    else:
        logger.info(
            "[BACKGROUND] Email skipped pass_status=%s pass_url_set=%s",
            result.pass_generation_status,
            bool(result.pass_url),
        )

    return result


def process_registration_after_submission(
    *,
    registration_id: str,
    name: str,
    phone: str,
    email: Optional[str],
    ticket_id: str,
) -> None:
    """FastAPI BackgroundTasks entrypoint — receives only per-request data."""
    try:
        process_pass_for_registration(
            registration_id=registration_id,
            name=name,
            phone=phone,
            email=email,
            skip_lookup=True,
            preassigned_ticket_id=ticket_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "[BACKGROUND] Unhandled failure for %s type=%s msg=%s",
            registration_id,
            type(exc).__name__,
            exc,
        )


def _send_email_with_bytes(
    *,
    email: str,
    name: str,
    ticket_id: str,
    pass_png: bytes,
    settings: Settings,
    registration_id: str,
) -> str:
    try:
        send_pass_email(
            to_email=email,
            attendee_name=name,
            ticket_id=ticket_id,
            pass_png=pass_png,
            settings=settings,
        )
        _safe_sheet_update(registration_id, {"Email Status": "SENT"}, settings)
        logger.info("[BACKGROUND] Email sent successfully to=%s", _mask_email(email))
        return "SENT"
    except EmailError as exc:
        cause = exc.__cause__
        logger.error(
            "[BACKGROUND] Email failed: type=%s msg=%s cause_type=%s cause_msg=%s",
            type(exc).__name__,
            exc,
            type(cause).__name__ if cause else None,
            cause if cause else None,
        )
        _safe_sheet_update(registration_id, {"Email Status": "FAILED"}, settings)
        return "FAILED"


def _send_email_safe(
    *,
    email: str,
    name: str,
    ticket_id: str,
    settings: Settings,
    registration_id: str,
) -> str:
    try:
        pass_png, _ = generate_pass_png(
            attendee_name=name,
            ticket_id=ticket_id,
            settings=settings,
        )
        return _send_email_with_bytes(
            email=email,
            name=name,
            ticket_id=ticket_id,
            pass_png=pass_png,
            settings=settings,
            registration_id=registration_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[BACKGROUND] Email retry failed type=%s msg=%s",
            type(exc).__name__,
            exc,
        )
        _safe_sheet_update(registration_id, {"Email Status": "FAILED"}, settings)
        return "FAILED"


def _safe_sheet_update(
    registration_id: str,
    fields: dict[str, str],
    settings: Settings,
) -> None:
    try:
        update_registration_fields(registration_id, fields, settings=settings)
        logger.info(
            "[BACKGROUND] Google Sheet updated id=%s fields=%s",
            registration_id,
            list(fields.keys()),
        )
    except GoogleSheetsError as exc:
        logger.error(
            "[BACKGROUND] Google Sheet update FAILED type=%s msg=%s fields=%s",
            type(exc).__name__,
            exc,
            list(fields),
        )

"""WATI WhatsApp template messaging for event passes.

Official API used:
  POST {WATI_API_ENDPOINT}/api/v1/sendTemplateMessages
  Docs: https://docs.wati.io/reference/post_api-v1-sendtemplatemessages

Dynamic image headers use named customParams (media URL must be public).
Ref: https://support.wati.io/en/articles/11463469-how-to-send-images-or-pdfs-using-wati-template-messages

No webhooks yet — structured for future delivery-status callbacks.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Official path from WATI OpenAPI
WATI_SEND_TEMPLATE_PATH = "/api/v1/sendTemplateMessages"


class WatiError(Exception):
    """Raised when WATI send fails or input is invalid."""


@dataclass
class WatiSendResult:
    success: bool
    status: str  # SENT | FAILED | NOT_PROVIDED | NOT_ATTEMPTED
    message: str = ""
    normalized_phone: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    response_body: Optional[dict[str, Any]] = None
    dry_run: bool = False


def mask_phone(phone: Optional[str]) -> str:
    if not phone:
        return "(none)"
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return "****"
    return f"****{digits[-4:]}"


def normalize_indian_whatsapp_number(raw: str) -> str:
    """Normalize to digits with country code 91 (no +).

    Accepts 10-digit Indian mobiles or already-prefixed 91XXXXXXXXXX.
    """
    if raw is None:
        raise WatiError("Phone number is required")

    digits = re.sub(r"[\s\-()+]", "", str(raw).strip())
    digits = re.sub(r"\D", "", digits)

    if not digits:
        raise WatiError("Phone number is empty")

    if len(digits) == 10 and digits[0] in "6789":
        return f"91{digits}"

    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return digits

    if len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        return f"91{digits[1:]}"

    raise WatiError("Invalid Indian mobile number for WhatsApp")


def build_template_payload(
    *,
    whatsapp_number: str,
    attendee_name: str,
    ticket_id: str,
    pass_url: str,
    settings: Settings,
) -> dict[str, Any]:
    """Build the official v1 sendTemplateMessages body.

    customParams names must match the approved template variables.
    Defaults (override via env):
      header image → WATI_PARAM_HEADER_IMAGE (default: header_image)
      attendee     → WATI_PARAM_ATTENDEE_NAME (default: name)
      ticket       → WATI_PARAM_TICKET_ID (default: ticket_id)
    """
    if not pass_url or not str(pass_url).startswith("https://"):
        raise WatiError("Pass URL must be a public https Cloudinary URL")

    custom_params = [
        {
            "name": settings.wati_param_header_image,
            "value": pass_url,
        },
        {
            "name": settings.wati_param_attendee_name,
            "value": attendee_name,
        },
        {
            "name": settings.wati_param_ticket_id,
            "value": ticket_id,
        },
    ]

    return {
        "template_name": settings.wati_template_name,
        "broadcast_name": settings.wati_broadcast_name,
        "channel_number": settings.wati_whatsapp_number,
        "receivers": [
            {
                "whatsappNumber": whatsapp_number,
                "customParams": custom_params,
            }
        ],
    }


def _wati_send_url(settings: Settings) -> str:
    base = settings.wati_api_endpoint.strip().rstrip("/")
    if not base:
        raise WatiError("WATI_API_ENDPOINT is not set")
    return f"{base}{WATI_SEND_TEMPLATE_PATH}"


def send_event_pass(
    phone_number: str,
    attendee_name: str,
    ticket_id: str,
    pass_url: str,
    *,
    settings: Settings | None = None,
) -> WatiSendResult:
    """Send (or dry-run) the sahjeevan_event_pass template with image header."""
    settings = settings or get_settings()

    try:
        normalized = normalize_indian_whatsapp_number(phone_number)
    except WatiError as exc:
        return WatiSendResult(
            success=False,
            status="NOT_PROVIDED",
            message=str(exc),
        )

    # Controlled testing: redirect to test phone when configured
    recipient = normalized
    if settings.wati_test_phone.strip():
        try:
            recipient = normalize_indian_whatsapp_number(settings.wati_test_phone)
            logger.info(
                "[WATI] Using WATI_TEST_PHONE ending %s (attendee ending %s)",
                mask_phone(recipient),
                mask_phone(normalized),
            )
        except WatiError as exc:
            return WatiSendResult(
                success=False,
                status="FAILED",
                message=f"Invalid WATI_TEST_PHONE: {exc}",
                normalized_phone=normalized,
            )

    try:
        payload = build_template_payload(
            whatsapp_number=recipient,
            attendee_name=attendee_name,
            ticket_id=ticket_id,
            pass_url=pass_url,
            settings=settings,
        )
    except WatiError as exc:
        return WatiSendResult(
            success=False,
            status="FAILED",
            message=str(exc),
            normalized_phone=recipient,
        )

    if not settings.wati_enabled:
        logger.info(
            "[WATI] Dry-run (WATI_ENABLED=false) template=%s to=%s header_param=%s",
            settings.wati_template_name,
            mask_phone(recipient),
            settings.wati_param_header_image,
        )
        return WatiSendResult(
            success=True,
            status="NOT_ATTEMPTED",
            message="WATI disabled — payload validated, API not called",
            normalized_phone=recipient,
            payload=payload,
            dry_run=True,
        )

    if not settings.wati_configured:
        return WatiSendResult(
            success=False,
            status="FAILED",
            message="WATI is enabled but API endpoint/token/channel are incomplete",
            normalized_phone=recipient,
            payload=payload,
        )

    url = _wati_send_url(settings)
    headers = {
        "Authorization": f"Bearer {settings.wati_api_token}",
        "Content-Type": "application/json",
    }

    try:
        # Never log token or full phone
        logger.info(
            "[WATI] Calling sendTemplateMessages template=%s to=%s",
            settings.wati_template_name,
            mask_phone(recipient),
        )
        response = requests.post(url, json=payload, headers=headers, timeout=45)
    except requests.RequestException as exc:
        logger.error("[WATI] Request failed type=%s msg=%s", type(exc).__name__, exc)
        return WatiSendResult(
            success=False,
            status="FAILED",
            message=f"WATI request error: {type(exc).__name__}",
            normalized_phone=recipient,
            payload=payload,
        )

    body: dict[str, Any] = {}
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {"raw": "non-json response"}

    # Official success shape: { "result": true, "errors": { ... } }
    api_ok = response.status_code < 400 and bool(body.get("result") is True)
    errors = body.get("errors") or {}
    error_msg = ""
    if isinstance(errors, dict):
        error_msg = (errors.get("error") or "").strip()
        invalid = errors.get("invalidWhatsappNumbers") or []
        if invalid:
            error_msg = (error_msg + f" invalid_numbers={len(invalid)}").strip()

    if not api_ok:
        logger.error(
            "[WATI] Send rejected http=%s result=%s err=%s",
            response.status_code,
            body.get("result"),
            error_msg or "unknown",
        )
        return WatiSendResult(
            success=False,
            status="FAILED",
            message=error_msg or f"WATI HTTP {response.status_code}",
            normalized_phone=recipient,
            payload=payload,
            response_body=body,
        )

    logger.info("[WATI] Template accepted by API for %s", mask_phone(recipient))
    return WatiSendResult(
        success=True,
        status="SENT",
        message="WATI accepted template message",
        normalized_phone=recipient,
        payload=payload,
        response_body=body,
    )


# Reserved for future webhook / delivery callbacks (not implemented yet)
@dataclass
class WatiDeliveryEvent:
    """Placeholder model for future WATI delivery-status webhooks."""

    message_id: Optional[str] = None
    whatsapp_number: Optional[str] = None
    status: Optional[str] = None  # delivered | read | failed | ...
    raw: dict[str, Any] = field(default_factory=dict)

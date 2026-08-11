"""WATI WhatsApp template messaging for event passes.

Official APIs used:
  1) GET  {WATI_API_ENDPOINT}/api/v1/getMessageTemplates  (static-header guard)
  2) POST {WATI_API_ENDPOINT}/api/v1/updateContactAttributes/{whatsappNumber}
     — optional, non-fatal
  3) POST {WATI_API_ENDPOINT}/api/v1/sendTemplateMessages
     — sole WhatsApp delivery: approved template + dynamic {{image}}

The pass PNG is generated once in pass_orchestrator, uploaded to Cloudinary,
and that Pass URL is passed into this service as the IMAGE header. This module
never generates a pass, never uses a static/sample image URL, and never sends
a second session-file copy of the PNG.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)

WATI_SEND_TEMPLATE_PATH = "/api/v1/sendTemplateMessages"
WATI_UPDATE_CONTACT_ATTRIBUTES_PATH = "/api/v1/updateContactAttributes"
WATI_GET_MESSAGE_TEMPLATES_PATH = "/api/v1/getMessageTemplates"

# Approved template uses {{image}} for the dynamic IMAGE header.
_DEFAULT_HEADER_PARAMS = ("image",)

_TICKET_IN_URL_RE = re.compile(r"SAP-[A-Z0-9]+", re.IGNORECASE)


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
    """Normalize to digits with country code 91 (no +)."""
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


def _assert_event_ready(settings: Settings) -> None:
    for label, value in (
        ("EVENT_DATE", settings.event_date),
        ("EVENT_TIME", settings.event_time),
        ("EVENT_VENUE", settings.event_venue),
        ("EVENT_NAME", settings.event_name),
    ):
        if "PLACEHOLDER" in (value or "").upper():
            raise WatiError(
                f"Refusing WhatsApp send — {label} still contains PLACEHOLDER"
            )


def _safe_url_for_log(url: str) -> str:
    """Truncate URL for logs — no credentials, enough to verify ticket public_id."""
    clean = (url or "").strip()
    if not clean:
        return "(empty)"
    match = _TICKET_IN_URL_RE.search(clean)
    ticket_bit = match.group(0) if match else "?"
    host = "cloudinary" if "cloudinary.com" in clean else "other"
    return f"{host}…/{ticket_bit}…{clean[-24:]}"


def assert_pass_url_matches_ticket(pass_url: str, ticket_id: str) -> str:
    """Ensure the Cloudinary URL belongs to THIS registration's ticket."""
    if not pass_url or not str(pass_url).startswith("https://"):
        raise WatiError("Pass URL must be a public https Cloudinary URL")

    pass_url_clean = str(pass_url).strip()
    if "cloudinary.com" not in pass_url_clean:
        raise WatiError("Pass URL must be the Cloudinary Pass URL for this registration")

    ticket = str(ticket_id or "").strip()
    if not ticket:
        raise WatiError("Ticket ID is required for WhatsApp template")

    if ticket not in pass_url_clean:
        found = _TICKET_IN_URL_RE.findall(pass_url_clean)
        raise WatiError(
            f"Pass URL ticket mismatch — refusing WATI send. "
            f"expected_ticket={ticket} url_tickets={found or ['(none)']}"
        )

    if "PLACEHOLDER" in pass_url_clean.upper():
        raise WatiError("Pass URL must not contain PLACEHOLDER")

    return pass_url_clean


def _header_param_names(settings: Settings) -> list[str]:
    configured = [
        n.strip()
        for n in (settings.wati_param_header_image or "").split(",")
        if n.strip()
    ]
    if configured:
        names: list[str] = []
        for name in configured:
            if name not in names:
                names.append(name)
        return names
    return list(_DEFAULT_HEADER_PARAMS)


def _media_custom_params(pass_url: str, settings: Settings) -> list[dict[str, str]]:
    return [
        {"name": name, "value": pass_url}
        for name in _header_param_names(settings)
    ]


def build_template_payload(
    *,
    whatsapp_number: str,
    attendee_name: str,
    ticket_id: str,
    pass_url: str,
    settings: Settings,
) -> dict[str, Any]:
    """Build sendTemplateMessages body using the orchestrator's Cloudinary Pass URL."""
    _assert_event_ready(settings)
    pass_url_clean = assert_pass_url_matches_ticket(pass_url, ticket_id)

    if not attendee_name or not str(attendee_name).strip():
        raise WatiError("Attendee name is required for WhatsApp template")

    custom_params: list[dict[str, str]] = _media_custom_params(pass_url_clean, settings)
    custom_params.extend(
        [
            {
                "name": settings.wati_param_attendee_name.strip() or "1",
                "value": str(attendee_name).strip(),
            },
            {
                "name": settings.wati_param_ticket_id.strip() or "2",
                "value": str(ticket_id).strip(),
            },
        ]
    )

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


def _auth_headers(settings: Settings, *, json_body: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {settings.wati_api_token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _base_url(settings: Settings) -> str:
    base = settings.wati_api_endpoint.strip().rstrip("/")
    if not base:
        raise WatiError("WATI_API_ENDPOINT is not set")
    return base


def _safe_error_summary(body: dict[str, Any], status_code: int) -> str:
    errors = body.get("errors") or {}
    parts: list[str] = [f"http={status_code}", f"result={body.get('result')}"]
    if isinstance(errors, dict):
        if errors.get("error"):
            parts.append(f"err={errors.get('error')}")
        if errors.get("invalidWhatsappNumbers"):
            parts.append(
                f"invalid_numbers={len(errors.get('invalidWhatsappNumbers') or [])}"
            )
        if errors.get("invalidCustomParameters"):
            parts.append(f"invalid_params={errors.get('invalidCustomParameters')}")
    info = body.get("info") or body.get("message")
    if isinstance(info, str) and info.strip():
        parts.append(f"info={info.strip()[:160]}")
    return " ".join(parts)


def _extract_ticket_from_url(url: str) -> Optional[str]:
    match = _TICKET_IN_URL_RE.search(url or "")
    return match.group(0).upper() if match else None


def _fetch_template_definition(
    settings: Settings,
) -> Optional[dict[str, Any]]:
    """Load the configured template from WATI (best-effort)."""
    url = f"{_base_url(settings)}{WATI_GET_MESSAGE_TEMPLATES_PATH}"
    try:
        response = requests.get(url, headers=_auth_headers(settings), timeout=30)
        response.raise_for_status()
        body = response.json() if response.content else {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "[WATI] getMessageTemplates failed type=%s msg=%s",
            type(exc).__name__,
            exc,
        )
        return None

    templates = body.get("messageTemplates") if isinstance(body, dict) else None
    if not isinstance(templates, list):
        return None

    wanted = (settings.wati_template_name or "").strip().lower()
    for template in templates:
        name = (template.get("elementName") or template.get("name") or "").strip()
        if name.lower() == wanted:
            return template
    return None


def assert_template_allows_dynamic_image(
    settings: Settings,
    *,
    ticket_id: str,
) -> None:
    """Refuse send when the approved template IMAGE header is a fixed sample URL."""
    template = _fetch_template_definition(settings)
    if not template:
        logger.warning(
            "[WATI DEBUG] Could not inspect template=%s — proceeding without "
            "static-header guard",
            settings.wati_template_name,
        )
        return

    header = template.get("header") or {}
    header_type = (header.get("headerTypeString") or header.get("typeString") or "").lower()
    link = (header.get("link") or "").strip()
    mapping = header.get("headerParamMapping")
    locked_ticket = _extract_ticket_from_url(link)

    template_params = template.get("customParams") or []
    param_names = {
        str(p.get("paramName") or p.get("name") or "").strip().lower()
        for p in template_params
        if isinstance(p, dict)
    }
    has_image_param = "image" in param_names or any(
        n in param_names for n in _header_param_names(settings)
    )

    logger.info(
        "[WATI DEBUG] template=%s header_type=%s headerParamMapping=%s "
        "has_image_param=%s static_link_ticket=%s current_ticket=%s",
        template.get("elementName"),
        header_type,
        mapping,
        has_image_param,
        locked_ticket or "(none)",
        ticket_id,
    )

    if header_type != "image":
        return

    link_is_variable = "{{" in link and "}}" in link
    if mapping is not None or link_is_variable or has_image_param:
        logger.info(
            "[WATI DEBUG] Dynamic IMAGE header confirmed — will send cloudinary_pass_url"
        )
        return

    if not link:
        logger.warning(
            "[WATI DEBUG] IMAGE header has empty link and null mapping — "
            "confirm dashboard uses Add a different header / {{image}}"
        )
        return

    raise WatiError(
        "Approved WATI template IMAGE header is STATIC (not a {{image}} "
        f"variable). Locked sample={_safe_url_for_log(link)} "
        f"locked_ticket={locked_ticket or '?'}. "
        "Use template aarogyasampaevent with dynamic {{image}} header."
    )


def _update_contact_pass_attributes(
    *,
    recipient: str,
    pass_url: str,
    ticket_id: str,
    settings: Settings,
) -> None:
    """Best-effort: write current Cloudinary Pass URL onto the WATI contact.

    Non-fatal — missing contacts or API errors must not block template send.
    """
    url = (
        f"{_base_url(settings)}{WATI_UPDATE_CONTACT_ATTRIBUTES_PATH}/{recipient}"
    )
    payload = {"customParams": _media_custom_params(pass_url, settings)}
    try:
        response = requests.post(
            url,
            json=payload,
            headers=_auth_headers(settings),
            timeout=30,
        )
        body: dict[str, Any] = {}
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        logger.info(
            "[WATI DEBUG] updateContactAttributes ticket=%s to=%s %s",
            ticket_id,
            mask_phone(recipient),
            _safe_error_summary(
                body if isinstance(body, dict) else {}, response.status_code
            ),
        )
    except requests.RequestException as exc:
        logger.warning(
            "[WATI] updateContactAttributes failed (non-fatal) type=%s msg=%s",
            type(exc).__name__,
            exc,
        )


def send_event_pass(
    phone_number: str,
    attendee_name: str,
    ticket_id: str,
    pass_url: str,
    *,
    pass_png: bytes | None = None,
    settings: Settings | None = None,
) -> WatiSendResult:
    """Send approved template with the registration's Cloudinary Pass URL as {{image}}.

    ``pass_png`` is accepted for call-site compatibility but unused — the template
    IMAGE header is the sole WhatsApp delivery path (no session-file follow-up).
    """
    _ = pass_png  # unused; template {{image}} uses pass_url only
    settings = settings or get_settings()

    try:
        normalized = normalize_indian_whatsapp_number(phone_number)
    except WatiError as exc:
        return WatiSendResult(
            success=False,
            status="NOT_PROVIDED",
            message=str(exc),
        )

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
        pass_url_clean = assert_pass_url_matches_ticket(pass_url, ticket_id)
        payload = build_template_payload(
            whatsapp_number=recipient,
            attendee_name=attendee_name,
            ticket_id=ticket_id,
            pass_url=pass_url_clean,
            settings=settings,
        )
    except WatiError as exc:
        logger.error("[WATI] WhatsApp send failed — payload error: %s", exc)
        return WatiSendResult(
            success=False,
            status="FAILED",
            message=str(exc),
            normalized_phone=recipient,
        )

    pass_url_ticket = _extract_ticket_from_url(pass_url_clean) or "(none)"
    logger.info(
        "[WATI] Sending template=%s ticket=%s",
        settings.wati_template_name,
        ticket_id,
    )
    logger.info("[WATI] Image header prepared for ticket=%s", ticket_id)
    logger.info(
        "[WATI DEBUG] pass_url_ticket=%s header_param=image pass_url=%s to=%s",
        pass_url_ticket,
        _safe_url_for_log(pass_url_clean),
        mask_phone(recipient),
    )

    if not settings.wati_enabled:
        logger.info(
            "[WATI] Dry-run (WATI_ENABLED=false) template=%s to=%s — API not called",
            settings.wati_template_name,
            mask_phone(recipient),
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
        logger.error(
            "[WATI] WhatsApp send failed — WATI_ENABLED=true but configuration incomplete"
        )
        return WatiSendResult(
            success=False,
            status="FAILED",
            message="WATI is enabled but API endpoint/token/channel/template are incomplete",
            normalized_phone=recipient,
            payload=payload,
        )

    try:
        assert_template_allows_dynamic_image(settings, ticket_id=ticket_id)
    except WatiError as exc:
        logger.error("[WATI] WhatsApp send blocked — %s", exc)
        return WatiSendResult(
            success=False,
            status="FAILED",
            message=str(exc),
            normalized_phone=recipient,
            payload=payload,
        )

    # Optional: sync contact media attribute (non-fatal if contact missing).
    _update_contact_pass_attributes(
        recipient=recipient,
        pass_url=pass_url_clean,
        ticket_id=ticket_id,
        settings=settings,
    )

    template_url = f"{_base_url(settings)}{WATI_SEND_TEMPLATE_PATH}"

    try:
        logger.info(
            "[WATI] Sending template=%s ticket=%s endpoint=sendTemplateMessages",
            settings.wati_template_name,
            ticket_id,
        )
        response = requests.post(
            template_url,
            json=payload,
            headers=_auth_headers(settings),
            timeout=45,
        )
    except requests.RequestException as exc:
        logger.error(
            "[WATI] WhatsApp send failed type=%s msg=%s",
            type(exc).__name__,
            exc,
        )
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

    logger.info(
        "[WATI] sendTemplateMessages response %s",
        _safe_error_summary(body if isinstance(body, dict) else {}, response.status_code),
    )

    api_ok = response.status_code < 400 and bool(
        isinstance(body, dict) and body.get("result") is True
    )
    if not api_ok:
        summary = _safe_error_summary(
            body if isinstance(body, dict) else {}, response.status_code
        )
        logger.error("[WATI] WhatsApp send failed %s", summary)
        return WatiSendResult(
            success=False,
            status="FAILED",
            message=summary,
            normalized_phone=recipient,
            payload=payload,
            response_body=body if isinstance(body, dict) else None,
        )

    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, dict) and (errors.get("invalidWhatsappNumbers") or []):
        logger.error(
            "[WATI] WhatsApp send failed — invalid WhatsApp number for to=%s",
            mask_phone(recipient),
        )
        return WatiSendResult(
            success=False,
            status="FAILED",
            message="WATI reported invalid WhatsApp number",
            normalized_phone=recipient,
            payload=payload,
            response_body=body,
        )

    logger.info(
        "[WATI] WhatsApp send successful ticket=%s template=%s",
        ticket_id,
        settings.wati_template_name,
    )
    return WatiSendResult(
        success=True,
        status="SENT",
        message="WATI template sent with Cloudinary Pass URL",
        normalized_phone=recipient,
        payload=payload,
        response_body=body,
    )


@dataclass
class WatiDeliveryEvent:
    """Placeholder model for future WATI delivery-status webhooks."""

    message_id: Optional[str] = None
    whatsapp_number: Optional[str] = None
    status: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

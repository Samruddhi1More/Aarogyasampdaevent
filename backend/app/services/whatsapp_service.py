"""WhatsApp notification adapter — delegates to WATI when enabled.

Keeps a stable interface for the pass orchestrator. Webhooks not implemented yet.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from backend.app.config import Settings, get_settings
from backend.app.services.wati_service import WatiSendResult, send_event_pass

logger = logging.getLogger(__name__)

# Google Sheet / orchestrator status values
WHATSAPP_STATUS_NOT_ATTEMPTED = "NOT_ATTEMPTED"
WHATSAPP_STATUS_NOT_PROVIDED = "NOT_PROVIDED"
WHATSAPP_STATUS_SENDING = "SENDING"
WHATSAPP_STATUS_SENT = "SENT"
WHATSAPP_STATUS_FAILED = "FAILED"

# Back-compat aliases used by older rows
WHATSAPP_STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
WHATSAPP_STATUS_SKIPPED = "SKIPPED"


@dataclass
class WhatsAppSendOutcome:
    status: str
    message: str = ""
    dry_run: bool = False


class WhatsAppNotifier(ABC):
    """Interface for WhatsApp delivery adapters (WATI)."""

    @abstractmethod
    def send_pass_notification(
        self,
        *,
        phone: str,
        attendee_name: str,
        ticket_id: str,
        pass_url: str,
        pass_png: bytes | None = None,
    ) -> WhatsAppSendOutcome:
        raise NotImplementedError


class WatiWhatsAppNotifier(WhatsAppNotifier):
    """WATI-backed notifier. Respects WATI_ENABLED / WATI_TEST_PHONE."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def send_pass_notification(
        self,
        *,
        phone: str,
        attendee_name: str,
        ticket_id: str,
        pass_url: str,
        pass_png: bytes | None = None,
    ) -> WhatsAppSendOutcome:
        if not phone or not str(phone).strip():
            return WhatsAppSendOutcome(
                status=WHATSAPP_STATUS_NOT_PROVIDED,
                message="No phone number provided",
            )

        if not pass_url:
            return WhatsAppSendOutcome(
                status=WHATSAPP_STATUS_FAILED,
                message="Missing Cloudinary pass URL",
            )

        result: WatiSendResult = send_event_pass(
            phone_number=phone,
            attendee_name=attendee_name,
            ticket_id=ticket_id,
            pass_url=pass_url,
            pass_png=pass_png,
            settings=self.settings,
        )
        return WhatsAppSendOutcome(
            status=result.status,
            message=result.message,
            dry_run=result.dry_run,
        )


def get_whatsapp_notifier(settings: Settings | None = None) -> WhatsAppNotifier:
    """Factory — always returns the WATI adapter (dry-run when disabled)."""
    return WatiWhatsAppNotifier(settings=settings or get_settings())

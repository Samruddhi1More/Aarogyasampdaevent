"""Placeholder interface for future WhatsApp (WATI) notifications.

Do NOT add WATI credentials or implement sending here yet.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class WhatsAppNotifier(ABC):
    """Interface for WhatsApp delivery adapters (e.g. WATI)."""

    @abstractmethod
    def send_pass_notification(
        self,
        *,
        phone: str,
        attendee_name: str,
        ticket_id: str,
        pass_url: str,
    ) -> None:
        raise NotImplementedError


class NoOpWhatsAppNotifier(WhatsAppNotifier):
    """Default stub used until WATI is wired in."""

    def send_pass_notification(
        self,
        *,
        phone: str,
        attendee_name: str,
        ticket_id: str,
        pass_url: str,
    ) -> None:
        logger.info(
            "WhatsApp notifier stub: skipping send for ticket %s (phone ending %s)",
            ticket_id,
            phone[-4:] if phone else "----",
        )


def get_whatsapp_notifier() -> WhatsAppNotifier:
    """Factory for the WhatsApp adapter. Swap implementation later without changing callers."""
    return NoOpWhatsAppNotifier()


# Reserved for future status values in Google Sheets
WHATSAPP_STATUS_SKIPPED = "SKIPPED"
WHATSAPP_STATUS_SENT = "SENT"
WHATSAPP_STATUS_FAILED = "FAILED"
WHATSAPP_STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

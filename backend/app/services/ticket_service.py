"""Unique Ticket ID generation — format SAP-XXXXXXXX."""

from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_uppercase + string.digits


def generate_ticket_id(*, length: int = 8) -> str:
    """Return a unique-looking ticket id, e.g. SAP-A7K92PLQ.

    Collision checks against the sheet (if needed) should be done by the caller.
    """
    if length < 6:
        raise ValueError("Ticket ID suffix length must be at least 6")
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"SAP-{suffix}"

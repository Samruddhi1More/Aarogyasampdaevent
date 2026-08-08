"""QR code generation for event passes.

Isolated so verification behavior can change later without touching pass rendering.
"""

from __future__ import annotations

import io
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from backend.app.config import Settings, get_settings


def build_pass_qr_url(ticket_id: str, settings: Settings | None = None) -> str:
    """Public verification URL embedded in the QR code (no PII)."""
    settings = settings or get_settings()
    base = settings.pass_base_url.rstrip("/")
    return f"{base}/{ticket_id}"


def generate_qr_png_bytes(
    ticket_id: str,
    *,
    settings: Settings | None = None,
    box_size: int = 12,
    border: int = 2,
) -> tuple[bytes, str]:
    """Generate a QR PNG for the pass URL.

    Returns (png_bytes, qr_url).
    """
    qr_url = build_pass_qr_url(ticket_id, settings)
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1A1412", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue(), qr_url


def generate_qr_image_path(
    ticket_id: str,
    destination: Path,
    *,
    settings: Settings | None = None,
) -> tuple[Path, str]:
    png_bytes, qr_url = generate_qr_png_bytes(ticket_id, settings=settings)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(png_bytes)
    return destination, qr_url

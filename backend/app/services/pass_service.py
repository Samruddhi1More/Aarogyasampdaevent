"""Premium event-pass PNG generator (portrait, mobile-optimized).

Visual design uses centralized brand tokens from ``backend.app.theme``.
Logos are loaded as provided — never redrawn or distorted (aspect ratio preserved).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from backend.app import theme
from backend.app.config import Settings, get_settings
from backend.app.services.qr_service import generate_qr_png_bytes

logger = logging.getLogger(__name__)


class PassGenerationError(Exception):
    """Raised when pass image rendering fails."""


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_logo(path: Path, max_w: int, max_h: int) -> Image.Image:
    """Load logo and fit within box while preserving aspect ratio (no crop/distort)."""
    if not path.is_file():
        img = Image.new("RGBA", (max_w, max_h), (*theme.ACCENT_SOFT_RGB, 255))
        return img

    logo = Image.open(path).convert("RGBA")
    logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    return logo


def _paste(base: Image.Image, overlay: Image.Image, x: int, y: int) -> None:
    base.alpha_composite(overlay, (x, y))


def _paste_center(base: Image.Image, overlay: Image.Image, cx: int, cy: int) -> None:
    _paste(base, overlay, cx - overlay.width // 2, cy - overlay.height // 2)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        w, _ = _text_size(draw, trial, font)
        if w <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def generate_pass_png(
    *,
    attendee_name: str,
    ticket_id: str,
    settings: Settings | None = None,
) -> tuple[bytes, str]:
    """Render a high-resolution portrait pass.

    Returns (png_bytes, qr_url).
    """
    settings = settings or get_settings()

    try:
        width, height = 1080, 1920
        img = Image.new("RGBA", (width, height), (*theme.BACKGROUND_RGB, 255))
        draw = ImageDraw.Draw(img)

        # Top brand band
        draw.rectangle([0, 0, width, 280], fill=(*theme.PRIMARY_RGB, 255))
        draw.rectangle([0, 280, width, 292], fill=(*theme.ACCENT_RGB, 255))

        # White logo plate
        plate = [70, 42, width - 70, 248]
        draw.rounded_rectangle(plate, radius=28, fill=(*theme.SURFACE_RGB, 255))

        ngo_logo = _fit_logo(settings.resolved_ngo_logo, 170, 170)
        partner_logo = _fit_logo(settings.resolved_partner_logo, 140, 140)

        # Primary logo left-of-center, partner secondary but readable
        gap = 36
        total_w = ngo_logo.width + gap + partner_logo.width
        start_x = (width - total_w) // 2
        logo_y = 145
        _paste(img, ngo_logo, start_x, logo_y - ngo_logo.height // 2)
        _paste(
            img,
            partner_logo,
            start_x + ngo_logo.width + gap,
            logo_y - partner_logo.height // 2,
        )

        font_kicker = _load_font(24, bold=True)
        font_event = _load_font(52, bold=True)
        font_label = _load_font(24, bold=True)
        font_meta = _load_font(30)
        font_name = _load_font(56, bold=True)
        font_ticket = _load_font(30, bold=True)
        font_hint = _load_font(26)
        font_thanks = _load_font(28)
        font_footer = _load_font(28, bold=True)

        y = 330

        # Event name
        for line in _wrap_text(draw, settings.event_name.upper(), font_event, width - 140):
            lw, lh = _text_size(draw, line, font_event)
            draw.text(((width - lw) // 2, y), line, fill=theme.TEXT_PRIMARY_RGB, font=font_event)
            y += lh + 6
        y += 18

        # Accent rule
        draw.rounded_rectangle(
            [width // 2 - 48, y, width // 2 + 48, y + 7],
            radius=4,
            fill=(*theme.PRIMARY_RGB, 255),
        )
        y += 28

        # Event meta block (dynamic height)
        meta_items = [
            ("Date", settings.event_date),
            ("Time", settings.event_time),
            ("Venue", settings.event_venue),
        ]
        meta_pad_top, meta_pad_bottom = 28, 28
        meta_content_h = 0
        for label, value in meta_items:
            meta_content_h += 26
            for line in _wrap_text(draw, value, font_meta, width - 280)[:2]:
                _, vh = _text_size(draw, line, font_meta)
                meta_content_h += vh + 2
            meta_content_h += 10
        meta_card = [90, y, width - 90, y + meta_pad_top + meta_content_h + meta_pad_bottom]
        draw.rounded_rectangle(
            meta_card,
            radius=22,
            fill=(*theme.SURFACE_RGB, 255),
            outline=(*theme.BORDER_RGB, 255),
            width=2,
        )
        meta_y = y + meta_pad_top
        for label, value in meta_items:
            draw.text((130, meta_y), label.upper(), fill=theme.PRIMARY_DARK_RGB, font=font_label)
            meta_y += 26
            for line in _wrap_text(draw, value, font_meta, width - 280)[:2]:
                draw.text((130, meta_y), line, fill=theme.TEXT_PRIMARY_RGB, font=font_meta)
                _, vh = _text_size(draw, line, font_meta)
                meta_y += vh + 2
            meta_y += 10
        y = meta_card[3] + 36

        # Attendee
        attendee_label = "ATTENDEE"
        alw, alh = _text_size(draw, attendee_label, font_kicker)
        draw.text(((width - alw) // 2, y), attendee_label, fill=theme.PRIMARY_RGB, font=font_kicker)
        y += alh + 14

        for line in _wrap_text(draw, attendee_name, font_name, width - 160)[:3]:
            lw, lh = _text_size(draw, line, font_name)
            draw.text(((width - lw) // 2, y), line, fill=theme.TEXT_PRIMARY_RGB, font=font_name)
            y += lh + 4
        y += 22

        # Ticket chip
        ticket_text = f"Ticket ID  {ticket_id}"
        tw, th = _text_size(draw, ticket_text, font_ticket)
        pad_x, pad_y = 30, 14
        chip = [
            (width - tw) // 2 - pad_x,
            y,
            (width + tw) // 2 + pad_x,
            y + th + pad_y * 2,
        ]
        draw.rounded_rectangle(
            chip,
            radius=40,
            fill=(232, 245, 236, 255),
            outline=(*theme.PRIMARY_SOFT_RGB, 255),
            width=2,
        )
        draw.text(
            ((width - tw) // 2, y + pad_y),
            ticket_text,
            fill=theme.PRIMARY_DARK_RGB,
            font=font_ticket,
        )
        y = chip[3] + 40

        # QR with quiet space
        qr_bytes, qr_url = generate_qr_png_bytes(
            ticket_id, settings=settings, box_size=14, border=2
        )
        qr_img = Image.open(io.BytesIO(qr_bytes)).convert("RGBA")
        qr_size = 400
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)

        card_pad = 32
        card = [
            (width - qr_size) // 2 - card_pad,
            y,
            (width + qr_size) // 2 + card_pad,
            y + qr_size + card_pad * 2 + 46,
        ]
        draw.rounded_rectangle(
            card,
            radius=28,
            fill=(*theme.SURFACE_RGB, 255),
            outline=(*theme.BORDER_RGB, 255),
            width=2,
        )
        img.alpha_composite(qr_img, ((width - qr_size) // 2, y + card_pad))
        hint = "Scan this QR code at the event"
        hw, hh = _text_size(draw, hint, font_hint)
        draw.text(
            ((width - hw) // 2, y + card_pad + qr_size + 14),
            hint,
            fill=theme.TEXT_SECONDARY_RGB,
            font=font_hint,
        )
        y = card[3] + 36

        # Thank-you
        thanks = settings.pass_thank_you.replace("\\n", "\n")
        for line in thanks.split("\n"):
            for wrapped in _wrap_text(draw, line, font_thanks, width - 180):
                ww, wh = _text_size(draw, wrapped, font_thanks)
                draw.text(
                    ((width - ww) // 2, y),
                    wrapped,
                    fill=theme.TEXT_SECONDARY_RGB,
                    font=font_thanks,
                )
                y += wh + 6

        # Footer
        draw.rectangle([0, height - 96, width, height], fill=(*theme.PRIMARY_DARK_RGB, 255))
        footer = settings.ngo_name
        fw, fh = _text_size(draw, footer, font_footer)
        draw.text(
            ((width - fw) // 2, height - 96 + (96 - fh) // 2),
            footer,
            fill=theme.WHITE_RGB,
            font=font_footer,
        )

        output = Image.new("RGB", (width, height), theme.BACKGROUND_RGB)
        output.paste(img, mask=img.split()[-1])
        buffer = io.BytesIO()
        output.save(buffer, format="PNG", optimize=False)
        return buffer.getvalue(), qr_url

    except Exception as exc:  # noqa: BLE001
        logger.exception("Pass rendering failed for ticket %s", ticket_id)
        raise PassGenerationError("Failed to generate event pass") from exc

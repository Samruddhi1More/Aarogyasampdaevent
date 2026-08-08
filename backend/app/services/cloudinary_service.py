"""Cloudinary upload for generated event passes."""

from __future__ import annotations

import logging
from typing import Any

import cloudinary
import cloudinary.uploader

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class CloudinaryError(Exception):
    """Raised when a Cloudinary upload fails."""


def _configure(settings: Settings) -> None:
    if not settings.cloudinary_configured:
        raise CloudinaryError(
            "Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."
        )
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    logger.info(
        "[diag] cloudinary_config_ok cloud_name_set=%s api_key_set=%s api_secret_set=%s",
        bool(settings.cloudinary_cloud_name),
        bool(settings.cloudinary_api_key),
        bool(settings.cloudinary_api_secret),
    )


def upload_pass_png(
    png_bytes: bytes,
    *,
    ticket_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Upload a pass PNG and return Cloudinary result including secure_url."""
    settings = settings or get_settings()
    _configure(settings)

    public_id = f"{settings.cloudinary_folder.rstrip('/')}/{ticket_id}"
    logger.info(
        "[diag] step=6 cloudinary_upload_started ticket=%s bytes=%s public_id=%s",
        ticket_id,
        len(png_bytes),
        public_id,
    )

    try:
        result = cloudinary.uploader.upload(
            png_bytes,
            public_id=public_id,
            folder=None,  # folder already in public_id
            overwrite=True,
            resource_type="image",
            format="png",
            unique_filename=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[diag] step=7 cloudinary_upload_failed type=%s msg=%s",
            type(exc).__name__,
            exc,
        )
        raise CloudinaryError("Failed to upload event pass") from exc

    secure_url = result.get("secure_url")
    if not secure_url:
        raise CloudinaryError("Cloudinary upload returned no secure URL")

    logger.info(
        "[diag] step=7 cloudinary_upload_succeeded public_id=%s url_prefix=%s",
        result.get("public_id"),
        secure_url[:64],
    )
    return {
        "secure_url": secure_url,
        "public_id": result.get("public_id"),
        "asset_id": result.get("asset_id"),
    }

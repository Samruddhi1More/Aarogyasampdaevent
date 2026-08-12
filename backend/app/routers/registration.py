"""Registration API routes."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import Response

from backend.app.config import get_settings
from backend.app.schemas import (
    PassStatusResponse,
    RegistrationRequest,
    RegistrationResponse,
)
from backend.app.services.google_sheets import (
    GoogleSheetsError,
    append_registration,
    find_row_by_registration_id,
    remember_ticket_id,
)
from backend.app.services.pass_orchestrator import (
    process_registration_after_submission,
)
from backend.app.services.ticket_service import generate_ticket_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["registration"])

IST = ZoneInfo("Asia/Kolkata")
_REG_ID_RE = re.compile(r"^AS-\d{8}-[A-Z0-9]{6}$", re.IGNORECASE)


def _generate_registration_id() -> str:
    """Unique, human-readable registration id, e.g. AS-20260808-A1B2C3."""
    now = datetime.now(tz=IST)
    suffix = uuid.uuid4().hex[:6].upper()
    return f"AS-{now.strftime('%Y%m%d')}-{suffix}"


def _validate_registration_id(registration_id: str) -> str:
    cleaned = (registration_id or "").strip()
    if not _REG_ID_RE.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid registration ID",
        )
    return cleaned


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegistrationRequest,
    background_tasks: BackgroundTasks,
) -> RegistrationResponse:
    registration_id = _generate_registration_id()
    ticket_id = generate_ticket_id()
    remember_ticket_id(ticket_id)
    timestamp = datetime.now(tz=IST)
    settings = get_settings()

    try:
        result = append_registration(
            registration_id=registration_id,
            name=payload.name,
            phone=payload.phone,
            email=payload.email,
            city=payload.city,
            invited_by=payload.invited_by,
            ticket_id=ticket_id,
            timestamp=timestamp,
            settings=settings,
        )
    except GoogleSheetsError as exc:
        logger.error("Registration failed for %s: %s", registration_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc)
            or "Registration service temporarily unavailable. Please try again.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected registration error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong while saving your registration. Please try again.",
        ) from exc

    logger.info("[REGISTRATION] Saved to Google Sheets id=%s ticket=%s", registration_id, ticket_id)

    # Pass / email run after the response is sent — per-request data only
    background_tasks.add_task(
        process_registration_after_submission,
        registration_id=registration_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        ticket_id=ticket_id,
    )

    if payload.email:
        message = (
            "Registration successful! Your event pass is being prepared "
            "and will be sent to your email shortly."
        )
        email_status = "PENDING"
    else:
        message = "Registration successful! Your event pass is being prepared."
        email_status = "NOT_PROVIDED"

    logger.info("[REGISTRATION] Response returned to user id=%s", registration_id)

    return RegistrationResponse(
        success=True,
        message=message,
        registration_id=result["registration_id"],
        timestamp=result["timestamp"],
        ticket_id=ticket_id,
        qr_url=None,
        pass_url=None,
        pass_generation_status="PENDING",
        email_status=email_status,
        email_provided=bool(payload.email),
    )


@router.get(
    "/register/{registration_id}/pass-status",
    response_model=PassStatusResponse,
)
async def get_pass_status(registration_id: str) -> PassStatusResponse:
    """Poll Cloudinary Pass URL readiness for the Download Pass button."""
    registration_id = _validate_registration_id(registration_id)
    settings = get_settings()

    try:
        row = find_row_by_registration_id(registration_id, settings=settings)
    except GoogleSheetsError as exc:
        logger.error("[PASS STATUS] Sheet lookup failed id=%s: %s", registration_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to check pass status right now. Please try again.",
        ) from exc

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    pass_status = (row.get("pass_generation_status") or "PENDING").strip().upper()
    pass_url = (row.get("pass_url") or "").strip() or None
    ticket_id = (row.get("ticket_id") or "").strip() or None
    ready = pass_status == "SUCCESS" and bool(pass_url)

    if ready:
        message = "Your event pass is ready to download."
    elif pass_status == "FAILED":
        message = "Pass generation failed. Please contact support with your Ticket ID."
    else:
        message = "Your event pass is still being prepared."

    return PassStatusResponse(
        registration_id=registration_id,
        ticket_id=ticket_id,
        pass_generation_status=pass_status or "PENDING",
        pass_url=pass_url if ready else None,
        download_ready=ready,
        message=message,
    )


@router.get("/register/{registration_id}/pass")
async def download_pass(registration_id: str) -> Response:
    """Download the same personalized Cloudinary PNG used for email/WhatsApp."""
    registration_id = _validate_registration_id(registration_id)
    settings = get_settings()

    try:
        row = find_row_by_registration_id(registration_id, settings=settings)
    except GoogleSheetsError as exc:
        logger.error("[PASS DOWNLOAD] Sheet lookup failed id=%s: %s", registration_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to download pass right now. Please try again.",
        ) from exc

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    pass_url = (row.get("pass_url") or "").strip()
    ticket_id = (row.get("ticket_id") or "").strip() or "pass"
    pass_status = (row.get("pass_generation_status") or "").strip().upper()

    if pass_status != "SUCCESS" or not pass_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pass is not ready yet. Please wait a moment and try again.",
        )

    if not pass_url.startswith("https://") or "cloudinary.com" not in pass_url:
        logger.error("[PASS DOWNLOAD] Invalid pass URL for id=%s", registration_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Pass file is unavailable.",
        )

    try:
        upstream = requests.get(pass_url, timeout=45)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        logger.error(
            "[PASS DOWNLOAD] Cloudinary fetch failed id=%s type=%s",
            registration_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to fetch your event pass. Please try again.",
        ) from exc

    png_bytes = upstream.content
    if not png_bytes:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Pass file is empty.",
        )

    filename = f"{ticket_id}-event-pass.png"
    logger.info(
        "[PASS DOWNLOAD] Served pass id=%s ticket=%s bytes=%s",
        registration_id,
        ticket_id,
        len(png_bytes),
    )
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )

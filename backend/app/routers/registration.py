"""Registration API routes."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from backend.app.config import get_settings
from backend.app.schemas import RegistrationRequest, RegistrationResponse
from backend.app.services.google_sheets import (
    GoogleSheetsError,
    append_registration,
    remember_ticket_id,
)
from backend.app.services.pass_orchestrator import (
    process_registration_after_submission,
)
from backend.app.services.ticket_service import generate_ticket_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["registration"])

IST = ZoneInfo("Asia/Kolkata")


def _generate_registration_id() -> str:
    """Unique, human-readable registration id, e.g. AS-20260808-A1B2C3."""
    now = datetime.now(tz=IST)
    suffix = uuid.uuid4().hex[:6].upper()
    return f"AS-{now.strftime('%Y%m%d')}-{suffix}"


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

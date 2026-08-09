"""Pydantic request/response schemas and field validators."""

from __future__ import annotations

import re
from typing import Optional

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field, field_validator

INDIAN_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ.'\-\s]{2,100}$")


class RegistrationRequest(BaseModel):
    name: str = Field(..., examples=["Priya Sharma"])
    phone: str = Field(..., examples=["9876543210"])
    email: Optional[str] = Field(default=None, examples=["priya@example.com"])
    city: str = Field(..., examples=["Pune"])
    invited_by: str = Field(..., examples=["Founder"])

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = " ".join(str(value).split()).strip()
        if not cleaned:
            raise ValueError("Name cannot be empty")
        if len(cleaned) > 100:
            raise ValueError("Name is too long")
        if not NAME_RE.match(cleaned):
            raise ValueError("Please enter a valid full name")
        return cleaned

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        digits = re.sub(r"[\s\-()]", "", value.strip())
        if digits.startswith("+91"):
            digits = digits[3:]
        elif digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]

        if not INDIAN_MOBILE_RE.match(digits):
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return digits

    @field_validator("email")
    @classmethod
    def validate_optional_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            result = validate_email(cleaned, check_deliverability=False)
            return result.normalized
        except EmailNotValidError as exc:
            raise ValueError("Please enter a valid email address") from exc

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: str) -> str:
        cleaned = " ".join(str(value).split()).strip()
        if not cleaned:
            raise ValueError("City cannot be empty")
        if len(cleaned) < 2:
            raise ValueError("Please enter a valid city name")
        if len(cleaned) > 100:
            raise ValueError("City name is too long")
        return cleaned

    @field_validator("invited_by")
    @classmethod
    def validate_invited_by(cls, value: str) -> str:
        cleaned = " ".join(str(value).split()).strip()
        if not cleaned:
            raise ValueError("Invited by is required")
        if len(cleaned) > 120:
            raise ValueError("Invited by is too long")
        return cleaned


class RegistrationResponse(BaseModel):
    success: bool = True
    message: str
    registration_id: str
    timestamp: str
    ticket_id: Optional[str] = None
    qr_url: Optional[str] = None
    pass_url: Optional[str] = None
    pass_generation_status: Optional[str] = None
    email_status: Optional[str] = None
    email_provided: bool = False

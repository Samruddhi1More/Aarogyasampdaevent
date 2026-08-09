"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Aarogyasampada Registration"
    cors_origins: str = "*"

    # Google Sheets
    google_sheet_id: str
    google_worksheet_name: str = "Sheet1"
    google_service_account_file: str

    # Event details (replace via .env)
    event_name: str = "Sahjeevan Puraskar 2026"
    event_date: str = "29 August 2026"
    event_time: str = "2:30 PM"
    event_venue: str = "Dnyaneshwar Sabhagruha, Marathwada Mitra Mandal Law College"
    event_organizer: str = "PLACEHOLDER_ORGANIZER_NAME"
    ngo_name: str = "Aarogyasampada 360 Degree"
    pass_thank_you: str = (
        "Thank you for registering.\nWe look forward to welcoming you."
    )

    # Pass / QR
    pass_base_url: str = "https://aarogyasampada360.com/pass"
    cloudinary_folder: str = "sahjeevan-puraskar-2026/passes"

    # Logo paths (absolute or relative to project root)
    ngo_logo_path: str = str(ROOT_DIR / "assets" / "logos" / "aarogyasampada-logo.png")
    partner_logo_path: str = str(ROOT_DIR / "assets" / "logos" / "partner-logo.png")

    # Cloudinary
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # Gmail SMTP
    email_host: str = "smtp.gmail.com"
    email_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_from: str = ""

    # WATI WhatsApp (disabled by default — no real sends)
    wati_enabled: bool = False
    wati_api_endpoint: str = ""
    wati_api_token: str = ""
    wati_whatsapp_number: str = "15553177267"
    wati_template_name: str = "sahjeevan_event_pass"
    wati_template_language: str = "en_GB"
    wati_broadcast_name: str = "Sahjeevan_Puraskar_2026"
    wati_test_phone: str = ""
    # Explicit template customParam names (must match approved WATI template)
    wati_param_attendee_name: str = "name"
    wati_param_ticket_id: str = "ticket_id"
    wati_param_header_image: str = "header_image"

    @field_validator("google_service_account_file")
    @classmethod
    def validate_service_account_file(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_FILE is required. "
                "Set it to your service account JSON path "
                "(e.g. service-account.json locally)."
            )
        return cleaned

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def service_account_path(self) -> Path:
        """Resolved credential path from GOOGLE_SERVICE_ACCOUNT_FILE."""
        load_dotenv()
        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or self.google_service_account_file
        if not raw or not str(raw).strip():
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_FILE is not set. "
                "Set this environment variable to the path of your Google "
                "service account JSON file."
            )
        path = Path(raw.strip()).expanduser()
        if not path.is_absolute():
            path = (ROOT_DIR / path).resolve()
        else:
            path = path.resolve()
        return path

    @property
    def resolved_ngo_logo(self) -> Path:
        path = Path(self.ngo_logo_path).expanduser()
        return path if path.is_absolute() else (ROOT_DIR / path).resolve()

    @property
    def resolved_partner_logo(self) -> Path:
        path = Path(self.partner_logo_path).expanduser()
        return path if path.is_absolute() else (ROOT_DIR / path).resolve()

    @property
    def cloudinary_configured(self) -> bool:
        return bool(
            self.cloudinary_cloud_name
            and self.cloudinary_api_key
            and self.cloudinary_api_secret
        )

    @property
    def email_configured(self) -> bool:
        return bool(
            self.email_host
            and self.email_port
            and self.email_username
            and self.email_password
            and self.email_from
        )

    @property
    def wati_configured(self) -> bool:
        return bool(
            self.wati_api_endpoint.strip()
            and self.wati_api_token.strip()
            and self.wati_whatsapp_number.strip()
            and self.wati_template_name.strip()
            and self.wati_broadcast_name.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

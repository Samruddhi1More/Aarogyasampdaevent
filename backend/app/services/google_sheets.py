"""Google Sheets integration via a Service Account.

Preserves existing registration append behavior and adds idempotent
pass-field updates using header-name mapping (with aliases for older sheets).

Designed to minimize Sheets API reads (quota-friendly).

Credential path is read only from GOOGLE_SERVICE_ACCOUNT_FILE (never hardcoded).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

from backend.app.config import Settings, get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parents[3]

SHEET_HEADERS = [
    "Timestamp",
    "Registration ID",
    "Name",
    "Phone",
    "Email",
    "City",
    "Invited by",
    "Ticket ID",
    "QR URL",
    "Pass URL",
    "Pass Generation Status",
    "Email Status",
    "WhatsApp",
    "SMS",
]

HEADER_ALIASES: dict[str, list[str]] = {
    "Timestamp": ["Timestamp"],
    "Registration ID": ["Registration ID"],
    "Name": ["Name", "Full Name"],
    "Phone": ["Phone"],
    "Email": ["Email"],
    "City": ["City"],
    # Prefer "Invited by"; reuse existing "Organization" column if present (no duplicate)
    "Invited by": ["Invited by", "Organization"],
    "Ticket ID": ["Ticket ID"],
    "QR URL": ["QR URL", "QR Token"],
    "Pass URL": ["Pass URL"],
    "Pass Generation Status": ["Pass Generation Status"],
    "Email Status": ["Email Status", "Email Sent"],
    "WhatsApp": ["WhatsApp Status", "WhatsApp"],
    "SMS": ["SMS"],
}

# Simple in-process caches to avoid burning Sheets quota
_HEADER_CACHE: dict[str, Any] = {"headers": None, "index": None, "expires": 0.0}
_TICKET_CACHE: set[str] = set()
_HEADER_TTL_SECONDS = 300.0


class GoogleSheetsError(Exception):
    """Raised when a Google Sheets operation fails."""


def resolve_google_service_account_file() -> Path:
    """Return the service-account JSON path from GOOGLE_SERVICE_ACCOUNT_FILE.

    Never hardcodes a filename. Supports absolute paths (e.g. Render secret files)
    and relative paths resolved from the project root (local development).
    """
    load_dotenv()
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if raw is None or not str(raw).strip():
        raise GoogleSheetsError(
            "GOOGLE_SERVICE_ACCOUNT_FILE is not set. "
            "Set this environment variable to the path of your Google service "
            "account JSON (e.g. service-account.json locally, or the Render "
            "Secret File path in production)."
        )

    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()

    if not path.is_file():
        raise GoogleSheetsError(
            f"GOOGLE_SERVICE_ACCOUNT_FILE points to a missing file: {path}"
        )

    return path


@lru_cache
def _get_client(service_account_file: str) -> gspread.Client:
    credentials = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    return gspread.authorize(credentials)


def _worksheet(settings: Settings):
    service_account_file = resolve_google_service_account_file()

    try:
        client = _get_client(str(service_account_file))
        spreadsheet = client.open_by_key(settings.google_sheet_id)
        return spreadsheet.worksheet(settings.google_worksheet_name)
    except GoogleSheetsError:
        raise
    except gspread.exceptions.WorksheetNotFound as exc:
        raise GoogleSheetsError(
            f"Worksheet '{settings.google_worksheet_name}' not found"
        ) from exc
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError(
            "Google Sheet not found or not shared with the service account"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to open Google Sheet")
        raise GoogleSheetsError("Unable to connect to Google Sheets") from exc


def _header_row(worksheet) -> list[str]:
    return [h.strip() for h in worksheet.row_values(1)]


def _build_header_index(headers: list[str]) -> dict[str, int]:
    lower_map = {h.lower(): idx for idx, h in enumerate(headers, start=1) if h}
    index: dict[str, int] = {}
    for logical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            col = lower_map.get(alias.lower())
            if col:
                index[logical] = col
                break
    return index


def _get_headers_and_index(worksheet, *, force: bool = False) -> tuple[list[str], dict[str, int]]:
    now = time.time()
    if (
        not force
        and _HEADER_CACHE["headers"] is not None
        and _HEADER_CACHE["expires"] > now
    ):
        return _HEADER_CACHE["headers"], _HEADER_CACHE["index"]

    headers = _header_row(worksheet)
    index = _build_header_index(headers)
    _HEADER_CACHE["headers"] = headers
    _HEADER_CACHE["index"] = index
    _HEADER_CACHE["expires"] = now + _HEADER_TTL_SECONDS
    return headers, index


def invalidate_header_cache() -> None:
    _HEADER_CACHE["headers"] = None
    _HEADER_CACHE["index"] = None
    _HEADER_CACHE["expires"] = 0.0


def ensure_headers(settings: Settings | None = None) -> None:
    """Ensure required headers exist. Adds missing columns; never duplicates rows."""
    settings = settings or get_settings()
    worksheet = _worksheet(settings)
    existing = _header_row(worksheet)

    if not existing:
        worksheet.append_row(SHEET_HEADERS, value_input_option="USER_ENTERED")
        invalidate_header_cache()
        return

    # Rename legacy "Organization" header to "Invited by" in-place (no new column)
    renamed = False
    for idx, header in enumerate(existing, start=1):
        if header.strip().lower() == "organization":
            worksheet.update_cell(1, idx, "Invited by")
            existing[idx - 1] = "Invited by"
            renamed = True
            logger.info("Renamed Google Sheet column Organization → Invited by")
            break

    present_lower = {h.lower() for h in existing if h}
    missing: list[str] = []
    for header in SHEET_HEADERS:
        aliases = HEADER_ALIASES.get(header, [header])
        if not any(a.lower() in present_lower for a in aliases):
            missing.append(header)

    if missing:
        start_col = len(existing) + 1
        cells = [
            gspread.Cell(1, start_col + offset, name) for offset, name in enumerate(missing)
        ]
        worksheet.update_cells(cells, value_input_option="USER_ENTERED")
        logger.info("Added missing Google Sheet columns: %s", missing)
        invalidate_header_cache()
    elif renamed:
        invalidate_header_cache()
        _get_headers_and_index(worksheet, force=True)
    else:
        _HEADER_CACHE["headers"] = existing
        _HEADER_CACHE["index"] = _build_header_index(existing)
        _HEADER_CACHE["expires"] = time.time() + _HEADER_TTL_SECONDS


def append_registration(
    *,
    registration_id: str,
    name: str,
    phone: str,
    email: str | None,
    city: str,
    timestamp: datetime | None = None,
    invited_by: str = "",
    ticket_id: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Append a registration row. Pass media fields filled by background processing."""
    settings = settings or get_settings()
    ts = timestamp or datetime.now(tz=IST)
    timestamp_str = ts.strftime("%Y-%m-%d %H:%M:%S")

    try:
        worksheet = _worksheet(settings)
        headers, index = _get_headers_and_index(worksheet)

        values = {
            "Timestamp": timestamp_str,
            "Registration ID": registration_id,
            "Name": name,
            "Phone": phone,
            "Email": email or "",
            "City": city,
            "Invited by": invited_by or "",
            "Ticket ID": ticket_id or "",
            "QR URL": "",
            "Pass URL": "",
            "Pass Generation Status": "PENDING",
            "Email Status": "NOT_PROVIDED" if not email else "PENDING",
            "WhatsApp": "NOT_ATTEMPTED",
            "SMS": "",
        }

        row = [""] * max(len(headers), 1)
        for logical, value in values.items():
            col = index.get(logical)
            if col:
                while len(row) < col:
                    row.append("")
                row[col - 1] = value

        worksheet.append_row(row, value_input_option="USER_ENTERED")
    except GoogleSheetsError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to append registration row")
        raise GoogleSheetsError("Failed to save registration to Google Sheets") from exc

    return {
        "registration_id": registration_id,
        "timestamp": timestamp_str,
        "timestamp_utc": ts.astimezone(timezone.utc).isoformat(),
    }


def find_row_by_registration_id(
    registration_id: str,
    *,
    settings: Settings | None = None,
) -> Optional[dict[str, Any]]:
    """Return row metadata and logical field values for a registration id."""
    settings = settings or get_settings()
    try:
        worksheet = _worksheet(settings)
        headers, index = _get_headers_and_index(worksheet)
        reg_col = index.get("Registration ID")
        if not reg_col:
            raise GoogleSheetsError("Registration ID column not found")

        try:
            cell = worksheet.find(registration_id, in_column=reg_col)
        except gspread.exceptions.CellNotFound:
            return None
        if not cell:
            return None

        row_values = worksheet.row_values(cell.row)
        while len(row_values) < len(headers):
            row_values.append("")

        def get(logical: str) -> str:
            col = index.get(logical)
            if not col or col > len(row_values):
                return ""
            return (row_values[col - 1] or "").strip()

        return {
            "row_number": cell.row,
            "registration_id": get("Registration ID"),
            "name": get("Name"),
            "phone": get("Phone"),
            "email": get("Email"),
            "city": get("City"),
            "ticket_id": get("Ticket ID"),
            "qr_url": get("QR URL"),
            "pass_url": get("Pass URL"),
            "pass_generation_status": get("Pass Generation Status"),
            "email_status": get("Email Status"),
            "whatsapp_status": get("WhatsApp"),
        }
    except GoogleSheetsError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to find registration %s", registration_id)
        raise GoogleSheetsError("Failed to look up registration") from exc


def ticket_id_exists(ticket_id: str, *, settings: Settings | None = None) -> bool:
    """Fast uniqueness check using an in-memory cache.

    Full sheet scans are avoided to protect API quota. Collision probability
    for SAP-XXXXXXXX is extremely low; cache covers the running process.
    """
    _ = settings  # reserved for future remote checks
    return ticket_id in _TICKET_CACHE


def remember_ticket_id(ticket_id: str) -> None:
    if ticket_id:
        _TICKET_CACHE.add(ticket_id)


def update_registration_fields(
    registration_id: str,
    fields: dict[str, str],
    *,
    settings: Settings | None = None,
) -> None:
    """Update logical fields on an existing registration row (no new row)."""
    settings = settings or get_settings()
    try:
        worksheet = _worksheet(settings)
        _, index = _get_headers_and_index(worksheet)

        reg_col = index.get("Registration ID")
        if not reg_col:
            raise GoogleSheetsError("Registration ID column not found")

        try:
            cell = worksheet.find(registration_id, in_column=reg_col)
        except gspread.exceptions.CellNotFound as exc:
            raise GoogleSheetsError(f"Registration {registration_id} not found") from exc
        if not cell:
            raise GoogleSheetsError(f"Registration {registration_id} not found")

        updates: list[gspread.Cell] = []
        for logical, value in fields.items():
            col = index.get(logical)
            if not col:
                logger.warning("Skipping unknown sheet field %s", logical)
                continue
            updates.append(gspread.Cell(cell.row, col, value))

        if updates:
            worksheet.update_cells(updates, value_input_option="USER_ENTERED")

        if fields.get("Ticket ID"):
            remember_ticket_id(fields["Ticket ID"])
    except GoogleSheetsError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to update registration %s", registration_id)
        raise GoogleSheetsError("Failed to update registration in Google Sheets") from exc

# Aarogyasampada — Sahjeevan Puraskar 2026 Registration

Registration form + Google Sheets storage + **event pass generation**, Cloudinary upload, and Resend email delivery.

## Features

- Mobile-first registration (name, phone, optional email, city)
- Google Sheets append + pass field updates (no duplicate rows)
- Unique Ticket IDs (`SAP-XXXXXXXX`)
- QR codes pointing to `https://aarogyasampada360.com/pass/{ticket_id}` (no PII in QR)
- Premium portrait PNG event pass
- Cloudinary upload under `sahjeevan-puraskar-2026/passes/`
- Resend HTTPS API pass delivery when email is provided
- Idempotent pass generation (reuses Ticket ID + Pass URL)
- WhatsApp / WATI placeholder only (not implemented)

## Brand colors (Aarogyasampada logo)

| Role | Hex |
|------|-----|
| Primary | `#E86828` |
| Secondary | `#1A1412` |
| Accent | `#F0B090` |

## Project structure

```
.
├── assets/logos/
│   ├── aarogyasampada.png   # NGO logo (primary)
│   ├── partner.png          # Partner logo (replace with official file)
│   └── README.md
├── backend/app/
│   ├── config.py
│   ├── schemas.py
│   ├── main.py
│   ├── routers/registration.py
│   └── services/
│       ├── google_sheets.py
│       ├── ticket_service.py
│       ├── qr_service.py
│       ├── pass_service.py
│       ├── cloudinary_service.py
│       ├── email_service.py
│       ├── whatsapp_service.py      # stub / interface only
│       └── pass_orchestrator.py
├── frontend/
├── .env.example
├── requirements.txt
└── README.md
```

## Logos

Place official files at:

1. `assets/logos/aarogyasampada.png` — Aarogyasampada 360 Degree
2. `assets/logos/partner.png` — Partner / co-organizer

Or set `NGO_LOGO_PATH` / `PARTNER_LOGO_PATH` in `.env`.

## Environment variables

```bash
cp .env.example .env
```

| Variable | Purpose |
|----------|---------|
| `GOOGLE_SHEET_ID` | Spreadsheet id |
| `GOOGLE_WORKSHEET_NAME` | Worksheet name |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to service-account JSON |
| `EVENT_NAME` / `EVENT_DATE` / `EVENT_TIME` / `EVENT_VENUE` / `EVENT_ORGANIZER` | Event copy on pass + email |
| `NGO_NAME` | Organizer / footer branding |
| `PASS_BASE_URL` | QR base URL |
| `NGO_LOGO_PATH` / `PARTNER_LOGO_PATH` | Logo files |
| `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | Pass hosting |
| `CLOUDINARY_FOLDER` | Upload folder |
| `EMAIL_ENABLED` / `RESEND_API_KEY` / `EMAIL_FROM` | Resend HTTPS email (no SMTP) |

Never commit `.env` or credential JSON files.

## Google Sheet columns

Preferred headers (missing columns are added automatically; existing aliases are reused):

| Column | Notes |
|--------|--------|
| Timestamp | Set on registration |
| Registration ID | `AS-YYYYMMDD-XXXXXX` |
| Name | (alias: Full Name) |
| Phone | |
| Email | optional |
| City | |
| Organization | reserved (blank for now) |
| Ticket ID | `SAP-XXXXXXXX` |
| QR URL | (alias: QR Token) |
| Pass URL | Cloudinary secure URL |
| Pass Generation Status | `GENERATED` / `FAILED` / … |
| Email Status | `SENT` / `FAILED` / `NOT_PROVIDED` |
| WhatsApp | stub status for later |
| SMS | reserved |

## Install & run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000

### API

`POST /register`

```json
{
  "name": "Priya Sharma",
  "phone": "9876543210",
  "email": "priya@example.com",
  "city": "Pune"
}
```

Response includes `ticket_id`, `pass_url`, `qr_url`, `pass_generation_status`, `email_status`.

## Replace placeholder event details

Edit `.env` only:

```env
EVENT_DATE=15 March 2026
EVENT_TIME=5:00 PM IST
EVENT_VENUE=Your Venue Name, City
EVENT_ORGANIZER=Aarogyasampada 360 Degree
```

Restart the server after changes.

## Testing checklist

1. Registration **with** email → pass generated, Cloudinary URL stored, email `SENT`
2. Registration **without** email → pass generated, `Email Status = NOT_PROVIDED`
3. Pass PNG renders with logos, name, ticket id, QR, placeholders
4. QR decodes to `https://aarogyasampada360.com/pass/{ticket_id}`
5. Sheet row updated (not duplicated)
6. Email attachment opens as PNG
7. Re-running pass for same registration reuses Ticket ID + Pass URL
8. Email failure does **not** fail registration
9. Cloudinary failure does **not** fail registration (status `FAILED`)
10. Invalid email rejected by validation

### Local smoke (pass + QR only)

```bash
source .venv/bin/activate
python - <<'PY'
from backend.app.services.ticket_service import generate_ticket_id
from backend.app.services.qr_service import generate_qr_png_bytes, build_pass_qr_url
from backend.app.services.pass_service import generate_pass_png

tid = generate_ticket_id()
url = build_pass_qr_url(tid)
assert tid.startswith('SAP-') and url.endswith(tid)
png, qr = generate_pass_png(attendee_name='Priya Sharma', ticket_id=tid)
open('/tmp/sahjeevan-pass-sample.png','wb').write(png)
print(tid, qr, len(png))
PY
```

## Out of scope

- WhatsApp / WATI delivery (interface stub only)
- SMS delivery
- Live QR verification page at `aarogyasampada360.com`

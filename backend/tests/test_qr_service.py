"""Unit tests for QR destination URL."""

from __future__ import annotations

import unittest

from backend.app.config import Settings
from backend.app.services.qr_service import build_pass_qr_url, generate_qr_png_bytes


class QrServiceTests(unittest.TestCase):
    def test_qr_payload_is_main_website(self) -> None:
        settings = Settings(
            google_service_account_file="service-account.json",
            pass_base_url="https://aarogyasampada360.com",
        )
        url = build_pass_qr_url("SAP-ANYTICKET", settings=settings)
        self.assertEqual(url, "https://aarogyasampada360.com")
        self.assertNotIn("SAP-ANYTICKET", url)
        self.assertFalse(url.endswith("/pass"))

        png, qr_url = generate_qr_png_bytes("SAP-ANYTICKET", settings=settings)
        self.assertEqual(qr_url, "https://aarogyasampada360.com")
        self.assertTrue(png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()

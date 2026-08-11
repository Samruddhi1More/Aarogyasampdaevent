"""Unit tests for WATI WhatsApp template sending (no live API calls)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import requests

from backend.app.config import Settings
from backend.app.services.wati_service import (
    WatiError,
    assert_pass_url_matches_ticket,
    build_template_payload,
    send_event_pass,
)


TICKET = "SAP-ABC12345"
PASS_URL = (
    "https://res.cloudinary.com/kml4eazb/image/upload/v1/"
    f"sahjeevan-puraskar-2026/passes/{TICKET}.png"
)


def _settings(**overrides: Any) -> Settings:
    base = dict(
        google_service_account_file="service-account.json",
        wati_enabled=True,
        wati_api_endpoint="https://example-wati.test/tenant",
        wati_api_token="test-token-not-a-secret-for-unit-tests",
        wati_whatsapp_number="15553177267",
        wati_template_name="aarogyasampaevent",
        wati_template_language="en",
        wati_broadcast_name="aarogyasampaevent",
        wati_param_attendee_name="1",
        wati_param_ticket_id="2",
        wati_param_header_image="image",
        event_name="Sahjeevan Gaurav Puraskar 2026",
        event_date="29 August 2026",
        event_time="2:30 PM",
        event_venue="Dnyaneshwar Sabhagruha, Marathwada Mitra Mandal Law College",
    )
    base.update(overrides)
    return Settings(**base)


def _mock_response(status_code: int, body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = b"{}"
    response.json.return_value = body
    return response


class WatiServiceTests(unittest.TestCase):
    def test_build_template_payload_uses_approved_template_and_params(self) -> None:
        settings = _settings()
        payload = build_template_payload(
            whatsapp_number="919876543210",
            attendee_name="Riya Sharma",
            ticket_id=TICKET,
            pass_url=PASS_URL,
            settings=settings,
        )

        self.assertEqual(payload["template_name"], "aarogyasampaevent")
        self.assertEqual(payload["broadcast_name"], "aarogyasampaevent")
        params = {
            p["name"]: p["value"] for p in payload["receivers"][0]["customParams"]
        }
        self.assertEqual(params["1"], "Riya Sharma")
        self.assertEqual(params["2"], TICKET)
        self.assertEqual(params["image"], PASS_URL)
        self.assertNotIn("SAP-L8T92O57", str(payload))
        self.assertNotIn("SAP-FPTM7STD", str(payload))

    def test_assert_pass_url_rejects_mismatched_ticket(self) -> None:
        with self.assertRaises(WatiError):
            assert_pass_url_matches_ticket(
                "https://res.cloudinary.com/kml4eazb/image/upload/v1/"
                "sahjeevan-puraskar-2026/passes/SAP-OTHER.png",
                TICKET,
            )

    @patch("backend.app.services.wati_service.assert_template_allows_dynamic_image")
    @patch("backend.app.services.wati_service.requests.post")
    def test_success_is_sent_without_session_or_chat_status(
        self,
        mock_post: MagicMock,
        mock_assert_dynamic: MagicMock,
    ) -> None:
        settings = _settings()

        def post_side_effect(url: str, *args: Any, **kwargs: Any) -> MagicMock:
            if "updateContactAttributes" in url:
                return _mock_response(200, {"result": True})
            if "sendTemplateMessages" in url:
                return _mock_response(200, {"result": True, "errors": {}})
            raise AssertionError(f"Unexpected POST URL: {url}")

        mock_post.side_effect = post_side_effect

        result = send_event_pass(
            phone_number="9876543210",
            attendee_name="Riya Sharma",
            ticket_id=TICKET,
            pass_url=PASS_URL,
            pass_png=b"fake-png-bytes",
            settings=settings,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "SENT")
        self.assertEqual(result.normalized_phone, "919876543210")
        assert result.payload is not None
        self.assertEqual(result.payload["template_name"], "aarogyasampaevent")
        params = {
            p["name"]: p["value"]
            for p in result.payload["receivers"][0]["customParams"]
        }
        self.assertEqual(params["image"], PASS_URL)
        self.assertEqual(params["1"], "Riya Sharma")
        self.assertEqual(params["2"], TICKET)

        posted_urls = [call.args[0] for call in mock_post.call_args_list]
        self.assertTrue(any("sendTemplateMessages" in u for u in posted_urls))
        self.assertFalse(any("sendSessionFile" in u for u in posted_urls))
        self.assertFalse(any("updateChatStatus" in u for u in posted_urls))
        mock_assert_dynamic.assert_called_once()

    @patch("backend.app.services.wati_service.assert_template_allows_dynamic_image")
    @patch("backend.app.services.wati_service.requests.post")
    def test_template_failure_is_failed(
        self,
        mock_post: MagicMock,
        mock_assert_dynamic: MagicMock,
    ) -> None:
        settings = _settings()

        def post_side_effect(url: str, *args: Any, **kwargs: Any) -> MagicMock:
            if "updateContactAttributes" in url:
                return _mock_response(404, {"result": False, "info": "contact missing"})
            if "sendTemplateMessages" in url:
                return _mock_response(200, {"result": False, "info": "template error"})
            raise AssertionError(f"Unexpected POST URL: {url}")

        mock_post.side_effect = post_side_effect

        result = send_event_pass(
            phone_number="9876543210",
            attendee_name="Riya Sharma",
            ticket_id=TICKET,
            pass_url=PASS_URL,
            settings=settings,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "FAILED")
        posted_urls = [call.args[0] for call in mock_post.call_args_list]
        self.assertTrue(any("sendTemplateMessages" in u for u in posted_urls))
        self.assertFalse(any("sendSessionFile" in u for u in posted_urls))
        self.assertFalse(any("updateChatStatus" in u for u in posted_urls))
        mock_assert_dynamic.assert_called_once()

    @patch("backend.app.services.wati_service.assert_template_allows_dynamic_image")
    @patch("backend.app.services.wati_service.requests.post")
    def test_update_contact_failure_does_not_block_template_send(
        self,
        mock_post: MagicMock,
        mock_assert_dynamic: MagicMock,
    ) -> None:
        settings = _settings()

        def post_side_effect(url: str, *args: Any, **kwargs: Any) -> MagicMock:
            if "updateContactAttributes" in url:
                raise requests.ConnectionError("contact missing")
            if "sendTemplateMessages" in url:
                return _mock_response(200, {"result": True})
            raise AssertionError(f"Unexpected POST URL: {url}")

        mock_post.side_effect = post_side_effect

        result = send_event_pass(
            phone_number="9876543210",
            attendee_name="Riya Sharma",
            ticket_id=TICKET,
            pass_url=PASS_URL,
            settings=settings,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "SENT")
        posted_urls = [call.args[0] for call in mock_post.call_args_list]
        self.assertTrue(any("sendTemplateMessages" in u for u in posted_urls))
        self.assertFalse(any("sendSessionFile" in u for u in posted_urls))
        self.assertFalse(any("updateChatStatus" in u for u in posted_urls))
        mock_assert_dynamic.assert_called_once()


if __name__ == "__main__":
    unittest.main()

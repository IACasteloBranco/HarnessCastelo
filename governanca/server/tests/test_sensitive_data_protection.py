import os
import unittest
from unittest.mock import AsyncMock, patch

from google.cloud import dlp_v2

from governanca.server.data_protection import Category, Finding
from governanca.server.sensitive_data_protection import (
    InspectionUnavailable,
    _client,
    inspect_sensitive_data,
)


class SensitiveDataProtectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "SENSITIVE_DATA_PROTECTION_PROJECT_ID": "synthetic-project",
            "SENSITIVE_DATA_PROTECTION_LOCATION": "southamerica-east1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_sends_explicit_info_types_without_quotes_and_maps_unicode_offsets(self):
        text = "Olá 😀, email ana@example.invalid"
        start = text.index("ana@example.invalid")
        response = dlp_v2.types.InspectContentResponse(result={"findings": [{
            "info_type": {"name": "EMAIL_ADDRESS"},
            "location": {"codepoint_range": {"start": start, "end": len(text)}},
        }]})
        client = AsyncMock()
        client.inspect_content.return_value = response
        with patch("governanca.server.sensitive_data_protection._client", return_value=client):
            findings = await inspect_sensitive_data(text)

        self.assertEqual(findings, (Finding(Category.EMAIL, start, len(text)),))
        request = client.inspect_content.await_args.kwargs["request"]
        dlp_v2.types.InspectContentRequest(**request)
        self.assertEqual(request["parent"], "projects/synthetic-project/locations/southamerica-east1")
        self.assertEqual({item["name"] for item in request["inspect_config"]["info_types"]},
                         {"BRAZIL_CPF_NUMBER", "EMAIL_ADDRESS", "PHONE_NUMBER"})
        self.assertFalse(request["inspect_config"]["include_quote"])
        self.assertEqual(client.inspect_content.await_args.kwargs["timeout"], 8.0)

    async def test_rejects_remote_cpf_that_fails_local_checksum(self):
        text = "12345678900"
        response = dlp_v2.types.InspectContentResponse(result={"findings": [{
            "info_type": {"name": "BRAZIL_CPF_NUMBER"},
            "location": {"codepoint_range": {"start": 0, "end": len(text)}},
        }]})
        client = AsyncMock()
        client.inspect_content.return_value = response
        with patch("governanca.server.sensitive_data_protection._client", return_value=client):
            self.assertEqual(await inspect_sensitive_data(text), ())

    async def test_missing_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(InspectionUnavailable):
                await inspect_sensitive_data("synthetic text")

    async def test_remote_api_failure_has_safe_error(self):
        client = AsyncMock()
        client.inspect_content.side_effect = RuntimeError("synthetic failure with sensitive data")
        with patch("governanca.server.sensitive_data_protection._client", return_value=client):
            with self.assertRaisesRegex(InspectionUnavailable, "inspection failed"):
                await inspect_sensitive_data("synthetic text")

    async def test_invalid_range_fails_closed(self):
        response = dlp_v2.types.InspectContentResponse(result={"findings": [{
            "info_type": {"name": "EMAIL_ADDRESS"},
            "location": {"codepoint_range": {"start": 2, "end": 20}},
        }]})
        client = AsyncMock()
        client.inspect_content.return_value = response
        with patch("governanca.server.sensitive_data_protection._client", return_value=client):
            with self.assertRaisesRegex(InspectionUnavailable, "invalid text range"):
                await inspect_sensitive_data("short")

    def test_client_uses_regional_endpoint(self):
        with patch("governanca.server.sensitive_data_protection.dlp_v2.DlpServiceAsyncClient") as factory:
            _client.cache_clear()
            _client("southamerica-east1")
            self.assertEqual(factory.call_args.kwargs["client_options"].api_endpoint,
                             "dlp.southamerica-east1.rep.googleapis.com")
            _client.cache_clear()


if __name__ == "__main__":
    unittest.main()

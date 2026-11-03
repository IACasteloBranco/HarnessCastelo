import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI

from backend.internal_auth import EmployeeInfo
from governanca.server.data_protection import Category, Finding
from governanca.server.sensitive_data_protection import InspectionUnavailable
from governanca.server import inspection
from gateway.internal_auth import EXTENSION_ORIGIN, extension_employee, router


class GovernanceInspectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[extension_employee] = lambda: EmployeeInfo(
            uuid4(), "synthetic", "org", "dept", "collaborator", False
        )
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://app.test")
        self.inspection = patch.object(inspection, "inspect_sensitive_data", new_callable=AsyncMock,
                                       return_value=())
        self.remote_inspection = self.inspection.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.inspection.stop()

    async def test_masks_personal_data_and_allows_cnpj(self):
        response = await self.client.post("/api/auth/extension/inspect", headers={"Origin": EXTENSION_ORIGIN}, json={
            "text": "CPF 123.456.789-09; e-mail ana@example.invalid; telefone (11) 91234-5678; CNPJ 11.222.333/0001-81"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "action": "mask", "text": "CPF [CPF_1]; e-mail [EMAIL_1]; telefone [PHONE_1]; CNPJ 11.222.333/0001-81",
            "requires_confirmation": True, "policy_version": "governanca-2",
            "categories": ["CNPJ", "CPF", "EMAIL", "PHONE"],
        })

    async def test_clean_and_cnpj_only_text_needs_no_confirmation(self):
        for text in ("texto sem identificadores", "CNPJ 11.222.333/0001-81"):
            with self.subTest(text=text):
                response = await self.client.post("/api/auth/extension/inspect",
                    headers={"Origin": EXTENSION_ORIGIN}, json={"text": text})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["action"], "allow")
                self.assertFalse(response.json()["requires_confirmation"])
                self.assertIsNone(response.json()["text"])

    async def test_rejects_wrong_origin_and_oversized_text(self):
        path = "/api/auth/extension/inspect"
        self.assertEqual((await self.client.post(path, headers={"Origin": "https://evil.test"},
            json={"text": "sem dados"})).status_code, 403)
        self.assertEqual((await self.client.post(path, headers={"Origin": EXTENSION_ORIGIN},
            json={"text": "x" * 100_001})).status_code, 422)

    async def test_merges_remote_findings_and_preserves_unicode_offsets(self):
        text = "Olá 😀, contato ana@example.invalid"
        start = text.index("ana@example.invalid")
        self.remote_inspection.return_value = (Finding(Category.EMAIL, start, len(text)),)
        response = await self.client.post("/api/auth/extension/inspect",
            headers={"Origin": EXTENSION_ORIGIN}, json={"text": text})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Olá 😀, contato [EMAIL_1]")
        self.assertEqual(self.remote_inspection.await_args.args, (text,))

    async def test_masks_contextual_person_name_from_remote_detector(self):
        text = "Meu nome é Ana Silva"
        self.remote_inspection.return_value = (Finding(Category.PERSON_NAME, 11, 20),)
        response = await self.client.post("/api/auth/extension/inspect",
            headers={"Origin": EXTENSION_ORIGIN}, json={"text": text})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Meu nome é [PERSON_NAME_1]")
        self.assertIn("PERSON_NAME", response.json()["categories"])

    async def test_masks_sensitive_client_trait_from_remote_detector(self):
        text = "Cliente com diabetes"
        self.remote_inspection.return_value = (Finding(Category.MEDICAL_DATA, 12, 20),)
        response = await self.client.post("/api/auth/extension/inspect",
            headers={"Origin": EXTENSION_ORIGIN}, json={"text": text})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Cliente com [MEDICAL_DATA_1]")

    async def test_remote_failure_fails_closed(self):
        self.remote_inspection.side_effect = InspectionUnavailable("synthetic failure")
        response = await self.client.post("/api/auth/extension/inspect",
            headers={"Origin": EXTENSION_ORIGIN}, json={"text": "contato ana@example.invalid"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("ana@example.invalid", response.text)


if __name__ == "__main__":
    unittest.main()

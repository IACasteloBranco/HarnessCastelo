import unittest
from uuid import uuid4

import httpx
from fastapi import FastAPI

from backend.internal_auth import EmployeeInfo
from gateway.internal_auth import EXTENSION_ORIGIN, extension_employee, router


class GovernanceInspectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[extension_employee] = lambda: EmployeeInfo(
            uuid4(), "synthetic", "org", "dept", "collaborator", False
        )
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://app.test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_masks_personal_data_and_allows_cnpj(self):
        response = await self.client.post("/api/auth/extension/inspect", headers={"Origin": EXTENSION_ORIGIN}, json={
            "text": "CPF 123.456.789-09; e-mail ana@example.invalid; telefone (11) 91234-5678; CNPJ 11.222.333/0001-81"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "action": "mask", "text": "CPF [CPF_1]; e-mail [EMAIL_1]; telefone [PHONE_1]; CNPJ 11.222.333/0001-81",
            "requires_confirmation": True, "policy_version": "governanca-1",
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


if __name__ == "__main__":
    unittest.main()

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from maximus.department_analysis import AnalysisUnavailable, aggregate_analysis
from backend.internal_auth import EmployeeInfo
from gateway.chat import governance_router
from gateway.internal_auth import current_employee


class AnalysisShapeTests(unittest.TestCase):
    def test_only_approved_categories_and_counts_leave_the_server(self):
        raw = json.dumps({"items": [
            {"index": index, "category": "procedures", "relevant": True,
             "possible_incident": index == 0, "raw_text": "Cliente Identificável"}
            for index in range(5)]})
        report, incident = aggregate_analysis(raw, 5, "FISCAL", 30)
        self.assertTrue(incident)
        self.assertEqual(report["themes"], [{"theme": "Dúvidas sobre procedimentos", "interactions": 5}])
        self.assertNotIn("Cliente Identificável", json.dumps(report))
        with self.assertRaises(AnalysisUnavailable):
            aggregate_analysis(raw.replace('"index": 4', '"index": 0'), 5, "FISCAL", 30)


class AnalysisRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_auditor_receives_only_aggregate_response(self):
        application = FastAPI()
        application.include_router(governance_router)
        employee = EmployeeInfo(uuid4(), "AUDITOR", "ORG", "RH", "auditor", False)
        application.dependency_overrides[current_employee] = lambda: employee
        samples = [("same-employee", f"Cliente privado {index}") for index in range(5)]
        model_text = json.dumps({"items": [
            {"index": index, "category": "training", "relevant": True,
             "possible_incident": index == 0} for index in range(5)]})
        async def stream():
            yield b"event: response.completed\n\n"
        with patch.dict(os.environ, {"GOVERNANCE_ANALYSIS_CREDENTIAL_ID": "shared"}), \
             patch("gateway.chat.department_samples", new_callable=AsyncMock, return_value=samples), \
             patch("gateway.chat.require_department_access", new_callable=AsyncMock), \
             patch("gateway.chat.admit_employee", new_callable=AsyncMock,
                   return_value=SimpleNamespace(run_id=uuid4())), \
             patch("gateway.chat.forward", new_callable=AsyncMock,
                   return_value=StreamingResponse(stream(), status_code=200)), \
             patch("gateway.chat.suggested_title_response", new_callable=AsyncMock,
                   return_value=model_text), \
             patch("gateway.chat.notify_possible_incident", new_callable=AsyncMock) as notify:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                         base_url="https://app.test") as client:
                response = await client.post("/api/governance/departments/analyze",
                    headers={"Origin": "https://app.test"},
                    json={"department_code": "FISCAL", "question": "Quais dificuldades aparecem?"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["themes"], [
            {"theme": "Necessidade de capacitação", "interactions": 5}])
        self.assertNotIn("Cliente privado", response.text)
        notify.assert_awaited_once()

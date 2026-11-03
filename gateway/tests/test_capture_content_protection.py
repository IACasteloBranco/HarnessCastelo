import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx

from backend.capture_app.db import connect, initialize
from backend.capture_app.integration import capture_app
from backend.capture_app.main import app as legacy_capture_app
from backend.capture_app.machine_identity import require_machine_signature
from backend.capture_app.settings import Settings, get_settings
from governanca.server.inspection import protect_stored_text
from governanca.server.sensitive_data_protection import InspectionUnavailable
from governanca.server import inspection


class CaptureContentProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(_env_file=None, app_env="local", database_url=None,
                                 database_path=Path(self.temp.name) / "capture.sqlite3")
        initialize(self.settings)
        self.inspection = patch.object(inspection, "inspect_sensitive_data", new_callable=AsyncMock,
                                       return_value=())
        self.inspect_mock = self.inspection.start()
        self.capture = capture_app(protect_content=protect_stored_text)
        self.previous_overrides = legacy_capture_app.dependency_overrides.copy()
        legacy_capture_app.dependency_overrides[require_machine_signature] = lambda: None
        legacy_capture_app.dependency_overrides[get_settings] = lambda: self.settings
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.capture),
                                        base_url="https://capture.test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.inspection.stop()
        legacy_capture_app.dependency_overrides.clear()
        legacy_capture_app.dependency_overrides.update(self.previous_overrides)
        self.temp.cleanup()

    def interaction_body(self, text: str) -> dict:
        return {
            "schema_version": "0.1",
            "client_event_id": str(uuid4()),
            "platform": "chatgpt_web",
            "device_installation_id": str(uuid4()),
            "project": {"capture_status": "unknown", "reason": "synthetic test"},
            "conversation": {"capture_status": "unknown", "reason": "synthetic test"},
            "prompt": {"text": text, "capture_status": "observed"},
            "attachments": [],
            "attachments_capture_status": "not_observed",
            "attachments_truncated": False,
            "adapter_version": "test",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_prompt_and_response_are_protected_before_database_insert(self):
        prompt = "Please review CPF 123.456.789-09"
        created = await self.client.post("/v1/interactions", json=self.interaction_body(prompt))
        self.assertEqual(created.status_code, 201, created.text)
        interaction_id = created.json()["interaction_id"]
        response_text = "The result includes CPF 123.456.789-09"
        response = await self.client.post(f"/v1/interactions/{interaction_id}/response", json={
            "client_event_id": str(uuid4()), "text": response_text, "capture_status": "complete",
            "observed_at": datetime.now(timezone.utc).isoformat(), "adapter_version": "test",
        })
        self.assertEqual(response.status_code, 201, response.text)

        with connect(self.settings) as db:
            stored_prompt = json.loads(db.execute(
                "SELECT prompt_json FROM interactions WHERE interaction_id = ?", (interaction_id,)
            ).fetchone()["prompt_json"])["text"]
            stored_response = db.execute(
                "SELECT text FROM responses WHERE interaction_id = ?", (interaction_id,)
            ).fetchone()["text"]
        self.assertEqual(stored_prompt, "Please review CPF [CPF_1]")
        self.assertEqual(stored_response, "The result includes CPF [CPF_1]")

    async def test_missing_storage_inspector_fails_closed(self):
        self.capture.state.protect_content = None
        response = await self.client.post("/v1/interactions", json=self.interaction_body("synthetic prompt"))
        self.assertEqual(response.status_code, 503)
        with connect(self.settings) as db:
            self.assertEqual(db.execute("SELECT count(*) AS count FROM interactions").fetchone()["count"], 0)

    async def test_unknown_interaction_is_rejected_before_inspection(self):
        response = await self.client.post(f"/v1/interactions/{uuid4()}/response", json={
            "client_event_id": str(uuid4()), "text": "synthetic response", "capture_status": "complete",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        })
        self.assertEqual(response.status_code, 404)
        self.inspect_mock.assert_not_awaited()

    async def test_inspection_failure_fails_closed_without_storing_response(self):
        created = await self.client.post(
            "/v1/interactions", json=self.interaction_body("synthetic prompt"))
        self.assertEqual(created.status_code, 201, created.text)

        self.inspect_mock.side_effect = InspectionUnavailable("synthetic failure")
        response = await self.client.post(
            f"/v1/interactions/{created.json()['interaction_id']}/response", json={
                "client_event_id": str(uuid4()), "text": "synthetic response",
                "capture_status": "complete", "observed_at": datetime.now(timezone.utc).isoformat(),
            })
        self.assertEqual(response.status_code, 503)
        with connect(self.settings) as db:
            self.assertEqual(db.execute("SELECT count(*) AS count FROM responses").fetchone()["count"], 0)


if __name__ == "__main__":
    unittest.main()

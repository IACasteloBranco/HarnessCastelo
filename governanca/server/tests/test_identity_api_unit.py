import unittest
import tempfile
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from governanca.server.data_protection import Category
from governanca.server.identity import api
from governanca.server.identity.auth import EmployeeInfo


class GovernancePasswordResetApiTests(unittest.IsolatedAsyncioTestCase):
    def _app(self, actor):
        app = FastAPI()
        app.include_router(api.router)

        async def current_employee():
            return actor

        app.dependency_overrides[api.current_employee] = current_employee
        return app

    async def test_governance_reset_returns_nocache_temporary_password(self):
        actor = EmployeeInfo(uuid4(), "GOV1", "ORG1", None, "governance", False)
        app = self._app(actor)
        with patch.object(api, "reset_password", new_callable=AsyncMock) as reset:
            reset.return_value = "temporary-secret"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
            ) as client:
                response = await client.post(
                    "/api/auth/governance/accounts/reset-password",
                    headers={"Origin": "https://governanca.test"},
                    json={"employee_code": "EMP1"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json(), {
            "employee_code": "EMP1",
            "temporary_password": "temporary-secret",
            "must_change_password": True,
        })
        reset.assert_awaited_once_with("EMP1", organization_code="ORG1", role="collaborator")

    async def test_non_governance_cannot_reset_a_collaborators_password(self):
        actor = EmployeeInfo(uuid4(), "EMP2", "ORG1", "FIN", "collaborator", False)
        app = self._app(actor)
        with patch.object(api, "reset_password", new_callable=AsyncMock) as reset:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
            ) as client:
                response = await client.post(
                    "/api/auth/governance/accounts/reset-password",
                    headers={"Origin": "https://governanca.test"},
                    json={"employee_code": "EMP1"},
                )

        self.assertEqual(response.status_code, 403)
        reset.assert_not_awaited()

    async def test_governance_can_read_backup_status_without_exposing_file_path(self):
        actor = EmployeeInfo(uuid4(), "GOV1", "ORG1", None, "governance", False)
        app = self._app(actor)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "last-success"
            marker.write_text(datetime.now(timezone.utc).isoformat())
            with patch.dict("os.environ", {"GOVERNANCA_BACKUP_STATUS_FILE": str(marker)}):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
                ) as client:
                    response = await client.get("/api/auth/governance/backup-status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(set(response.json()), {"state", "last_success_at"})
        self.assertEqual(response.json()["state"], "fresh")

    async def test_only_governance_can_read_backup_status_or_policy_catalog(self):
        actor = EmployeeInfo(uuid4(), "EMP2", "ORG1", "FIN", "collaborator", False)
        app = self._app(actor)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
        ) as client:
            backup = await client.get("/api/auth/governance/backup-status")
            policies = await client.get("/api/auth/governance/policies")

        self.assertEqual(backup.status_code, 403)
        self.assertEqual(policies.status_code, 403)

    async def test_governance_policy_catalog_uses_server_policy_and_extension_rules(self):
        actor = EmployeeInfo(uuid4(), "GOV1", "ORG1", None, "governance", False)
        app = self._app(actor)
        with patch.object(api, "policy_for_organization", new_callable=AsyncMock,
                          return_value={"version": 3, "actions": {"R01": "BLOCK"}}), \
             patch.object(api, "server_policy_for_organization", new_callable=AsyncMock,
                          return_value={"version": 3, "actions": {
                              category.value: "allow" if category.value == "CNPJ" else "mask"
                              for category in Category
                          }}):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
            ) as client:
                response = await client.get("/api/auth/governance/policies")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        data = response.json()
        self.assertEqual(data["extension"]["policy_version"], 3)
        self.assertEqual(data["extension"]["configured_actions"]["R01"], "BLOCK")
        self.assertEqual(data["extension"]["destination"], "not_approved")
        self.assertEqual(data["extension"]["warning_rules"], ["R05", "R06"])
        self.assertEqual(data["server_inspection"]["version"], "governanca-2")
        self.assertEqual(next(item["action"] for item in data["server_inspection"]["categories"]
                              if item["name"] == "CNPJ"), "allow")

    async def test_governance_policy_update_is_audited_and_requires_current_version(self):
        actor = EmployeeInfo(uuid4(), "GOV1", "ORG1", None, "governance", False)
        app = self._app(actor)
        actions = {f"R{number:02}": None for number in range(1, 10)}
        actions["R08"] = "ALLOW"
        with patch.object(api, "save_policy", new_callable=AsyncMock,
                          return_value={"version": 1, "actions": actions}) as save:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
            ) as client:
                response = await client.put("/api/auth/governance/policies",
                    headers={"Origin": "https://governanca.test"},
                    json={"expected_version": 0, "actions": actions})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 1)
        save.assert_awaited_once_with("ORG1", actor.employee_id, 0, actions, None)

    async def test_non_governance_cannot_edit_policy_and_invalid_rules_are_rejected(self):
        actor = EmployeeInfo(uuid4(), "EMP2", "ORG1", "FIN", "collaborator", False)
        app = self._app(actor)
        actions = {f"R{number:02}": None for number in range(1, 10)}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
        ) as client:
            forbidden = await client.put("/api/auth/governance/policies",
                headers={"Origin": "https://governanca.test"},
                json={"expected_version": 0, "actions": actions})
        self.assertEqual(forbidden.status_code, 403)

        actor = EmployeeInfo(uuid4(), "GOV1", "ORG1", None, "governance", False)
        app = self._app(actor)
        actions["LIMIT"] = "ALLOW"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
        ) as client:
            invalid = await client.put("/api/auth/governance/policies",
                headers={"Origin": "https://governanca.test"},
                json={"expected_version": 0, "actions": actions})
        self.assertEqual(invalid.status_code, 422)

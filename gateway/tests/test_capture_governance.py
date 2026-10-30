import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi.routing import APIRoute
from sqlalchemy import delete, select

from backend.capture_app.analytics import router as analytics_router
from backend.capture_app.db import connect, initialize, iso
from backend.capture_app.integration import CAPTURE_PATHS, capture_app
from backend.capture_app.main import app as legacy_capture_app
from backend.capture_app.settings import get_settings
from backend.database import Department, Employee, InternalSession, Organization, _session_factory, session_factory
from backend.internal_auth import provision_department, provision_employee, provision_organization
from gateway.main import app


class CaptureRouteMountingTests(unittest.TestCase):
    def test_analytics_router_is_canonical_when_legacy_route_conflicts(self):
        analytics_route = next(route for route in analytics_router.routes
                               if isinstance(route, APIRoute)
                               and route.path == "/v1/admin/analytics/interactions")
        conflicting_route = APIRoute(analytics_route.path, lambda: None,
                                     methods=analytics_route.methods)
        with patch.object(legacy_capture_app.router, "routes",
                          [conflicting_route, *legacy_capture_app.router.routes]):
            routes = [route for route in capture_app().router.routes
                      if isinstance(route, APIRoute)
                      and route.path == analytics_route.path
                      and route.methods == analytics_route.methods]
        self.assertEqual(len(routes), 1)
        self.assertIs(routes[0].endpoint, analytics_route.endpoint)


@unittest.skipUnless(os.environ.get("HARNESS_TEST_DATABASE_URL"), "requires a disposable PostgreSQL database")
class CaptureGovernanceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        _session_factory.cache_clear()
        get_settings.cache_clear()

    async def asyncSetUp(self):
        self.previous_capture_ready = app.state.capture_store_ready
        app.state.capture_store_ready = True
        initialize(get_settings())
        self.org = f"org-{uuid4().hex}"
        self.department = f"dept-{uuid4().hex}"
        self.other_department = f"dept-{uuid4().hex}"
        self.viewer = f"viewer-{uuid4().hex}"
        self.denied = f"denied-{uuid4().hex}"
        self.other_employee = f"other-{uuid4().hex}"
        self.interaction_ids = [str(uuid4()) for _ in range(4)]
        await provision_organization(self.org, "Synthetic capture test")
        await provision_department(self.org, self.department, "Synthetic department")
        await provision_department(self.org, self.other_department, "Other synthetic department")
        self.viewer_password = await provision_employee(self.org, self.viewer, "collaborator", self.department)
        self.denied_password = await provision_employee(self.org, self.denied, "collaborator", self.department)
        self.other_password = await provision_employee(self.org, self.other_employee, "collaborator", self.other_department)
        async with session_factory()() as session, session.begin():
            viewer = await session.scalar(select(Employee).where(Employee.code == self.viewer))
            self.assertIsNotNone(viewer)
            if viewer is None:
                self.fail("synthetic governance viewer was not provisioned")
            viewer.can_govern = True
        self.clients = {
            name: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.test")
            for name in ("anonymous", "viewer", "denied")
        }
        for name, code, password in (
            ("viewer", self.viewer, self.viewer_password),
            ("denied", self.denied, self.denied_password),
        ):
            client = self.clients[name]
            headers = {"Origin": "https://app.test"}
            response = await client.post("/api/auth/login", json={
                "employee_code": code, "password": password}, headers=headers)
            self.assertEqual(response.status_code, 200)
            response = await client.post("/api/auth/change-password", json={
                "current_password": password, "new_password": "new test password 123"}, headers=headers)
            self.assertEqual(response.status_code, 200)
        self._seed_synthetic_interactions()

    def _seed_synthetic_interactions(self):
        timestamp = iso(datetime(2026, 10, 30, 12, tzinfo=timezone.utc))
        records = (
            (self.interaction_ids[0], self.viewer, self.department, "chatgpt_web"),
            (self.interaction_ids[1], self.viewer, self.department, "chatgpt_web"),
            (self.interaction_ids[2], self.viewer, self.department, "claude_web"),
            (self.interaction_ids[3], self.other_employee, self.other_department, "chatgpt_web"),
        )
        with connect(get_settings()) as db:
            for interaction_id, employee_id, department_code, platform in records:
                db.execute(
                    """INSERT INTO interactions (
                        interaction_id, client_event_id, request_fingerprint, device_installation_id,
                        platform, project_json, conversation_json, prompt_json, attachments_json,
                        adapter_version, status, observed_at, received_at, employee_id, department_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (interaction_id, str(uuid4()), "synthetic-test-fingerprint", str(uuid4()), platform,
                     json.dumps({}), json.dumps({}), json.dumps({"text": "synthetic prompt", "capture_status": "observed"}),
                     json.dumps([]), "test", "complete", timestamp, timestamp, employee_id, department_code),
                )
                db.execute(
                    """INSERT INTO responses (
                        response_id, interaction_id, client_event_id, request_fingerprint, text,
                        capture_status, observed_at, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid4()), interaction_id, str(uuid4()), "synthetic-response-fingerprint",
                     "synthetic response", "complete", timestamp, timestamp),
                )

    async def asyncTearDown(self):
        for client in getattr(self, "clients", {}).values():
            await client.aclose()
        if hasattr(self, "interaction_ids"):
            with connect(get_settings()) as db:
                db.execute("DELETE FROM privacy_audit WHERE actor_id IN (?, ?)", (self.viewer, self.denied))
                db.execute("DELETE FROM interactions WHERE interaction_id IN (?, ?, ?, ?)", self.interaction_ids)
        if hasattr(self, "org"):
            async with session_factory()() as session, session.begin():
                org_id = await session.scalar(select(Organization.id).where(Organization.code == self.org))
                employee_ids = select(Employee.id).where(Employee.organization_id == org_id)
                await session.execute(delete(InternalSession).where(InternalSession.employee_id.in_(employee_ids)))
                await session.execute(delete(Employee).where(Employee.organization_id == org_id))
                await session.execute(delete(Department).where(Department.organization_id == org_id))
                await session.execute(delete(Organization).where(Organization.id == org_id))
        app.state.capture_store_ready = self.previous_capture_ready

    async def _login_routes_allowlist_and_deduplication(self):
        routes = [route for route in capture_app().router.routes if isinstance(route, APIRoute)]
        keys = [(route.path, frozenset(getattr(route, "methods", ()))) for route in routes]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(route.path in CAPTURE_PATHS for route in routes))
        self.assertIn(("/v1/admin/analytics/summary", frozenset({"GET"})), keys)
        self.assertIn(("/v1/admin/analytics/interactions", frozenset({"GET"})), keys)

    async def test_governance_capture_access_is_scoped_and_audited(self):
        await self._login_routes_allowlist_and_deduplication()
        anonymous = await self.clients["anonymous"].get(
            "/api/capture/v1/admin/analytics/interactions")
        self.assertEqual(anonymous.status_code, 401)
        denied = await self.clients["denied"].get(
            "/api/capture/v1/admin/analytics/interactions")
        self.assertEqual(denied.status_code, 403)

        client = self.clients["viewer"]
        summary = await client.get("/api/capture/v1/admin/analytics/summary")
        self.assertEqual(summary.status_code, 200, summary.text)
        params = {
            "employee_id": self.viewer,
            "platform": "chatgpt_web",
            "from": "2026-10-30T00:00:00Z",
            "to": "2026-10-31T00:00:00Z",
            "limit": 1,
            "offset": 0,
        }
        first = await client.get("/api/capture/v1/admin/analytics/interactions", params=params)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["total"], 2)
        self.assertEqual(len(first.json()["items"]), 1)
        self.assertEqual(first.json()["items"][0]["platform"], "chatgpt_web")
        self.assertNotIn("prompt", first.json()["items"][0])
        self.assertNotIn("response", first.json()["items"][0])
        params["offset"] = 1
        second = await client.get("/api/capture/v1/admin/analytics/interactions", params=params)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(first.json()["items"][0]["interaction_id"], second.json()["items"][0]["interaction_id"])

        with connect(get_settings()) as db:
            list_audit = db.execute(
                """SELECT event_type, record_count FROM privacy_audit
                   WHERE actor_id = ? AND action = ? ORDER BY audit_id DESC LIMIT 1""",
                (self.viewer, "GET /v1/admin/analytics/interactions"),
            ).fetchone()
        self.assertIsNotNone(list_audit)
        self.assertEqual((list_audit["event_type"], list_audit["record_count"]), ("content_read", 1))

        detail = await client.get(f"/api/capture/v1/interactions/{self.interaction_ids[0]}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["prompt"]["text"], "synthetic prompt")
        self.assertEqual(detail.json()["responses"][0]["text"], "synthetic response")
        out_of_scope = await client.get(f"/api/capture/v1/interactions/{self.interaction_ids[3]}")
        self.assertEqual(out_of_scope.status_code, 404)

        with connect(get_settings()) as db:
            audit = db.execute(
                """SELECT event_type, action, record_count FROM privacy_audit
                   WHERE actor_id = ? AND action = ? ORDER BY audit_id DESC LIMIT 1""",
                (self.viewer, "GET /v1/interactions/{interaction_id}"),
            ).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual((audit["event_type"], audit["record_count"]), ("content_read", 1))

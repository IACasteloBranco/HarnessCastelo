import unittest
from unittest.mock import patch
from uuid import uuid4

from governanca.server.identity import investigations
from governanca.server.identity.models import Employee, GovernanceInvestigation


class Session:
    def __init__(self, actors, subject):
        self.actors = actors
        self.subject = subject
        self.case = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def begin(self):
        return self

    async def get(self, model, key):
        if model is Employee:
            return self.actors.get(key)
        if model is GovernanceInvestigation and self.case and self.case.id == key:
            return self.case
        return None

    async def scalar(self, _query):
        return self.subject

    def add(self, case):
        self.case = case


class InvestigationWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_is_recorded_and_grants_only_requester_one_hour_access(self):
        actor_id = uuid4()
        other_id = uuid4()
        organization_id = uuid4()
        actor = Employee(id=actor_id, organization_id=organization_id, code="GOV1",
                         role="governance", disabled=False, must_change_password=False)
        other = Employee(id=other_id, organization_id=organization_id, code="GOV2",
                         role="governance", disabled=False, must_change_password=False)
        subject = Employee(id=uuid4(), organization_id=organization_id, code="EMP1")
        session = Session({actor_id: actor, other_id: other}, subject)

        with patch.object(investigations, "session_factory", return_value=lambda: session):
            result = await investigations.request_investigation(
                actor_id, "Review of a reported interaction", "EMP1")
            await investigations.require_investigation(actor_id, result["id"], subject.id)
            with self.assertRaises(investigations.InvestigationDenied):
                await investigations.require_investigation(other_id, result["id"], subject.id)

        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["target_employee_code"], "EMP1")
        self.assertEqual(session.case.requested_by, actor_id)
        self.assertEqual(session.case.viewer_ids, [str(actor_id)])
        self.assertEqual(session.case.approved_by, actor_id)
        self.assertGreater(session.case.expires_at, session.case.created_at)


if __name__ == "__main__":
    unittest.main()

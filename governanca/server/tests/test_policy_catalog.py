import os
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select

from governanca.server.data_protection import Action, Category
from governanca.server.inspection import POLICY_VERSION, policy_configuration
from governanca.server.policy_catalog import EXTENSION_POLICY_VERSION, get_policy_catalog
from governanca.server.identity.database import session_factory
from governanca.server.identity.models import Employee, GovernancePolicyRevision, Organization


class PolicyCatalogTests(unittest.TestCase):
    def test_server_policy_catalog_matches_the_policy_used_for_inspection(self):
        config = policy_configuration()
        self.assertEqual(config["version"], POLICY_VERSION)
        self.assertEqual({item["name"] for item in config["categories"]},
                         {item.value for item in Category})
        self.assertEqual({item["action"] for item in config["categories"]},
                         {Action.ALLOW.value, Action.MASK.value})

    def test_extension_policy_catalog_tracks_the_engine_version_and_rule_ids(self):
        engine = Path(__file__).parents[2] / "extension" / "src" / "content" / "policy-engine.js"
        source = engine.read_text(encoding="utf-8")
        bridge = engine.with_name("blocker-bridge.js").read_text(encoding="utf-8")
        version = re.search(r"const VERSION = '([^']+)'", source).group(1)
        destination = re.search(r"const destination = '([^']+)'", bridge).group(1)
        rule_ids = set(re.findall(r"add\('(R\d{2}|LIMIT)'", source))
        catalog = get_policy_catalog()["extension"]
        self.assertEqual(version, EXTENSION_POLICY_VERSION)
        self.assertEqual({item["id"] for item in catalog["rules"]}, rule_ids)
        self.assertEqual(catalog["destination"], destination)
        self.assertEqual(catalog["decision_counts"], "local_only")


@unittest.skipUnless(os.environ.get("GOVERNANCA_DATABASE_URL"), "requires disposable Governance PostgreSQL")
class PolicyRevisionDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.organization_id = uuid4()
        self.employee_id = uuid4()
        self.organization_code = f"TEST-{uuid4().hex}"
        now = datetime.now(timezone.utc)
        async with session_factory()() as session, session.begin():
            session.add(Organization(id=self.organization_id, code=self.organization_code,
                name="synthetic governance test", created_at=now))
            await session.flush()
            session.add(Employee(id=self.employee_id, organization_id=self.organization_id,
                department_id=None, code=f"TEST-{uuid4().hex}", display_name="Test Governance",
                role="governance", password_hash="synthetic", must_change_password=False,
                disabled=False, failed_logins=0, locked_until=None, created_at=now))

    async def asyncTearDown(self):
        async with session_factory()() as session, session.begin():
            await session.execute(delete(GovernancePolicyRevision).where(
                GovernancePolicyRevision.organization_id == self.organization_id))
            await session.execute(delete(Employee).where(Employee.id == self.employee_id))
            await session.execute(delete(Organization).where(Organization.id == self.organization_id))

    async def test_policy_revision_is_persisted_and_stale_versions_are_rejected(self):
        from governanca.server.policy_catalog import EDITABLE_RULES, policy_for_organization, save_policy

        actions = {rule: None for rule in EDITABLE_RULES}
        actions["R08"] = "WARN"
        saved = await save_policy(self.organization_code, self.employee_id, 0, actions)
        current = await policy_for_organization(self.organization_code)
        self.assertEqual(saved, {"version": 1, "actions": actions})
        self.assertEqual(current, saved)
        with self.assertRaisesRegex(RuntimeError, "policy version conflict"):
            await save_policy(self.organization_code, self.employee_id, 0, actions)
        async with session_factory()() as session:
            revisions = (await session.scalars(select(GovernancePolicyRevision).where(
                GovernancePolicyRevision.organization_id == self.organization_id))).all()
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].changed_by, self.employee_id)


if __name__ == "__main__":
    unittest.main()

import unittest

from maximus.backend.governance_access import has_governance_access


class GovernanceAccessTests(unittest.TestCase):
    def test_role_and_grant(self):
        self.assertTrue(has_governance_access("governance"))
        self.assertFalse(has_governance_access("auditor"))
        self.assertFalse(has_governance_access("collaborator"))

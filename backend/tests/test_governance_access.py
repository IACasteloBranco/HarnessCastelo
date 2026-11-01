import unittest

from backend.governance_access import has_governance_access


class GovernanceAccessTests(unittest.TestCase):
    def test_role_and_grant(self):
        self.assertTrue(has_governance_access("governance", False))
        self.assertTrue(has_governance_access("governance", True))
        self.assertTrue(has_governance_access("collaborator", True))
        self.assertFalse(has_governance_access("collaborator", False))

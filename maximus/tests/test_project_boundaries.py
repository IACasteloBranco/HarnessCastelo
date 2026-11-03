import ast
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAXIMUS_ROOT = REPOSITORY_ROOT / "maximus"
GOVERNANCE_ROOT = REPOSITORY_ROOT / "governanca"


def imported_modules(root: Path) -> set[str]:
    modules = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
    return modules


class ProjectBoundaryTests(unittest.TestCase):
    def test_maximus_owns_its_runtime_roots_and_requirements(self):
        for path in ("backend", "gateway", "frontend", "requirements.txt"):
            with self.subTest(path=path):
                self.assertTrue((MAXIMUS_ROOT / path).exists(), f"missing maximus/{path}")

    def test_maximus_does_not_import_governance_or_legacy_root_packages(self):
        modules = imported_modules(MAXIMUS_ROOT)
        forbidden = {"backend", "gateway", "frontend", "governanca"}
        self.assertFalse(
            sorted(module for module in modules if module.split(".", 1)[0] in forbidden),
            "Maximus source must use its project root and shared contracts",
        )

    def test_governance_does_not_import_maximus_or_legacy_root_packages(self):
        modules = imported_modules(GOVERNANCE_ROOT / "server")
        forbidden = {"backend", "gateway", "maximus"}
        self.assertFalse(
            sorted(module for module in modules if module.split(".", 1)[0] in forbidden),
            "Governança must depend only on its root and shared contracts",
        )

    def test_each_project_owns_a_distinct_analytics_module(self):
        governance_analytics = GOVERNANCE_ROOT / "server" / "capture_app" / "analytics.py"
        maximus_analytics = MAXIMUS_ROOT / "department_analysis.py"
        self.assertTrue(governance_analytics.is_file())
        self.assertTrue(maximus_analytics.is_file())
        self.assertNotEqual(governance_analytics.resolve(), maximus_analytics.resolve())


if __name__ == "__main__":
    unittest.main()

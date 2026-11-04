import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DbtFixtureProfileTests(unittest.TestCase):
    def test_manifest_fixture_profile_is_shipped(self):
        project = (ROOT / "fixtures" / "dbt_project.yml").read_text()
        profile = (ROOT / "fixtures" / "profiles.yml").read_text()
        self.assertIn("profile: reconciliation_fixture", project)
        self.assertIn("reconciliation_fixture:", profile)
        self.assertIn("type: postgres", profile)
        self.assertIn("target: dev", profile)


if __name__ == "__main__":
    unittest.main()

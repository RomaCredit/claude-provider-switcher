import re
import unittest
from pathlib import Path

from claude_provider_switcher import __version__


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/RomaCredit/claude-provider-switcher"


class ReleaseMetadataTests(unittest.TestCase):
    def test_versioned_documentation_and_installers(self):
        for name in ("README.md", "README.zh-CN.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for version in re.findall(r"/(v[\d.]+)/install\.(?:sh|ps1)", text):
                self.assertEqual(version, "v" + __version__)
            for version in re.findall(r"/refs/tags/(v[\d.]+)\.zip", text):
                self.assertEqual(version, "v" + __version__)
            self.assertIn(REPOSITORY + "/releases", text)
            self.assertIn("https://github.com/RomaCredit/codex-provider-switcher", text)
            self.assertNotRegex(text, r"\]\((?:README[^)]*|LICENSE)\)")
        self.assertIn("README.zh-CN.md", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("README.md", (ROOT / "README.zh-CN.md").read_text(encoding="utf-8"))

    def test_release_metadata(self):
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn(f"version: {__version__}\n", citation)
        self.assertIn(REPOSITORY, citation)
        self.assertIn(f"## {__version__}\n", (ROOT / "CHANGELOG.md").read_text())
        metadata = (ROOT / "pyproject.toml").read_text()
        self.assertIn("dependencies = []", metadata)
        for keyword in ("claude-code", "anthropic-compatible", "provider-switcher"):
            self.assertIn(keyword, metadata)

    def test_community_and_publishing_resources(self):
        for name in ("CONTRIBUTING.md", "SECURITY.md", "RELEASE.md"):
            self.assertTrue((ROOT / name).is_file())
        for name in ("installation.yml", "provider.yml", "history.yml", "config.yml"):
            self.assertTrue((ROOT / ".github" / "ISSUE_TEMPLATE" / name).is_file())
        workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text()
        self.assertIn("id-token: write", workflow)
        self.assertIn("needs: test", workflow)
        self.assertNotIn("password:", workflow)

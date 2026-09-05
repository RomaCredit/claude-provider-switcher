import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from claude_provider_switcher import __version__


ROOT = Path(__file__).parents[1]


class PackageTests(unittest.TestCase):
    def test_versions_agree(self):
        self.assertIn(f'version = "{__version__}"', (ROOT / "pyproject.toml").read_text())
        self.assertIn(f":-v{__version__}", (ROOT / "install.sh").read_text())
        self.assertIn(f"'v{__version__}'", (ROOT / "install.ps1").read_text())


@unittest.skipUnless(os.name == "posix", "POSIX installer runs on Linux/macOS CI")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.archive = self.root / "fixture.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            for path in [ROOT / "ccs.py", *(ROOT / "claude_provider_switcher").glob("*.py")]:
                archive.write(path, f"claude-provider-switcher-{__version__}/{path.relative_to(ROOT).as_posix()}")
        for name in ("mktemp", "cp", "rm", "rmdir"):
            (self.tools / name).symlink_to(shutil.which(name))
        self.write_tool("python3", "exec " + shlex.quote(sys.executable) + ' "$@"')
        self.write_tool("id", "printf '1000\\n'")
        self.write_tool("curl", 'cp "$CCS_TEST_ZIP" "$4"')
        self.env = {
            **os.environ, "PATH": str(self.tools), "CCS_TEST_ZIP": str(self.archive),
            "CLAUDE_SWITCHER_VERSION": "v" + __version__,
            "CLAUDE_SWITCHER_BIN_DIR": str(self.root / "bin path"),
            "CLAUDE_SWITCHER_DATA_DIR": str(self.root / "data '$literal"),
        }

    def write_tool(self, name, body):
        path = self.tools / name
        path.write_text("#!/bin/sh\nset -eu\n" + body + "\n")
        path.chmod(0o755)

    def install(self):
        return subprocess.run(
            ["/bin/sh"], input=(ROOT / "install.sh").read_text(), env=self.env,
            capture_output=True, text=True, timeout=30,
        )

    def test_both_commands_reinstall_special_paths(self):
        for _ in range(2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("ccs", "claude-provider-switcher"):
                command = Path(self.env["CLAUDE_SWITCHER_BIN_DIR"]) / name
                check = subprocess.run([str(command), "--version"], capture_output=True, text=True, env=self.env)
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertIn(__version__, check.stdout)

    def test_bad_download_does_not_replace_command(self):
        self.assertEqual(self.install().returncode, 0)
        command = Path(self.env["CLAUDE_SWITCHER_BIN_DIR"]) / "ccs"
        previous = command.read_bytes()
        self.archive.write_bytes(b"not a zip")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(command.read_bytes(), previous)

    def test_no_overwrite_of_unrelated_ccs(self):
        command = Path(self.env["CLAUDE_SWITCHER_BIN_DIR"]) / "ccs"
        command.parent.mkdir()
        command.write_text("another tool")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(command.read_text(), "another tool")

    def test_old_python_rejected(self):
        self.write_tool("python3", "exit 1")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.10", result.stderr)

    def test_wget_fallback(self):
        (self.tools / "curl").unlink()
        self.write_tool("wget", 'cp "$CCS_TEST_ZIP" "$2"')
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_version_and_traversal(self):
        self.env["CLAUDE_SWITCHER_VERSION"] = "../main"
        self.assertNotEqual(self.install().returncode, 0)
        self.env["CLAUDE_SWITCHER_VERSION"] = "v9.9.9"
        self.assertNotEqual(self.install().returncode, 0)
        self.env["CLAUDE_SWITCHER_VERSION"] = "v" + __version__
        with zipfile.ZipFile(self.archive, "a") as archive:
            archive.writestr("../outside.py", "pass")
        self.assertNotEqual(self.install().returncode, 0)

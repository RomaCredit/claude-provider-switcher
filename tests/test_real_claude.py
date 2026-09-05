"""Opt-in local CLI integration. Uses only auth status, never inference."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_provider_switcher.core import Switcher, owned_env
from claude_provider_switcher.profiles import Profile
from claude_provider_switcher.storage import write_object


class FileOnlyVault:
    def set(self, *_):
        return False


@unittest.skipUnless(os.environ.get("CCS_TEST_REAL_CLAUDE") == "1", "Opt-in real Claude Code smoke test")
class RealClaudeTests(unittest.TestCase):
    def test_real_auth_status_with_both_auth_kinds_and_persistent_helper(self):
        executable = shutil.which("claude.cmd" if os.name == "nt" else "claude")
        self.assertIsNotNone(executable)
        with tempfile.TemporaryDirectory(prefix="ccs-real-") as directory:
            base = Path(directory)
            switcher = Switcher(base / "switcher", base / "claude", vault=FileOnlyVault())
            profiles = switcher.profiles.load()
            for kind, variable in (("api_key", "ANTHROPIC_API_KEY"), ("auth_token", "ANTHROPIC_AUTH_TOKEN")):
                profiles["local"] = Profile("api", "http://127.0.0.1:1", "test-model", kind)
                switcher.profiles.save(profiles)
                switcher.credentials.set("local", "sk-fake-local-no-network")
                write_object(switcher.settings_path, {
                    "apiKeyHelper": "ccs-test-helper-must-not-run",
                    "env": {
                        "ANTHROPIC_BASE_URL": "http://127.0.0.1:2",
                        "ANTHROPIC_API_KEY": "sk-stale-key",
                        "ANTHROPIC_AUTH_TOKEN": "sk-stale-token",
                    },
                })
                settings_before = switcher.settings_path.read_bytes()
                commands = []

                def call(args, env):
                    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
                    result = subprocess.run(args, env=env, cwd=base, capture_output=True, text=True, timeout=30)
                    commands.append(result)
                    return result.returncode

                with patch("claude_provider_switcher.core.subprocess.call", side_effect=call):
                    result = switcher.run("local", ["auth", "status", "--text"])
                self.assertEqual(result, 0, commands[0].stdout + commands[0].stderr)
                self.assertIn(variable, commands[0].stdout)
                self.assertIn("http://127.0.0.1:1", commands[0].stdout)
                self.assertNotIn("apiKeyHelper", commands[0].stdout)
                self.assertEqual(switcher.settings_path.read_bytes(), settings_before)
            switcher.use("local")
            env = {k: v for k, v in os.environ.items() if not owned_env(k)}
            env.update({"CLAUDE_CONFIG_DIR": str(switcher.claude_home), "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
            result = subprocess.run(
                [executable, "auth", "status", "--text"], env=env, cwd=base,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("apiKeyHelper", result.stdout)
            self.assertNotIn("sk-fake-local-no-network", result.stdout + result.stderr)

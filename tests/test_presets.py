import copy
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from claude_provider_switcher.cli import main
from claude_provider_switcher.core import Switcher
from claude_provider_switcher.probe import endpoint
from claude_provider_switcher.profiles import DEFAULTS, Profile, Profiles
from claude_provider_switcher.storage import SwitcherError, read_object, write_object


class FileOnlyVault:
    def set(self, *_):
        return False


class PresetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.switcher = Switcher(self.base / "switcher", self.base / "claude", FileOnlyVault())
        self.profiles = self.switcher.profiles

    def legacy(self, profiles):
        write_object(self.profiles.path, {"version": 1, "profiles": {
            name: {k: v for k, v in asdict(profile).items() if k != "env"}
            for name, profile in profiles.items()
        }})
        return self.profiles.path.read_bytes()

    def test_fresh_apimaster_is_preconfigured_without_a_credential(self):
        profile = self.profiles.get("apimaster")
        self.assertEqual(profile.base_url, "https://apimaster.ai")
        self.assertEqual(profile.model, "claude-sonnet-4-6")
        self.assertEqual(profile.auth_kind, "auth_token")
        self.assertEqual(endpoint(profile.base_url, "messages"), "https://apimaster.ai/v1/messages")
        self.assertEqual(profile.env, {
            "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        })
        self.assertFalse(self.switcher.credentials.path.exists())
        self.assertEqual(read_object(self.profiles.path)["version"], 2)

    def test_legacy_upgrade_backs_up_and_preserves_custom_profiles(self):
        custom = Profile("api", "https://example.com", "custom")
        before = self.legacy({"official": DEFAULTS["official"], "custom": custom})
        self.switcher.credentials.set("custom", "sk-fake-existing")
        credential_bytes = self.switcher.credentials.path.read_bytes()
        profiles = self.profiles.load()
        self.assertEqual(set(profiles), {"official", "custom", "apimaster"})
        self.assertEqual(profiles["custom"], custom)
        backups = list(self.profiles.root.glob("profiles-v1-*.backup.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(self.switcher.credentials.path.read_bytes(), credential_bytes)
        self.assertFalse(self.switcher.settings_path.exists())
        self.profiles.load()
        self.assertEqual(len(list(self.profiles.root.glob("profiles-v1-*.backup.json"))), 1)

    def test_custom_same_name_is_never_replaced(self):
        custom = Profile("api", "https://custom.example.com", "my-model")
        self.legacy({"apimaster": custom})
        self.assertEqual(self.profiles.get("apimaster"), custom)

    def test_migration_does_not_restore_other_removed_presets(self):
        self.legacy({})
        self.assertEqual(set(self.profiles.load()), {"apimaster"})
        self.profiles.save({})
        self.assertEqual(Profiles(self.profiles.root).load(), {})

    def test_deleted_or_edited_new_preset_stays_that_way(self):
        profiles = self.profiles.load()
        profiles["apimaster"] = Profile("api", "https://example.com", "custom", "api_key")
        self.profiles.save(profiles)
        self.assertEqual(self.profiles.get("apimaster"), profiles["apimaster"])
        del profiles["apimaster"]
        self.profiles.save(profiles)
        self.assertNotIn("apimaster", Profiles(self.profiles.root).load())

    def test_invalid_legacy_file_is_not_migrated(self):
        for invalid in ({"type": "api", "api_key": "sk-fake"}, {"type": "api"}, {"type": "subscription", "env": {"ANTHROPIC_API_KEY": "sk-fake"}}):
            write_object(self.profiles.path, {"version": 1, "profiles": {"bad": invalid}})
            before = self.profiles.path.read_bytes()
            with self.assertRaises(SwitcherError):
                self.profiles.load()
            self.assertEqual(self.profiles.path.read_bytes(), before)
            self.assertEqual(list(self.profiles.root.glob("*.backup.json")), [])

    def test_failed_migration_preserves_original_and_backup(self):
        before = self.legacy({"official": DEFAULTS["official"]})
        with patch.object(self.profiles, "save", side_effect=OSError("write failed")), self.assertRaises(OSError):
            self.profiles.load()
        self.assertEqual(self.profiles.path.read_bytes(), before)
        self.assertEqual(next(self.profiles.root.glob("*.backup.json")).read_bytes(), before)
        self.assertFalse((self.profiles.root / ".ccs.lock").exists())

    def test_env_validation_disallows_credentials_and_other_settings(self):
        for env in ([], {"ANTHROPIC_AUTH_TOKEN": "sk-fake"}, {"NODE_OPTIONS": "--require=bad"}, {"CLAUDE_CODE_ATTRIBUTION_HEADER": "secret"}, {"CLAUDE_CODE_ATTRIBUTION_HEADER": 0}):
            with self.subTest(env=env), self.assertRaises(SwitcherError):
                Profile("api", "https://example.com", "model", env=env).validate()
        with self.assertRaises(SwitcherError):
            Profile("subscription", env={"CLAUDE_CODE_ATTRIBUTION_HEADER": "0"}).validate()

    def test_compatibility_flags_follow_profile_not_its_name(self):
        profiles = self.profiles.load()
        profiles["renamed"] = copy.deepcopy(profiles["apimaster"])
        self.profiles.save(profiles)
        self.switcher.credentials.set("renamed", "sk-fake-test")
        self.switcher.use("renamed")
        env = read_object(self.switcher.settings_path)["env"]
        self.assertEqual(env["CLAUDE_CODE_ATTRIBUTION_HEADER"], "0")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"], "1")
        self.assertNotIn("sk-fake-test", self.switcher.settings_path.read_text())
        self.switcher.use("official")
        self.assertNotIn("env", read_object(self.switcher.settings_path))

    def test_run_clears_inherited_flags_and_supplies_selected_ones(self):
        self.profiles.load()
        self.switcher.credentials.set("apimaster", "sk-fake-test")
        captured = {}

        def call(command, env):
            captured["settings"] = read_object(Path(command[command.index("--settings") + 1]))
            captured["env"] = env
            return 0

        with patch.dict(os.environ, {"CLAUDE_CODE_ATTRIBUTION_HEADER": "1"}), patch("shutil.which", return_value="claude"), patch("subprocess.call", side_effect=call):
            self.assertEqual(self.switcher.run("apimaster", ["--version"]), 0)
        self.assertEqual(captured["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-fake-test")
        self.assertNotIn("CLAUDE_CODE_ATTRIBUTION_HEADER", captured["env"])
        self.assertEqual(captured["settings"]["env"]["CLAUDE_CODE_ATTRIBUTION_HEADER"], "0")
        self.assertFalse(self.switcher.settings_path.exists())

    def test_menu_first_switch_prompts_only_for_key_then_reuses_it(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("claude_provider_switcher.cli.Switcher", return_value=self.switcher), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["1", "3", "0"]), patch("getpass.getpass", return_value="sk-fake-menu-key") as prompt, redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(["menu"]), 0)
        prompt.assert_called_once()
        self.assertIn("3. apimaster", output.getvalue())
        self.assertEqual(errors.getvalue(), "")
        self.assertNotIn("sk-fake-menu-key", output.getvalue())
        self.assertEqual(self.switcher.status()["configured_profile"], "apimaster")
        with patch("claude_provider_switcher.cli.Switcher", return_value=self.switcher), patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", side_effect=AssertionError("Must reuse saved credential")), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["use", "apimaster"]), 0)

    def test_noninteractive_switch_without_key_is_safe(self):
        with patch("claude_provider_switcher.cli.Switcher", return_value=self.switcher), patch("sys.stdin", io.StringIO()), patch("getpass.getpass", side_effect=AssertionError("Must not prompt")), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["use", "apimaster"]), 1)
        self.assertFalse(self.switcher.settings_path.exists())

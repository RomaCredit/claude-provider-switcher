import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from claude_provider_switcher import __version__
from claude_provider_switcher.cli import main, parser
from claude_provider_switcher.core import Switcher, owned_env
from claude_provider_switcher.credentials import Credentials, mask_secret
from claude_provider_switcher.profiles import Profile, Profiles
from claude_provider_switcher.storage import SwitcherError, atomic_write, mutation_lock, read_object, write_object


SECRET = "sk-test-not-a-real-key-0123456789"


class FakeVault:
    def __init__(self, available=False):
        self.available = available
        self.data = {}

    def get(self, name):
        return self.data.get(name)

    def set(self, name, key):
        if self.available:
            self.data[name] = key
        return self.available

    def delete(self, name):
        self.data.pop(name, None)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vault = FakeVault()
        self.switcher = Switcher(self.base / "switcher", self.base / "claude", self.vault)

    def add_api(self, name="local"):
        profiles = self.switcher.profiles.load()
        profiles[name] = Profile("api", "http://127.0.0.1:9000", "test-model", "auth_token")
        self.switcher.profiles.save(profiles)
        self.switcher.credentials.set(name, SECRET)

    def cli(self, arguments, stdin=""):
        output, errors = io.StringIO(), io.StringIO()
        with patch("claude_provider_switcher.cli.Switcher", return_value=self.switcher), patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(output), redirect_stderr(errors):
            result = main(arguments)
        self.assertNotIn(SECRET, output.getvalue() + errors.getvalue())
        return result, output.getvalue(), errors.getvalue()


class ProfilesTests(Fixture):
    def test_defaults_generated_once_and_mutable(self):
        profiles = self.switcher.profiles.load()
        self.assertEqual(set(profiles), {"official", "anthropic", "apimaster"})
        self.switcher.profiles.save({})
        self.assertEqual(self.switcher.profiles.load(), {})

    def test_unknown_keys_and_api_key_in_profile_rejected(self):
        write_object(self.switcher.profiles.path, {"version": 1, "profiles": {"x": {"type": "api", "api_key": SECRET}}})
        with self.assertRaises(SwitcherError) as caught:
            self.switcher.profiles.load()
        self.assertNotIn(SECRET, str(caught.exception))

    def test_malformed_schema_is_not_replaced(self):
        for value in ({}, {"version": True, "profiles": {}}, {"version": 3, "profiles": {}}, {"version": 1, "profiles": []}):
            write_object(self.switcher.profiles.path, value)
            before = self.switcher.profiles.path.read_bytes()
            with self.assertRaises(SwitcherError):
                self.switcher.profiles.load()
            self.assertEqual(before, self.switcher.profiles.path.read_bytes())

    def test_duplicate_json_and_nonfinite_rejected(self):
        self.switcher.root.mkdir()
        for text in ('{"profiles": {}, "profiles": {}}', '{"version": NaN}', '{"bad": "' + SECRET):
            self.switcher.profiles.path.write_text(text)
            with self.assertRaises(SwitcherError) as caught:
                self.switcher.profiles.load()
            self.assertNotIn(SECRET, str(caught.exception))

    def test_invalid_names(self):
        for name in ("../evil", ".", "", "has space", "a" * 65, "a.b"):
            with self.subTest(name=name), self.assertRaises(SwitcherError):
                self.switcher.profiles.save({name: Profile("subscription")})

    def test_reject_insecure_urls_and_bad_models(self):
        invalid = [
            "http://example.com", "ftp://example.com", "https://user:key@example.com",
            "https://example.com/?key=" + SECRET, "https://example.com/#fragment",
            "https://example.com:bad", "https://example.com/v1/messages", "https://example.com/a b",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(SwitcherError):
                Profile("api", url, "model").validate()
        for model in ("", "line\nbreak", "has space", "x" * 201):
            with self.assertRaises(SwitcherError):
                Profile("api", "https://example.com", model).validate()
        with self.assertRaises(SwitcherError):
            Profile("subscription", model="x").validate()

    def test_empty_claude_home_environment_override(self):
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.base / "custom"), "CLAUDE_PROVIDER_SWITCHER_HOME": str(self.base / "custom-switcher")}):
            instance = Switcher()
            self.assertEqual(instance.claude_home, (self.base / "custom").resolve())
        with self.assertRaises(SwitcherError):
            Switcher(self.base, self.base)


class CredentialTests(Fixture):
    def test_fallback_is_private(self):
        self.assertEqual(self.switcher.credentials.set("test", SECRET), "file")
        self.assertEqual(self.switcher.credentials.get("test"), SECRET)
        if os.name != "nt":
            self.assertEqual(self.switcher.credentials.path.stat().st_mode & 0o777, 0o600)
        else:
            result = subprocess.run(["icacls", str(self.switcher.credentials.path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("(I)", result.stdout)

    def test_system_backend_no_plaintext_file(self):
        self.vault.available = True
        self.switcher.credentials.set("test", SECRET)
        self.assertNotIn(SECRET, self.switcher.credentials.path.read_text())
        self.assertEqual(self.switcher.credentials.get("test"), SECRET)

    def test_new_fallback_never_shadowed_by_stale_system_key(self):
        self.vault.available = True
        self.switcher.credentials.set("test", "old-key")
        self.vault.available = False
        self.switcher.credentials.set("test", SECRET)
        self.vault.available = True
        self.assertEqual(self.switcher.credentials.get("test"), SECRET)

    def test_system_unavailable_falls_back(self):
        with patch.object(self.vault, "set", side_effect=OSError("sensitive " + SECRET)):
            self.assertEqual(self.switcher.credentials.set("test", SECRET), "file")

    def test_locked_vault_does_not_print_details(self):
        self.vault.available = True
        self.switcher.credentials.set("test", SECRET)
        with patch.object(self.vault, "get", side_effect=OSError(SECRET)):
            self.assertIsNone(self.switcher.credentials.get("test"))

    def test_delete_and_namespace_isolation(self):
        other = Credentials(self.base / "other", self.vault)
        self.assertNotEqual(other.service("x"), self.switcher.credentials.service("x"))
        self.vault.available = True
        self.switcher.credentials.set("test", SECRET)
        self.switcher.credentials.delete("test")
        self.assertIsNone(self.switcher.credentials.get("test"))
        self.assertEqual(self.vault.data, {})

    def test_validate_and_mask(self):
        for value in ("", "line\nbreak", "space value", "\x01", "x" * 2049):
            with self.assertRaises(SwitcherError):
                self.switcher.credentials.set("test", value)
        self.assertEqual(mask_secret("short"), "****")
        self.assertNotIn(SECRET, mask_secret(SECRET))


class SettingsTests(Fixture):
    def test_api_switch_preserves_settings_and_never_touches_sessions(self):
        self.add_api()
        original = {"env": {"KEEP_ME": "yes", "ANTHROPIC_API_KEY": "old"}, "permissions": {"defaultMode": "manual"}, "hooks": {"x": []}, "apiKeyHelper": "old-helper"}
        write_object(self.switcher.settings_path, original)
        session = self.switcher.claude_home / "projects" / "thread.jsonl"
        session.parent.mkdir()
        session.write_text('{"test":"unchanged"}\n')
        oauth = self.switcher.claude_home / ".credentials.json"
        oauth.write_text('{"oauth":"unchanged"}')
        backup = self.switcher.use("local")
        result = read_object(self.switcher.settings_path)
        self.assertEqual(result["hooks"], original["hooks"])
        self.assertEqual(result["permissions"], original["permissions"])
        self.assertEqual(result["env"]["KEEP_ME"], "yes")
        self.assertNotIn("ANTHROPIC_API_KEY", result["env"])
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertEqual(self.switcher.status()["configured_profile"], "local")
        self.assertEqual(session.read_text(), '{"test":"unchanged"}\n')
        self.assertEqual(oauth.read_text(), '{"oauth":"unchanged"}')
        self.switcher.restore(backup)
        self.assertEqual(read_object(self.switcher.settings_path), original)

    def test_official_removes_gateway_and_cloud_flags(self):
        self.add_api()
        self.switcher.use("local")
        current = read_object(self.switcher.settings_path)
        current["env"].update({"CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_OAUTH_TOKEN": "old", "ANTHROPIC_DEFAULT_OPUS_MODEL": "other", "HTTP_PROXY": "http://127.0.0.1:9"})
        write_object(self.switcher.settings_path, current)
        self.switcher.use("official")
        result = read_object(self.switcher.settings_path)
        self.assertEqual(result["env"], {"HTTP_PROXY": "http://127.0.0.1:9"})
        self.assertNotIn("apiKeyHelper", result)
        self.assertNotIn("model", result)
        self.assertEqual(result["forceLoginMethod"], "claudeai")
        self.assertEqual(self.switcher.status()["configured_profile"], "official")

    def test_missing_key_no_settings_change(self):
        self.switcher.profiles.load()
        with self.assertRaises(SwitcherError):
            self.switcher.use("anthropic")
        self.assertFalse(self.switcher.settings_path.exists())
        self.assertEqual(self.switcher.backups(), [])

    def test_restore_absent_settings_and_undo(self):
        self.switcher.profiles.load()
        backup = self.switcher.use("official")
        undo = self.switcher.restore(backup)
        self.assertFalse(self.switcher.settings_path.exists())
        self.switcher.restore(undo)
        self.assertEqual(read_object(self.switcher.settings_path)["forceLoginMethod"], "claudeai")

    def test_multiple_backups_never_collide(self):
        self.switcher.profiles.load()
        self.switcher.use("official")
        self.switcher.use("official")
        self.assertEqual(len(self.switcher.backups()), 2)

    def test_use_and_restore_preserve_concurrent_settings_changes(self):
        self.switcher.profiles.load()
        backup = self.switcher.use("official")
        original_backup = self.switcher._backup

        def external_change(data, existed):
            identifier = original_backup(data, existed)
            write_object(self.switcher.settings_path, {"external": True})
            return identifier

        for operation in (lambda: self.switcher.use("official"), lambda: self.switcher.restore(backup)):
            write_object(self.switcher.settings_path, {"before": True})
            with patch.object(self.switcher, "_backup", side_effect=external_change), self.assertRaises(SwitcherError):
                operation()
            self.assertEqual(read_object(self.switcher.settings_path), {"external": True})

    def test_status_detects_provider_setting_drift(self):
        self.add_api()
        self.switcher.use("local")
        original = read_object(self.switcher.settings_path)
        for key in ("CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_AUTH_TOKEN"):
            changed = copy.deepcopy(original)
            changed["env"][key] = "unexpected"
            self.assertIsNone(self.switcher.configured_name(changed))
        changed = copy.deepcopy(original)
        changed["model"] = "unexpected"
        self.assertIsNone(self.switcher.configured_name(changed))
        original["hooks"] = {"unrelated": []}
        self.assertEqual(self.switcher.configured_name(original), "local")

    def test_wrong_home_backup_and_traversal_rejected(self):
        self.switcher.profiles.load()
        backup = self.switcher.use("official")
        other = Switcher(self.switcher.root, self.base / "other")
        with self.assertRaises(SwitcherError):
            other.restore(backup)
        with self.assertRaises(SwitcherError):
            self.switcher.restore("../profiles")

    def test_corrupt_user_settings_not_overwritten(self):
        self.switcher.profiles.load()
        self.switcher.claude_home.mkdir()
        for data in ('{"key":"' + SECRET, '{"env":[]}', '{"env":{"API":42}}'):
            self.switcher.settings_path.write_text(data)
            with self.assertRaises(SwitcherError):
                self.switcher.use("official")
            self.assertEqual(self.switcher.settings_path.read_text(), data)

    def test_atomic_replace_failure_preserves_original_and_cleans_up(self):
        path = self.base / "settings.json"
        write_object(path, {"original": True})
        with patch("claude_provider_switcher.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                write_object(path, {"new": True})
        self.assertEqual(read_object(path), {"original": True})
        self.assertEqual(list(self.base.glob(".ccs-*")), [])

    def test_lock_blocks_concurrent_mutation(self):
        with mutation_lock(self.switcher.root):
            with self.assertRaises(SwitcherError):
                with mutation_lock(self.switcher.root):
                    pass
        self.assertFalse((self.switcher.root / ".ccs.lock").exists())

    @unittest.skipIf(os.name == "nt", "Windows symlinks require developer privileges")
    def test_symlink_settings_not_replaced(self):
        self.switcher.profiles.load()
        self.switcher.claude_home.mkdir()
        target = self.base / "target"
        target.write_text("{}")
        self.switcher.settings_path.symlink_to(target)
        with self.assertRaises(SwitcherError):
            self.switcher.use("official")
        self.assertEqual(target.read_text(), "{}")

    def test_status_and_doctor_do_not_execute_user_helpers(self):
        write_object(self.switcher.settings_path, {"apiKeyHelper": SECRET, "env": {"ANTHROPIC_AUTH_TOKEN": SECRET, "ANTHROPIC_BASE_URL": "https://user:" + SECRET + "@example.com/secret?key=" + SECRET}})
        self.switcher.profiles.load()
        project = self.base / "project"
        write_object(project / ".claude/settings.json", {"env": {"ANTHROPIC_API_KEY": SECRET}})
        with patch("subprocess.call", side_effect=AssertionError("must not execute")):
            findings = self.switcher.doctor(project, {"ANTHROPIC_AUTH_TOKEN": SECRET})
            status = self.switcher.status()
        serialized = json.dumps([findings, status])
        self.assertNotIn(SECRET, serialized)
        self.assertIn("shell", serialized)
        self.assertIn("ANTHROPIC_API_KEY", serialized)
        self.assertEqual(status["base_url_origin"], "https://example.com")

    def test_credential_helper_machine_channel(self):
        self.add_api()
        helper = Path(__file__).parents[1] / "claude_provider_switcher/credential_helper.py"
        result = subprocess.run([sys.executable, str(helper), str(self.switcher.root), "local"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, SECRET)
        missing = subprocess.run([sys.executable, str(helper), str(self.switcher.root), "missing"], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(missing.stdout, "")
        shell_result = subprocess.run(self.switcher.helper_command("local"), shell=True, capture_output=True, text=True, timeout=15)
        self.assertEqual(shell_result.returncode, 0, shell_result.stderr)
        self.assertEqual(shell_result.stdout, SECRET)

    def test_run_sanitizes_child_only_and_preserves_settings(self):
        self.add_api()
        original = {"permissions": {"defaultMode": "manual"}, "apiKeyHelper": "old-helper", "env": {"ANTHROPIC_API_KEY": "old", "KEEP": "1"}}
        write_object(self.switcher.settings_path, original)
        captured = {}

        def child(command, env):
            captured["command"] = command
            captured["env"] = env
            captured["settings"] = read_object(Path(command[command.index("--settings") + 1]))
            self.assertNotIn(SECRET, json.dumps(captured["settings"]))
            return 0

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "old", "CLAUDE_CODE_USE_BEDROCK": "1"}), patch("shutil.which", return_value="claude"), patch("subprocess.call", side_effect=child):
            self.assertEqual(self.switcher.run("local", ["--version"]), 0)
            self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "old")
        self.assertEqual(captured["env"]["ANTHROPIC_AUTH_TOKEN"], SECRET)
        self.assertNotIn("ANTHROPIC_API_KEY", captured["env"])
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", captured["env"])
        self.assertNotIn("apiKeyHelper", captured["settings"])
        self.assertIn("--setting-sources=", captured["command"])
        self.assertEqual(read_object(self.switcher.settings_path), original)
        self.assertEqual(list(self.switcher.root.glob("run-*")), [])

    def test_subscription_run_strips_auth_and_rejects_overrides(self):
        self.switcher.profiles.load()
        with patch("shutil.which", return_value="claude"), patch("subprocess.call", return_value=0) as call, patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": SECRET}):
            self.switcher.run("official", ["--version"])
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", call.call_args.kwargs["env"])
        for argument in ("--settings=secret.json", "--model", "--bare", "--resume"):
            with self.assertRaises(SwitcherError):
                self.switcher.run("official", [argument])


class CliTests(Fixture):
    def test_parser_error_redacts_supplied_values(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
            main(["profile", "test", "local", "--timeout", SECRET])
        self.assertNotIn(SECRET, errors.getvalue())

    def test_interactive_add_prompts_without_echoing_key(self):
        from claude_provider_switcher.cli import execute
        args = parser().parse_args(["profile", "add", "interactive"])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["https://example.com", "model"]), patch("getpass.getpass", return_value=SECRET), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(execute(args, self.switcher), 0)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(self.switcher.credentials.get("interactive"), SECRET)

    def test_menu_switch_status_list_diagnose(self):
        self.add_api()
        self.assertEqual(self.cli(["menu"], "2\n4\n1\n5\n1\n1\n0\n")[0], 0)
        self.assertEqual(self.switcher.status()["configured_profile"], "official")

    def test_menu_add_edit_set_key_and_remove(self):
        from claude_provider_switcher.cli import menu
        self.switcher.profiles.load()
        values = [
            "4", "2", "new", "https://example.com", "model",
            "4", "5", "2", "", "new-model", "",
            "4", "3", "2",
            "4", "4", "4", "y",
            "0",
        ]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=values), patch("getpass.getpass", return_value=SECRET), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(menu(parser(), self.switcher), 0)
        self.assertNotIn("new", self.switcher.profiles.load())

    def test_menu_restore_and_invalid_choices(self):
        self.switcher.profiles.load()
        backup = self.switcher.use("official")
        result = self.cli(["menu"], f"nonsense\n1\n99\n4\n99\n6\n{backup}\ny\n0\n")
        self.assertEqual(result[0], 0)
        # Noninteractive restore deliberately refuses confirmation.
        self.assertIn("Operation cancelled", result[2])

    def test_probe_dispatch_and_menu_probe(self):
        self.add_api()
        with patch("claude_provider_switcher.cli.probe", return_value={"ok": True}) as mocked:
            self.assertEqual(self.cli(["profile", "test", "local", "--inference"])[0], 0)
            self.assertTrue(mocked.call_args.kwargs["inference"])
            self.assertEqual(self.cli(["menu"], "3\n3\n0\n")[0], 0)

    def test_extra_validation_paths(self):
        self.add_api()
        self.assertEqual(self.cli(["profile", "edit", "official", "--model", "x"])[0], 1)
        self.assertEqual(self.cli(["profile", "key", "official"])[0], 1)
        self.assertEqual(self.cli(["profile", "edit", "local"])[0], 1)
        with patch("claude_provider_switcher.cli.execute", side_effect=OSError(SECRET)):
            self.assertEqual(self.cli(["status"])[0], 1)
        with patch("claude_provider_switcher.cli.execute", side_effect=KeyboardInterrupt):
            self.assertEqual(self.cli(["status"])[0], 130)

    def test_add_edit_key_remove_lifecycle(self):
        code, _, error = self.cli(["profile", "add", "local", "--base-url", "https://example.com", "--model", "test", "--auth-kind", "auth_token", "--key-stdin"], SECRET + "\n")
        self.assertEqual(code, 0, error)
        self.assertEqual(self.switcher.profiles.get("local").auth_kind, "auth_token")
        self.assertEqual(self.cli(["profile", "edit", "local", "--model", "new"])[0], 0)
        self.assertEqual(self.switcher.profiles.get("local").model, "new")
        self.assertEqual(self.cli(["profile", "key", "local", "--key-stdin"], SECRET + "\n")[0], 0)
        self.assertEqual(self.cli(["profile", "remove", "local", "--yes"])[0], 0)
        self.assertNotIn("local", self.switcher.profiles.load())
        self.assertIsNone(self.switcher.credentials.get("local"))

    def test_use_status_restore_cli(self):
        self.add_api()
        self.assertEqual(self.cli(["use", "local"])[0], 0)
        status = self.cli(["status", "--json"])
        self.assertEqual(json.loads(status[1])["configured_profile"], "local")
        self.assertEqual(self.cli(["profile", "remove", "local", "--yes"])[0], 1)
        backup = self.switcher.backups()[0]
        self.assertEqual(self.cli(["backup", "restore", backup, "--yes"])[0], 0)

    def test_remove_still_referenced_after_edit(self):
        self.add_api()
        self.switcher.use("local")
        self.cli(["profile", "edit", "local", "--model", "new"])
        self.assertEqual(self.cli(["profile", "remove", "local", "--yes"])[0], 1)

    def test_noninteractive_key_and_missing_model_fail(self):
        self.assertEqual(self.cli(["profile", "add", "x", "--base-url", "https://example.com"])[0], 1)
        self.assertEqual(self.cli(["profile", "key", "anthropic"])[0], 1)
        self.assertEqual(self.cli(["profile", "remove", "anthropic"])[0], 1)

    def test_duplicate_add_and_subscription_options(self):
        self.assertEqual(self.cli(["profile", "add", "official", "--type", "subscription"])[0], 1)
        self.assertEqual(self.cli(["profile", "add", "other", "--type", "subscription", "--model", "bad"])[0], 1)
        self.assertEqual(self.cli(["profile", "add", "other", "--type", "subscription"])[0], 0)

    def test_version_does_not_create_state(self):
        with redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as caught:
            main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn(__version__, output.getvalue())
        self.assertFalse(self.switcher.root.exists())

    def test_doctor_and_invalid_probe_options(self):
        self.add_api()
        code, output, _ = self.cli(["doctor", "--json", "--project", str(self.base)])
        self.assertIn(code, (0, 1))
        self.assertIn("limitations", json.loads(output))
        self.assertEqual(self.cli(["profile", "test", "local", "--timeout", "-1"])[0], 1)
        self.assertEqual(self.cli(["profile", "test", "official"])[0], 1)

    def test_menu_exit(self):
        self.assertEqual(self.cli(["menu"], "0\n")[0], 0)


if __name__ == "__main__":
    unittest.main()

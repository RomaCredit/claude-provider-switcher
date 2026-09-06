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

from claude_provider_switcher.cli import main
from claude_provider_switcher.core import Switcher
from claude_provider_switcher.history import canonical_project, encode_project_dir
from claude_provider_switcher.storage import SwitcherError, read_object, write_object


FORWARD = "D:/WorkSpace/app"
BACKWARD = "D:\\WorkSpace\\app"


class HistoryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.switcher = Switcher(self.base / "switcher", self.base / "claude")
        self.config = self.base / "claude.json"
        self.switcher.history._config_path = self.config

    def write_config(self, projects):
        write_object(self.config, {"numStartups": 3, "projects": projects})

    def write_history(self, records):
        path = self.switcher.history.history_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")

    def cli(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with patch("claude_provider_switcher.cli.Switcher", return_value=self.switcher), redirect_stdout(output), redirect_stderr(errors):
            result = main(arguments)
        return result, output.getvalue(), errors.getvalue()


class EncodingTests(unittest.TestCase):
    def test_both_separators_encode_to_one_transcript_directory(self):
        # Inventory helper only; this does not prove behavior of every client.
        self.assertEqual(encode_project_dir(FORWARD), encode_project_dir(BACKWARD))
        self.assertEqual(encode_project_dir("C:/Users/58927"), "C--Users-58927")
        self.assertEqual(encode_project_dir("D:\\WorkSpace\\codex\u5207\u6362\u63d2\u4ef6"), "D--WorkSpace-codex----")

    def test_canonical_project_groups_separator_and_drive_case(self):
        self.assertEqual(canonical_project(FORWARD), canonical_project(BACKWARD))
        self.assertEqual(canonical_project("d:\\WorkSpace\\app"), canonical_project(FORWARD))
        self.assertEqual(canonical_project("D:/WorkSpace/app/"), canonical_project(FORWARD))
        self.assertEqual(canonical_project("/"), "/")
        self.assertNotEqual(canonical_project("/srv/App"), canonical_project("/srv/app"))


class RepairTests(HistoryFixture):
    def test_merges_duplicate_records_into_every_path_form(self):
        self.write_config({
            FORWARD: {"hasTrustDialogAccepted": True, "allowedTools": ["Read"], "lastSessionId": "abc"},
            BACKWARD: {"hasTrustDialogAccepted": True, "allowedTools": ["Read"]},
            "D:/WorkSpace/other": {"lastSessionId": "solo"},
        })
        report = self.switcher.repair_history()
        self.assertEqual(report["duplicate_folders"], 1)
        # Only the stub needs rewriting; the richest record already holds the merge.
        self.assertEqual(report["project_entries_updated"], 1)
        projects = read_object(self.config)["projects"]
        expected = {"hasTrustDialogAccepted": True, "allowedTools": ["Read"], "lastSessionId": "abc"}
        self.assertEqual(projects[FORWARD], expected)
        self.assertEqual(projects[BACKWARD], expected)
        self.assertEqual(projects["D:/WorkSpace/other"], {"lastSessionId": "solo"})
        self.assertEqual(read_object(self.config)["numStartups"], 3)

    def test_richer_record_cannot_override_or_grant_trust(self):
        self.write_config({
            FORWARD: {"hasTrustDialogAccepted": True, "allowedTools": ["Bash"], "mcpServers": {}},
            BACKWARD: {"hasTrustDialogAccepted": False},
        })
        before = self.config.read_bytes()
        report = self.switcher.repair_history()
        self.assertFalse(report["applied"])
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(self.config.read_bytes(), before)

    def test_conflicting_state_is_preserved_and_reported(self):
        self.write_config({
            FORWARD: {"allowedTools": ["Read"], "mcpServers": {"a": {}}},
            BACKWARD: {"allowedTools": ["Bash"], "mcpServers": {"b": {}}},
        })
        report = self.switcher.repair_history()
        self.assertEqual(report["conflicts"][0]["field_count"], 2)
        projects = read_object(self.config)["projects"]
        self.assertEqual(projects[FORWARD]["allowedTools"], ["Read"])
        self.assertEqual(projects[BACKWARD]["allowedTools"], ["Bash"])
        self.assertEqual(projects[FORWARD]["mcpServers"], {"a": {}})
        self.assertEqual(projects[BACKWARD]["mcpServers"], {"b": {}})

    def test_check_reports_without_writing_and_exits_nonzero(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        original = self.config.read_text(encoding="utf-8")
        report = self.switcher.repair_history(apply=False)
        self.assertEqual(report["duplicate_folders"], 1)
        self.assertFalse(report["applied"])
        self.assertIsNone(report["backup"])
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        code, output, _ = self.cli(["repair-history", "--check"])
        self.assertEqual(code, 1)
        # A report that wrote nothing must not claim it merged anything.
        self.assertIn("would update 1 project record", output)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_consistent_configuration_is_left_untouched(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}})
        original = self.config.read_text(encoding="utf-8")
        report = self.switcher.repair_history()
        self.assertEqual(report["duplicate_folders"], 0)
        self.assertFalse(report["applied"])
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertEqual(self.cli(["repair-history", "--check"])[0], 0)

    def test_check_detects_history_only_changes(self):
        self.write_config({FORWARD: {}})
        self.write_history([{"project": FORWARD}, {"project": BACKWARD}])
        self.assertEqual(self.cli(["repair-history", "--check"])[0], 1)

    def test_check_is_zero_when_duplicate_records_already_match(self):
        expected = {"lastSessionId": "same"}
        self.write_config({FORWARD: expected, BACKWARD: expected})
        self.assertEqual(self.cli(["repair-history", "--check"])[0], 0)

    def test_backup_captures_both_files_before_writing(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        self.write_history([
            {"display": "\u4f60\u597d", "project": FORWARD, "sessionId": "a"},
            {"display": "hi", "project": BACKWARD, "sessionId": "b"},
        ])
        report = self.switcher.repair_history()
        saved = self.switcher.backups_dir / f"history-{report['backup']}"
        self.assertEqual(read_object(saved / "claude.json")["projects"][BACKWARD], {})
        restored = [json.loads(line) for line in (saved / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["project"] for r in restored], [FORWARD, BACKWARD])

    def test_history_entries_adopt_the_spelling_claude_used_most(self):
        self.write_config({FORWARD: {}})
        self.write_history([
            {"display": "one", "project": FORWARD},
            {"display": "two", "project": FORWARD},
            {"display": "\u4e09", "project": BACKWARD},
            {"display": "elsewhere", "project": "/srv/app"},
        ])
        report = self.switcher.repair_history()
        self.assertEqual(report["history_entries_normalized"], 1)
        lines = self.switcher.history.history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["project"] for line in lines], [FORWARD, FORWARD, FORWARD, "/srv/app"])
        # Non-ASCII prompts stay readable rather than being escaped.
        self.assertIn("\u4e09", lines[2])

    def test_unparsable_history_lines_are_preserved_verbatim(self):
        self.write_config({FORWARD: {}})
        path = self.switcher.history.history_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"project": FORWARD}) + "\nnot json\n" + json.dumps({"project": BACKWARD}) + "\n",
            encoding="utf-8",
        )
        self.switcher.repair_history()
        self.assertEqual(path.read_text(encoding="utf-8").splitlines()[1], "not json")

    def test_orphan_transcript_directories_are_reported_not_deleted(self):
        self.write_config({FORWARD: {}})
        orphan = self.switcher.claude_home / "projects" / "D--WorkSpace-gone"
        orphan.mkdir(parents=True)
        (orphan / "session.jsonl").write_text('{"kept":true}\n')
        report = self.switcher.repair_history()
        self.assertEqual(report["transcript_directories"], 1)
        self.assertEqual(report["transcript_directories_without_project_entry"], ["D--WorkSpace-gone"])
        self.assertEqual((orphan / "session.jsonl").read_text(), '{"kept":true}\n')

    def test_concurrent_history_change_is_rejected(self):
        self.write_config({FORWARD: {}})
        self.write_history([{"project": FORWARD}, {"project": BACKWARD}])
        original_backup = self.switcher.history._backup
        def change_during_read(*args):
            result = original_backup(*args)
            with self.switcher.history.history_path.open("a", encoding="utf-8") as stream:
                stream.write('{"project":"D:/new"}\n')
            return result
        with patch.object(self.switcher.history, "_backup", side_effect=change_during_read), self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        self.assertIn("D:/new", self.switcher.history.history_path.read_text(encoding="utf-8"))

    def test_missing_configuration_is_not_an_error(self):
        report = self.switcher.repair_history()
        self.assertFalse(report["config_present"])
        self.assertEqual(report["duplicate_folders"], 0)
        self.assertFalse(self.config.exists())

    def test_invalid_projects_map_is_rejected_without_writing(self):
        write_object(self.config, {"projects": [FORWARD]})
        with self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        write_object(self.config, {"projects": {FORWARD: "not-an-object"}})
        with self.assertRaises(SwitcherError):
            self.switcher.repair_history()

    def test_config_path_defaults_beside_the_configuration_directory(self):
        switcher = Switcher(self.base / "switcher", self.base / "claude")
        self.assertEqual(switcher.history.config_path, self.base / "claude.json")
        inside = self.base / "claude" / ".claude.json"
        inside.parent.mkdir(parents=True, exist_ok=True)
        write_object(inside, {"projects": {}})
        self.assertEqual(switcher.history.config_path, inside)


class SwitchIntegrationTests(HistoryFixture):
    def test_use_reports_records_without_rewriting_them(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        before = self.config.read_bytes()
        result, output, _ = self.cli(["use", "official"])
        self.assertEqual(result, 0)
        self.assertIn("would update 1 project record", output)
        self.assertIn("never read or rewritten", output)
        self.assertEqual(self.config.read_bytes(), before)

    def test_explicit_repair_requires_confirmation(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        before = self.config.read_bytes()
        with patch("sys.stdin", io.StringIO()):
            self.assertEqual(self.cli(["repair-history"])[0], 1)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.cli(["repair-history", "--yes"])[0], 0)
        self.assertEqual(read_object(self.config)["projects"][BACKWARD], {"lastSessionId": "abc"})

    def test_read_only_check_failure_does_not_claim_switch_failed(self):
        with patch.object(self.switcher, "repair_history", side_effect=SwitcherError("sensitive-test-value")):
            result, _, errors = self.cli(["use", "official"])
        self.assertEqual(result, 0)
        self.assertIn("Provider switch succeeded", errors)
        self.assertNotIn("sensitive-test-value", errors)

    def test_menu_repair_confirmation_cancel_and_accept(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        before = self.config.read_bytes()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["7", "n", "0"]):
            self.assertEqual(self.cli(["menu"])[0], 0)
        self.assertEqual(self.config.read_bytes(), before)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["7", "y", "0"]):
            self.assertEqual(self.cli(["menu"])[0], 0)
        self.assertEqual(read_object(self.config)["projects"][BACKWARD], {"lastSessionId": "abc"})

    def test_no_repair_history_leaves_records_alone(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        original = self.config.read_text(encoding="utf-8")
        result, output, _ = self.cli(["use", "official", "--no-repair-history"])
        self.assertEqual(result, 0)
        self.assertNotIn("History:", output)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_switching_never_touches_transcripts(self):
        transcript = self.switcher.claude_home / "projects" / encode_project_dir(FORWARD) / "session.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text('{"type":"user","message":"keep me"}\n', encoding="utf-8")
        self.write_config({FORWARD: {}, BACKWARD: {}})
        self.cli(["use", "official"])
        self.assertEqual(transcript.read_text(encoding="utf-8"), '{"type":"user","message":"keep me"}\n')


class SafetyTests(HistoryFixture):
    def dirty_both(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        self.write_history([{"project": FORWARD}, {"project": BACKWARD}])

    def test_missing_security_fields_are_not_copied(self):
        for field, value in (
            ("allowedTools", ["Bash"]), ("mcpServers", {"secret-server": {"env": {"TOKEN": "secret-value"}}}),
            ("hasTrustDialogAccepted", True), ("unknownFuturePermission", True),
        ):
            with self.subTest(field=field):
                self.write_config({FORWARD: {field: value, "lastSessionId": "abc"}, BACKWARD: {}})
                original = self.config.read_bytes()
                report = self.switcher.repair_history()
                self.assertEqual(self.config.read_bytes(), original)
                self.assertEqual(len(report["conflicts"]), 1)
                self.assertNotIn("secret-value", json.dumps(report))
                self.assertNotIn("secret-server", json.dumps(report))

    def test_conflicting_nested_types_and_session_ids_are_not_guessed(self):
        for field, a, b in (
            ("lastSessionId", "old", "new"), ("lastCost", 1, True),
            ("mcpServers", {"x": {"enabled": True}}, {"x": {"enabled": 1}}),
        ):
            self.write_config({FORWARD: {field: a}, BACKWARD: {field: b}})
            before = self.config.read_bytes()
            self.assertEqual(len(self.switcher.repair_history()["conflicts"]), 1)
            self.assertEqual(before, self.config.read_bytes())

    def test_conflicting_folder_history_labels_are_not_normalized(self):
        self.write_config({FORWARD: {"allowedTools": ["Read"]}, BACKWARD: {"allowedTools": ["Bash"]}})
        self.write_history([{"project": FORWARD}, {"project": BACKWARD}])
        before = self.switcher.history.history_path.read_bytes()
        code, output, _ = self.cli(["repair-history", "--yes", "--json"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output)["pending_changes"])
        self.assertEqual(before, self.switcher.history.history_path.read_bytes())
        self.assertEqual(self.cli(["repair-history", "--check"])[0], 1)

    def test_safe_folder_repaired_while_conflicting_folder_preserved(self):
        other, alias = "C:/other", "C:\\other"
        self.write_config({FORWARD: {"allowedTools": ["Read"]}, BACKWARD: {},
                           other: {"lastSessionId": "abc"}, alias: {}})
        self.assertEqual(self.cli(["repair-history", "--yes"])[0], 1)
        data = read_object(self.config)["projects"]
        self.assertEqual(data[BACKWARD], {})
        self.assertEqual(data[alias], {"lastSessionId": "abc"})
        self.assertFalse(self.switcher.repair_history(apply=False)["pending_changes"])

    def test_check_creates_no_directories_files_or_locks(self):
        self.assertEqual(self.cli(["repair-history", "--check"])[0], 0)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_check_works_with_switcher_mutation_lock_held(self):
        self.dirty_both()
        from claude_provider_switcher.storage import mutation_lock
        with mutation_lock(self.switcher.root):
            self.assertTrue(self.switcher.repair_history(apply=False)["pending_changes"])

    def test_preserves_posix_backslashes_and_drive_root_identity(self):
        self.assertNotEqual(canonical_project("/srv/a\\b"), canonical_project("/srv/a/b"))
        self.assertNotEqual(canonical_project("D:"), canonical_project("D:/"))
        self.assertEqual(canonical_project("D:\\"), canonical_project("d:/"))
        self.write_config({"/srv/a\\b": {"lastSessionId": "one"}, "/srv/a/b": {}})
        self.assertFalse(self.switcher.repair_history()["pending_changes"])

    def test_bom_crlf_invalid_lines_and_no_final_newline_are_preserved(self):
        self.write_config({FORWARD: {}})
        path = self.switcher.history.history_path
        path.parent.mkdir()
        invalid = b'{"project":"one","project":"two"}\r\n{"x":NaN}\r\nBROKEN\r\n'
        original = (b"\xef\xbb\xbf" + json.dumps({"project": FORWARD}).encode() + b"\r\n" + invalid
                    + json.dumps({"project": BACKWARD, "display": "\u4f60\u597d"}).encode())
        path.write_bytes(original)
        self.switcher.repair_history()
        result = path.read_bytes()
        self.assertTrue(result.startswith(b"\xef\xbb\xbf"))
        self.assertIn(invalid, result)
        self.assertFalse(result.endswith(b"\n"))
        self.assertEqual(result.count(b"\r\n"), original.count(b"\r\n"))

    def test_bad_encoding_rejected_without_writes(self):
        self.dirty_both()
        for path in (self.config, self.switcher.history.history_path):
            original = path.read_bytes()
            path.write_bytes(b"\xff")
            with self.assertRaises(SwitcherError):
                self.switcher.repair_history()
            self.assertEqual(path.read_bytes(), b"\xff")
            path.write_bytes(original)

    def test_backups_are_exact_bytes_and_private_even_for_public_sources(self):
        self.dirty_both()
        paths = [self.config, self.switcher.history.history_path]
        for path in paths:
            path.chmod(0o644)
        originals = [path.read_bytes() for path in paths]
        report = self.switcher.repair_history()
        backup = self.switcher.backups_dir / ("history-" + report["backup"])
        for name, original in zip(("claude.json", "history.jsonl"), originals):
            path = backup / name
            self.assertEqual(path.read_bytes(), original)
            if os.name == "nt":
                acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True)
                self.assertNotIn("(I)", acl.stdout)
            else:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_history_only_report_does_not_claim_nothing_to_repair(self):
        self.write_history([{"project": FORWARD}, {"project": BACKWARD}])
        code, output, _ = self.cli(["repair-history", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("1 prompt path label", output)
        self.assertNotIn("no automatic changes", output)

    def test_backup_failure_leaves_both_sources_untouched(self):
        self.dirty_both()
        originals = (self.config.read_bytes(), self.switcher.history.history_path.read_bytes())
        with patch.object(self.switcher.history, "_backup", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.switcher.repair_history()
        self.assertEqual(originals, (self.config.read_bytes(), self.switcher.history.history_path.read_bytes()))

    def test_external_edit_after_backup_preserved_and_no_repair_committed(self):
        for name in ("config", "history"):
            self.dirty_both()
            original_config = self.config.read_bytes()
            original_history = self.switcher.history.history_path.read_bytes()
            backup = self.switcher.history._backup
            def edit(snapshots):
                identifier = backup(snapshots)
                path = self.config if name == "config" else self.switcher.history.history_path
                with path.open("ab") as stream:
                    stream.write(b"\nNEW-DATA")
                return identifier
            with patch.object(self.switcher.history, "_backup", side_effect=edit), self.assertRaises(SwitcherError) as error:
                self.switcher.repair_history()
            self.assertIn("Files already replaced: none", str(error.exception))
            self.assertEqual(self.config.read_bytes(), original_config + (b"\nNEW-DATA" if name == "config" else b""))
            self.assertEqual(self.switcher.history.history_path.read_bytes(), original_history + (b"\nNEW-DATA" if name == "history" else b""))

    def test_guard_runs_after_staging_temp_file(self):
        self.dirty_both()
        import claude_provider_switcher.storage as storage
        real_private = storage.private_file
        def mutate_during_stage(path):
            real_private(path)
            if path.parent == self.config.parent:
                with self.switcher.history.history_path.open("ab") as stream:
                    stream.write(b"\nNEW-PROMPT")
        before = self.config.read_bytes()
        with patch.object(storage, "private_file", side_effect=mutate_during_stage), self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertIn(b"NEW-PROMPT", self.switcher.history.history_path.read_bytes())
        self.assertEqual(list(self.base.glob(".ccs-*")), [])

    def test_separate_process_append_after_backup_is_preserved(self):
        self.dirty_both()
        backup = self.switcher.history._backup
        def append(snapshots):
            identifier = backup(snapshots)
            subprocess.run(
                [sys.executable, "-c",
                 "import sys; from pathlib import Path; p=Path(sys.argv[1]); "
                 "f=p.open('ab'); f.write(b'\\nEXTERNAL-PROMPT'); f.close()",
                 str(self.switcher.history.history_path)],
                check=True, capture_output=True, timeout=10,
            )
            return identifier
        with patch.object(self.switcher.history, "_backup", side_effect=append), self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        self.assertIn(b"EXTERNAL-PROMPT", self.switcher.history.history_path.read_bytes())
        self.assertEqual(read_object(self.config)["projects"][BACKWARD], {})

    def test_external_append_between_replacements_stops_second_write(self):
        self.dirty_both()
        import claude_provider_switcher.storage as storage
        real_replace = storage.os.replace
        def write_then_append(source, target):
            real_replace(source, target)
            if Path(target) == self.config:
                with self.switcher.history.history_path.open("ab") as stream:
                    stream.write(b"\nEXTERNAL-PROMPT")
        with patch.object(storage.os, "replace", side_effect=write_then_append), self.assertRaises(SwitcherError) as error:
            self.switcher.repair_history()
        self.assertIn("Files already replaced: claude.json", str(error.exception))
        self.assertIn(b"EXTERNAL-PROMPT", self.switcher.history.history_path.read_bytes())
        self.assertEqual(read_object(self.config)["projects"][BACKWARD], {"lastSessionId": "abc"})

    def test_config_path_drift_during_backup_aborts(self):
        self.dirty_both()
        self.switcher.history._config_path = None
        before = self.config.read_bytes()
        backup = self.switcher.history._backup
        def relocate(snapshots):
            identifier = backup(snapshots)
            write_object(self.switcher.claude_home / ".claude.json", {"projects": {}})
            return identifier
        with patch.object(self.switcher.history, "_backup", side_effect=relocate), self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        self.assertEqual(self.config.read_bytes(), before)

    def test_new_history_file_during_backup_is_preserved(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        backup = self.switcher.history._backup
        def create(snapshots):
            identifier = backup(snapshots)
            self.switcher.history.history_path.write_bytes(b"NEW-HISTORY")
            return identifier
        with patch.object(self.switcher.history, "_backup", side_effect=create), self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        self.assertEqual(read_object(self.config)["projects"][BACKWARD], {})
        self.assertEqual(self.switcher.history.history_path.read_bytes(), b"NEW-HISTORY")

    def test_invalid_config_duplicate_keys_not_silently_replaced(self):
        self.config.write_bytes(b'{"projects": {}, "projects": {}}')
        before = self.config.read_bytes()
        with self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        self.assertEqual(before, self.config.read_bytes())

    def test_partial_failure_is_reported_without_destructive_rollback(self):
        self.dirty_both()
        import claude_provider_switcher.storage as storage
        original_replace = storage.os.replace
        original_history = self.switcher.history.history_path.read_bytes()
        def fail_second(source, target):
            if Path(target) == self.switcher.history.history_path:
                raise OSError("secret-value")
            return original_replace(source, target)
        with patch.object(storage.os, "replace", side_effect=fail_second), self.assertRaises(SwitcherError) as error:
            self.switcher.repair_history()
        self.assertIn("Files already replaced: claude.json", str(error.exception))
        self.assertIn("history-", str(error.exception))
        self.assertNotIn("secret-value", str(error.exception))
        self.assertEqual(original_history, self.switcher.history.history_path.read_bytes())
        self.assertEqual(read_object(self.config)["projects"][BACKWARD], {"lastSessionId": "abc"})

    def test_created_deleted_or_replaced_sources_are_detected(self):
        from claude_provider_switcher.history import Snapshot
        path = self.base / "snapshot"
        missing = Snapshot.read(path)
        path.write_bytes(b"original")
        with self.assertRaises(SwitcherError):
            missing.check()
        original = Snapshot.read(path)
        replacement = self.base / "new"
        replacement.write_bytes(b"original")
        os.replace(replacement, path)
        with self.assertRaises(SwitcherError):
            original.check()
        original = Snapshot.read(path)
        path.unlink()
        with self.assertRaises(SwitcherError):
            original.check()

    @unittest.skipIf(os.name == "nt", "Symlinks need Windows developer privileges")
    def test_symlink_and_dangling_symlink_rejected(self):
        self.dirty_both()
        self.config.unlink()
        target = self.base / "target"
        target.write_text("{}")
        self.config.symlink_to(target)
        with self.assertRaises(SwitcherError):
            self.switcher.repair_history()
        target.unlink()
        with self.assertRaises(SwitcherError):
            self.switcher.repair_history()

    def test_hard_link_rejected(self):
        self.dirty_both()
        alias = self.base / "alias"
        try:
            os.link(self.config, alias)
        except OSError:
            self.skipTest("Hard links unsupported")
        with self.assertRaises(SwitcherError):
            self.switcher.repair_history()


if __name__ == "__main__":
    unittest.main()

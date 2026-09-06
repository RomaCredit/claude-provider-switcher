import io
import json
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
        # This is why switching providers cannot split conversation history.
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
            FORWARD: {"hasTrustDialogAccepted": True, "allowedTools": ["Bash"], "lastSessionId": "abc"},
            BACKWARD: {"hasTrustDialogAccepted": False},
            "D:/WorkSpace/other": {"lastSessionId": "solo"},
        })
        report = self.switcher.repair_history()
        self.assertEqual(report["duplicate_folders"], 1)
        # Only the stub needs rewriting; the richest record already holds the merge.
        self.assertEqual(report["project_entries_updated"], 1)
        projects = read_object(self.config)["projects"]
        expected = {"hasTrustDialogAccepted": True, "allowedTools": ["Bash"], "lastSessionId": "abc"}
        self.assertEqual(projects[FORWARD], expected)
        self.assertEqual(projects[BACKWARD], expected)
        self.assertEqual(projects["D:/WorkSpace/other"], {"lastSessionId": "solo"})
        self.assertEqual(read_object(self.config)["numStartups"], 3)

    def test_richer_record_wins_so_a_fresh_stub_cannot_reset_trust(self):
        self.write_config({
            FORWARD: {"hasTrustDialogAccepted": True, "allowedTools": ["Bash"], "mcpServers": {}},
            BACKWARD: {"hasTrustDialogAccepted": False},
        })
        self.switcher.repair_history()
        self.assertTrue(read_object(self.config)["projects"][BACKWARD]["hasTrustDialogAccepted"])

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
        self.assertIn("would merge 1 folder", output)
        self.assertNotIn("merged 1 folder", output)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_consistent_configuration_is_left_untouched(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}})
        original = self.config.read_text(encoding="utf-8")
        report = self.switcher.repair_history()
        self.assertEqual(report["duplicate_folders"], 0)
        self.assertFalse(report["applied"])
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
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
    def test_use_reconciles_records_and_reports_them(self):
        self.write_config({FORWARD: {"lastSessionId": "abc"}, BACKWARD: {}})
        result, output, _ = self.cli(["use", "official"])
        self.assertEqual(result, 0)
        self.assertIn("merged 1 folder", output)
        self.assertIn("not filtered by provider", output)
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


if __name__ == "__main__":
    unittest.main()

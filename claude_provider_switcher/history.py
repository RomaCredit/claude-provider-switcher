"""Repair Claude Code project bookkeeping so history survives a provider switch.

Claude Code does not tag a conversation with the provider that produced it.
Switching providers rewrites ``settings.json`` only, so no transcript is ever
hidden or lost, and there is no per-conversation provider field to rewrite.

Transcripts live in ``<claude_home>/projects/<encoded-cwd>/<session>.jsonl``
where the encoding replaces every non-alphanumeric character with ``-``.
``D:/WorkSpace/app`` and ``D:\\WorkSpace\\app`` therefore encode to the same
directory and cannot split.

What does split is the bookkeeping that stores the raw working directory
string: the ``projects`` map in ``.claude.json`` and the ``project`` field in
``history.jsonl``. Entry points disagree about the separator on Windows - the
CLI writes ``D:/WorkSpace/app`` while the desktop app writes
``D:\\WorkSpace\\app`` - leaving two records for one folder that split trust
approval, allowed tools, MCP settings and prompt recall.

This module merges those records. ``.claude.json`` entries are mirrored rather
than collapsed: every path form for a folder receives the merged payload, so
whichever form an entry point looks up it finds complete state, and a form that
the desktop app recreates later is repaired on the next run instead of silently
losing data.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .storage import SwitcherError, atomic_write, read_object, write_object


def encode_project_dir(path: str) -> str:
    """Return the ``projects/`` directory name Claude Code derives from a cwd."""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def canonical_project(path: str) -> str:
    """Group key for project paths that differ only in separator or drive case.

    Path case is not folded: that would merge genuinely distinct directories on
    case-sensitive filesystems, and separator drift is the failure seen in
    practice.
    """
    normalized = path.replace("\\", "/")
    if len(normalized) > 1:
        normalized = normalized.rstrip("/") or normalized[0]
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isascii() and normalized[0].isalpha():
        normalized = normalized[0].upper() + normalized[1:]
    return normalized


class HistoryRepair:
    """Reconcile duplicated project records under a Claude configuration."""

    def __init__(self, claude_home: Path, backups_dir: Path, config_path: Path | None = None):
        self.claude_home = claude_home
        self.backups_dir = backups_dir
        self._config_path = config_path
        self.history_path = claude_home / "history.jsonl"
        self.projects_dir = claude_home / "projects"

    @property
    def config_path(self) -> Path:
        """Locate ``.claude.json``, which sits beside the configuration directory."""
        if self._config_path is not None:
            return self._config_path
        inside = self.claude_home / ".claude.json"
        return inside if inside.exists() else self.claude_home.parent / (self.claude_home.name + ".json")

    @staticmethod
    def _projects(config: dict) -> dict:
        projects = config.get("projects", {})
        if not isinstance(projects, dict) or any(not isinstance(v, dict) for v in projects.values()):
            raise SwitcherError("projects in .claude.json must map paths to objects; no changes were made.")
        return projects

    @staticmethod
    def _merge_projects(projects: dict) -> tuple[dict, int, int]:
        groups: dict[str, list[str]] = defaultdict(list)
        for key in projects:
            groups[canonical_project(key)].append(key)
        merged, folders, entries = dict(projects), 0, 0
        for keys in groups.values():
            if len(keys) < 2:
                continue
            combined: dict = {}
            # Later updates win per key, so apply the richest record last: a stub
            # the desktop app just created must not overwrite real project state.
            for key in sorted(keys, key=lambda k: (len(projects[k]), k)):
                combined.update(projects[key])
            folders += 1
            for key in keys:
                if merged[key] != combined:
                    merged[key] = copy.deepcopy(combined)
                    entries += 1
        return merged, folders, entries

    def _normalize_history(self) -> tuple[list[str] | None, int]:
        if not self.history_path.exists():
            return None, 0
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            raise SwitcherError("Cannot read history.jsonl; check permissions and UTF-8 encoding.") from None
        records, forms = [], defaultdict(Counter)
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                record = None
            records.append(record)
            if isinstance(record, dict) and isinstance(record.get("project"), str):
                forms[canonical_project(record["project"])][record["project"]] += 1
        # Only folders recorded under more than one spelling are ambiguous; adopt
        # the spelling Claude itself used most, never a spelling we invented.
        preferred = {key: counts.most_common(1)[0][0] for key, counts in forms.items() if len(counts) > 1}
        if not preferred:
            return None, 0
        output, changed = [], 0
        for line, record in zip(lines, records):
            if isinstance(record, dict) and isinstance(record.get("project"), str):
                target = preferred.get(canonical_project(record["project"]))
                if target and record["project"] != target:
                    record["project"] = target
                    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                    changed += 1
            output.append(line)
        return output, changed

    def _transcripts(self, projects: dict) -> tuple[int, list[str]]:
        if not self.projects_dir.is_dir():
            return 0, []
        directories = sorted(p.name for p in self.projects_dir.iterdir() if p.is_dir())
        known = {encode_project_dir(key) for key in projects}
        return len(directories), [name for name in directories if name not in known]

    def _backup(self, config_existed: bool, history_lines: list[str] | None) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        identifier = f"{stamp}-{uuid.uuid4().hex[:8]}"
        target = self.backups_dir / f"history-{identifier}"
        target.mkdir(parents=True, exist_ok=True)
        if config_existed:
            shutil.copy2(self.config_path, target / "claude.json")
        if history_lines is not None:
            shutil.copy2(self.history_path, target / "history.jsonl")
        return identifier

    def repair(self, *, apply: bool = True) -> dict:
        """Merge duplicated project records. Callers must hold the mutation locks."""
        config_existed = self.config_path.exists()
        config = read_object(self.config_path) if config_existed else {}
        projects = self._projects(config)
        merged, folders, entries = self._merge_projects(projects)
        history_lines, history_changed = self._normalize_history()
        directories, orphans = self._transcripts(merged)
        changed = bool(entries or history_changed)
        backup = None
        if changed and apply:
            backup = self._backup(config_existed, history_lines if history_changed else None)
            if entries:
                config["projects"] = merged
                write_object(self.config_path, config)
            if history_changed and history_lines is not None:
                atomic_write(self.history_path, ("\n".join(history_lines) + "\n").encode("utf-8"))
        return {
            "config_file": str(self.config_path),
            "config_present": config_existed,
            "duplicate_folders": folders,
            "project_entries_updated": entries,
            "history_entries_normalized": history_changed,
            "transcript_directories": directories,
            "transcript_directories_without_project_entry": orphans,
            "applied": bool(changed and apply),
            "backup": backup,
            "note": "Conversation transcripts are keyed by working directory only and are never rewritten or filtered by provider.",
        }

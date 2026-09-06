"""Conservative reconciliation of Claude project metadata, not transcripts.

Claude does not participate in the switcher's locks. Explicit repair requires
closing Claude; snapshot checks detect intervening changes but cannot provide a
transaction against an uncooperative writer across multiple files.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .storage import SwitcherError, atomic_write, parse_json


# Missing security fields do not imply approval to copy them. Only known
# session bookkeeping may fill a missing field automatically.
MERGEABLE_METADATA = {"lastSessionId", "lastCost", "lastDuration", "lastAPIDuration",
                      "lastTotalInputTokens", "lastTotalOutputTokens"}


def encode_project_dir(path: str) -> str:
    """Legacy encoding, used only for advisory inventory reporting."""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def canonical_project(path: str) -> str:
    """Normalize Windows separator/drive spelling, preserving POSIX backslashes."""
    if re.match(r"^[a-zA-Z]:[\\/]", path):
        normalized = path[0].upper() + path[1:].replace("\\", "/")
        return normalized.rstrip("/") if len(normalized.rstrip("/")) > 2 else normalized[:3]
    if path.startswith("\\\\"):
        return path.replace("\\", "/").rstrip("/")
    return path.rstrip("/") or path


def _identity(path: Path) -> tuple | None:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return None
    if path.is_symlink() or not path.is_file() or stat.st_nlink > 1:
        raise SwitcherError("History repair requires regular, non-linked configuration files.")
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@dataclass(frozen=True)
class Snapshot:
    path: Path
    data: bytes | None
    identity: tuple | None

    @classmethod
    def read(cls, path: Path) -> Snapshot:
        before = _identity(path)
        data = path.read_bytes() if before is not None else None
        snapshot = cls(path, data, before)
        snapshot.check()
        return snapshot

    def check(self) -> None:
        if _identity(self.path) != self.identity or (
            self.data is not None and self.path.read_bytes() != self.data
        ):
            raise SwitcherError("Claude history changed during this operation. Close Claude and retry.")


class HistoryRepair:
    def __init__(self, claude_home: Path, backups_dir: Path, config_path: Path | None = None):
        self.claude_home = claude_home
        self.backups_dir = backups_dir
        self._config_path = config_path
        self.history_path = claude_home / "history.jsonl"
        self.projects_dir = claude_home / "projects"

    @property
    def config_path(self) -> Path:
        if self._config_path is not None:
            return self._config_path
        inside = self.claude_home / ".claude.json"
        return inside if inside.exists() or inside.is_symlink() else self.claude_home.parent / (self.claude_home.name + ".json")

    @staticmethod
    def _projects(config: dict) -> dict:
        projects = config.get("projects", {})
        if not isinstance(projects, dict) or any(not isinstance(v, dict) for v in projects.values()):
            raise SwitcherError("projects in .claude.json must map paths to objects; no changes were made.")
        return projects

    @staticmethod
    def _merge_projects(projects: dict) -> tuple[dict, int, int, list[dict]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for key in projects:
            groups[canonical_project(key)].append(key)
        merged, folders, entries, conflicts = copy.deepcopy(projects), 0, 0, []
        for keys in groups.values():
            if len(keys) < 2:
                continue
            folders += 1
            combined, conflicting_fields = {}, 0
            for field in sorted({field for key in keys for field in projects[key]}):
                values = [projects[key][field] for key in keys if field in projects[key]]
                # Distinguish true from 1, including nested data.
                encoded = [json.dumps(v, sort_keys=True, ensure_ascii=True, allow_nan=False) for v in values]
                if len(set(encoded)) > 1 or (len(values) != len(keys) and field not in MERGEABLE_METADATA):
                    conflicting_fields += 1
                else:
                    combined[field] = copy.deepcopy(values[0])
            if conflicting_fields:
                # Preserve the whole folder. Do not expose secret-bearing values
                # or arbitrary configuration keys in diagnostics.
                conflicts.append({"paths": keys, "field_count": conflicting_fields})
                continue
            for key in keys:
                if merged[key] != combined:
                    merged[key] = copy.deepcopy(combined)
                    entries += 1
        return merged, folders, entries, conflicts

    @staticmethod
    def _normalize_history(data: bytes | None, excluded: set[str]) -> tuple[bytes | None, int]:
        if data is None:
            return None, 0
        try:
            data.decode("utf-8-sig")
        except UnicodeError:
            raise SwitcherError("Cannot read history.jsonl; check UTF-8 encoding.") from None
        bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
        chunks = data[len(bom):].split(b"\n")
        records, forms = [], defaultdict(Counter)
        for line in chunks:
            try:
                record = parse_json(line.decode("utf-8"))
            except SwitcherError:
                record = None
            records.append(record)
            if isinstance(record, dict) and isinstance(record.get("project"), str):
                key = canonical_project(record["project"])
                if key not in excluded:
                    forms[key][record["project"]] += 1
        preferred = {key: counts.most_common(1)[0][0] for key, counts in forms.items() if len(counts) > 1}
        changed = 0
        for index, record in enumerate(records):
            if isinstance(record, dict) and isinstance(record.get("project"), str):
                target = preferred.get(canonical_project(record["project"]))
                if target and record["project"] != target:
                    record["project"] = target
                    ending = b"\r" if chunks[index].endswith(b"\r") else b""
                    chunks[index] = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + ending
                    changed += 1
        return (bom + b"\n".join(chunks) if changed else None), changed

    def _transcripts(self, projects: dict) -> tuple[int, list[str]]:
        if not self.projects_dir.is_dir():
            return 0, []
        directories = sorted(p.name for p in self.projects_dir.iterdir() if p.is_dir())
        known = {encode_project_dir(key) for key in projects}
        return len(directories), [name for name in directories if name not in known]

    def _backup(self, snapshots: list[Snapshot]) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        identifier = f"{stamp}-{uuid.uuid4().hex[:8]}"
        target = self.backups_dir / f"history-{identifier}"
        for snapshot, name in zip(snapshots, ("claude.json", "history.jsonl")):
            if snapshot.data is not None:
                atomic_write(target / name, snapshot.data)
        return identifier

    def repair(self, *, apply: bool = True) -> dict:
        """Call with mutation locks and Claude stopped when applying changes."""
        config_path = self.config_path
        snapshots = [Snapshot.read(config_path), Snapshot.read(self.history_path)]
        try:
            config = parse_json(snapshots[0].data.decode("utf-8-sig")) if snapshots[0].data is not None else {}
        except UnicodeError:
            raise SwitcherError("Cannot read .claude.json; check UTF-8 encoding.") from None
        projects = self._projects(config)
        merged, folders, entries, conflicts = self._merge_projects(projects)
        excluded = {canonical_project(item["paths"][0]) for item in conflicts}
        history_data, history_changed = self._normalize_history(snapshots[1].data, excluded)
        directories, orphans = self._transcripts(merged)
        changed = bool(entries or history_changed)
        backup, written = None, []

        def check_sources():
            if self.config_path != config_path:
                raise SwitcherError("Claude configuration location changed. Close Claude and retry.")
            for snapshot in snapshots:
                snapshot.check()

        check_sources()
        if changed and apply:
            backup = self._backup(snapshots)
            replacements = []
            if entries:
                config["projects"] = merged
                replacements.append((0, (json.dumps(config, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()))
            if history_changed:
                replacements.append((1, history_data))
            try:
                for index, data in replacements:
                    # Validate all sources after staging, immediately before replace.
                    atomic_write(snapshots[index].path, data, before_replace=check_sources)
                    written.append("claude.json" if index == 0 else "history.jsonl")
                    snapshots[index] = Snapshot.read(snapshots[index].path)
                    if snapshots[index].data != data:
                        raise SwitcherError("Claude changed a repaired file.")
                check_sources()
            except (OSError, SwitcherError):
                progress = ", ".join(written) if written else "none"
                raise SwitcherError(
                    f"History repair stopped because a file changed or could not be written. "
                    f"Files already replaced: {progress}. Original backup: history-{backup}. "
                    "Close Claude, inspect the current files and backup before retrying; no automatic rollback was attempted."
                ) from None
        return {
            "config_file": str(config_path),
            "config_present": snapshots[0].data is not None,
            "duplicate_folders": folders,
            "project_entries_updated": entries,
            "history_entries_normalized": history_changed,
            "conflicts": conflicts,
            "pending_changes": changed,
            "transcript_directories": directories,
            "transcript_directories_without_project_entry": orphans,
            "applied": bool(changed and apply),
            "backup": backup,
            "note": "Only project metadata and prompt path labels are reconciled. Transcripts are never read or rewritten; history visibility is not guaranteed.",
        }

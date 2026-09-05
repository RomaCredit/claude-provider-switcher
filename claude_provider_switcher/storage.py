"""Private atomic files and a per-configuration mutation lock."""

from __future__ import annotations

import csv
import functools
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SwitcherError(Exception):
    """User-facing error whose message must not contain credentials."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(
            text, object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite number")),
        )
    except (ValueError, TypeError):
        raise SwitcherError("Invalid JSON object; the file was not modified.") from None
    if not isinstance(data, dict):
        raise SwitcherError("Expected a JSON object; the file was not modified.")
    return data


def read_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return parse_json(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError):
        raise SwitcherError("Cannot read configuration file; check permissions and UTF-8 encoding.") from None


@functools.lru_cache(maxsize=1)
def _windows_sid() -> str:
    try:
        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        sid = next(csv.reader(result.stdout.strip().splitlines()))[1]
        if not sid.startswith("S-1-"):
            raise ValueError()
        return sid
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        raise SwitcherError("Cannot determine the Windows account for private file permissions.") from None


def private_file(path: Path) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{_windows_sid()}:F"],
                capture_output=True, check=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            raise SwitcherError("Cannot restrict the file ACL; refusing to store sensitive data.") from None
    else:
        path.chmod(0o600)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".ccs-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            private_file(Path(temporary))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_object(path: Path, data: dict[str, Any]) -> None:
    atomic_write(path, (json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode())


@contextmanager
def mutation_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / ".ccs.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SwitcherError(
            "Another switcher operation holds .ccs.lock. If it crashed, verify no ccs process "
            "is running before removing that lock."
        ) from None
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink()

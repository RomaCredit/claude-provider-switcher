from __future__ import annotations

import copy
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .credentials import Credentials
from .profiles import COMPATIBILITY_ENV, Profile, Profiles, validate_name
from .storage import SwitcherError, mutation_lock, read_object, write_object


ENV_KEYS = {
    "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_CUSTOM_HEADERS", "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_AWS", "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
    "CLAUDE_CODE_SKIP_VERTEX_AUTH", "CLAUDE_CODE_SKIP_FOUNDRY_AUTH",
    "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_AWS_BASE_URL",
}
TOP_KEYS = {"apiKeyHelper", "model", "modelOverrides", "forceLoginMethod"}


def owned_env(key: str) -> bool:
    return key in ENV_KEYS or key in COMPATIBILITY_ENV or key.startswith("ANTHROPIC_DEFAULT_")


def settings_env(data: dict) -> dict:
    env = data.get("env", {})
    if not isinstance(env, dict) or any(not isinstance(v, str) for v in env.values()):
        raise SwitcherError("settings.json env must contain string values; no changes were made.")
    return env


def relevant_keys(data: dict) -> list[str]:
    return sorted(TOP_KEYS.intersection(data) | {k for k in settings_env(data) if owned_env(k)})


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return "(invalid URL)"
        return f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
    except (ValueError, TypeError):
        return "(invalid URL)"


class Switcher:
    def __init__(self, root: Path | None = None, claude_home: Path | None = None, vault=None):
        self.root = (root or Path(os.environ.get("CLAUDE_PROVIDER_SWITCHER_HOME", "~/.claude-provider-switcher"))).expanduser().resolve()
        self.claude_home = (claude_home or Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"))).expanduser().resolve()
        if self.root == self.claude_home:
            raise SwitcherError("Switcher home and Claude configuration directory must be different.")
        self.settings_path = self.claude_home / "settings.json"
        self.profiles = Profiles(self.root)
        self.credentials = Credentials(self.root, vault=vault)
        self.backups_dir = self.root / "backups"

    def helper_command(self, name: str) -> str:
        validate_name(name)
        args = [
            sys.executable, str(Path(__file__).with_name("credential_helper.py").resolve()),
            str(self.root), name,
        ]
        if os.name == "nt":
            if any(any(c in arg for c in '"%!\r\n') for arg in args):
                raise SwitcherError("Credential helper paths cannot contain quotes, %, ! or newlines on Windows.")
            return " ".join('"' + arg + '"' for arg in args)
        return shlex.join(args)

    def build_settings(self, current: dict, name: str, profile: Profile, *, helper=True) -> dict:
        data = copy.deepcopy(current)
        env = {k: v for k, v in settings_env(data).items() if not owned_env(k)}
        for key in TOP_KEYS:
            data.pop(key, None)
        if profile.type == "api":
            env.update(profile.env)
            env["ANTHROPIC_BASE_URL"] = profile.base_url.rstrip("/")
            env["ANTHROPIC_MODEL"] = profile.model
            # Keep built-in model aliases and background requests on a gateway's
            # configured model, rather than silently selecting an unsupported ID.
            for tier in ("HAIKU", "SONNET", "OPUS"):
                env[f"ANTHROPIC_DEFAULT_{tier}_MODEL"] = profile.model
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = profile.model
            data["model"] = profile.model
            data["forceLoginMethod"] = "console"
            if helper:
                data["apiKeyHelper"] = self.helper_command(name)
        else:
            data["forceLoginMethod"] = "claudeai"
        if env:
            data["env"] = env
        else:
            data.pop("env", None)
        return data

    def _read_settings(self):
        if self.settings_path.is_symlink():
            raise SwitcherError("Refusing to replace a settings.json symlink; use the real configuration directory.")
        data = read_object(self.settings_path)
        settings_env(data)
        return data

    def _backup(self, data: dict, existed: bool) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        identifier = f"{stamp}-{uuid.uuid4().hex[:8]}"
        write_object(self.backups_dir / f"{identifier}.json", {
            "version": 1, "claude_home": str(self.claude_home),
            "settings_existed": existed, "settings": data,
        })
        return identifier

    def use(self, name: str) -> str:
        self.profiles.load()
        with mutation_lock(self.root), mutation_lock(self.claude_home):
            profile = self.profiles.get(name)
            if profile.type == "api" and not self.credentials.get(name):
                raise SwitcherError("Credential unavailable. Run 'ccs profile key <name>' first.")
            existed = self.settings_path.exists()
            current = self._read_settings()
            updated = self.build_settings(current, name, profile)
            backup = self._backup(current, existed)
            if self._read_settings() != current or self.settings_path.exists() != existed:
                raise SwitcherError("Claude settings changed during this operation. Retry after closing Claude Code.")
            write_object(self.settings_path, updated)
        return backup

    def backups(self) -> list[str]:
        return sorted(p.stem for p in self.backups_dir.glob("*.json") if re.fullmatch(r"\d{8}T\d{12}Z-[0-9a-f]{8}", p.stem))

    def restore(self, identifier: str) -> str:
        if identifier not in self.backups():
            raise SwitcherError("Unknown backup ID. Run 'ccs backup list'.")
        record = read_object(self.backups_dir / f"{identifier}.json")
        if (
            record.get("version") != 1 or record.get("claude_home") != str(self.claude_home)
            or type(record.get("settings_existed")) is not bool
            or not isinstance(record.get("settings"), dict)
        ):
            raise SwitcherError("Backup is invalid or belongs to another Claude configuration directory.")
        settings_env(record["settings"])
        with mutation_lock(self.root), mutation_lock(self.claude_home):
            existed = self.settings_path.exists()
            current = self._read_settings()
            undo = self._backup(current, existed)
            if self._read_settings() != current or self.settings_path.exists() != existed:
                raise SwitcherError("Claude settings changed during this operation. Retry after closing Claude Code.")
            if record["settings_existed"]:
                write_object(self.settings_path, record["settings"])
            elif self.settings_path.exists():
                self.settings_path.unlink()
        return undo

    def configured_name(self, data: dict) -> str | None:
        actual = {key: data[key] for key in TOP_KEYS if key in data}
        actual["env"] = {key: value for key, value in settings_env(data).items() if owned_env(key)}
        for name, profile in self.profiles.load().items():
            expected = self.build_settings({}, name, profile)
            expected.setdefault("env", {})
            if actual == expected:
                return name
        return None

    def status(self) -> dict:
        data = self._read_settings()
        name = self.configured_name(data)
        return {
            "configured_profile": name or "unmanaged",
            "settings_file": str(self.settings_path),
            "settings_present": self.settings_path.exists(),
            "base_url_origin": safe_url(settings_env(data)["ANTHROPIC_BASE_URL"]) if settings_env(data).get("ANTHROPIC_BASE_URL") else "default",
            "credential_backend": self.credentials.backend(name) if name else "unmanaged",
            "helper": "configured" if data.get("apiKeyHelper") else "absent",
            "note": "Local configuration only; this does not verify subscription login or the running Claude session.",
        }

    def doctor(self, project: Path, environ=None) -> list[dict]:
        environ = os.environ if environ is None else environ
        findings = []
        inherited = sorted(k for k in environ if owned_env(k) and environ[k])
        if inherited:
            findings.append({"source": "shell", "keys": inherited, "issue": "Inherited provider settings may conflict; use 'ccs run' or clear them in your shell."})
        files = []
        # Show potential project overrides; Claude's actual loading scope is version dependent.
        project = project.resolve()
        for parent in (project, *project.parents):
            for name in ("settings.json", "settings.local.json"):
                candidate = parent / ".claude" / name
                if candidate != self.settings_path and candidate.exists():
                    files.append(candidate)
            if (parent / ".git").exists():
                break
        managed_dir = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "ClaudeCode"
            if os.name == "nt" else
            Path("/Library/Application Support/ClaudeCode") if sys.platform == "darwin" else Path("/etc/claude-code")
        )
        files.extend([managed_dir / "managed-settings.json", self.claude_home / "managed-settings.json"])
        fragment_dir = managed_dir / "managed-settings.d"
        if fragment_dir.exists():
            files.extend(sorted(fragment_dir.glob("*.json")))
        for path in dict.fromkeys(files):
            if not path.exists():
                continue
            try:
                keys = relevant_keys(read_object(path))
                if keys:
                    findings.append({"source": str(path), "keys": keys, "issue": "Potential higher-priority provider configuration; file was not modified."})
            except SwitcherError:
                findings.append({"source": str(path), "keys": [], "issue": "Cannot inspect invalid or unreadable settings."})
        data = self._read_settings()
        permissions = data.get("permissions", {})
        if isinstance(permissions, dict) and permissions.get("defaultMode") == "bypassPermissions":
            findings.append({"source": "user settings", "keys": ["permissions.defaultMode"], "issue": "Permission bypass is configured. The switcher does not enable or disable it."})
        if not shutil.which("claude"):
            findings.append({"source": "PATH", "keys": [], "issue": "Claude Code executable not found."})
        return findings

    def run(self, name: str, arguments: list[str]) -> int:
        profile = self.profiles.get(name)
        blocked = ("--settings", "--setting-sources", "--model", "--bare", "--resume", "--continue")
        if any(arg in {"-c", "-r"} or any(arg == flag or arg.startswith(flag + "=") for flag in blocked) for arg in arguments):
            raise SwitcherError("run does not accept provider/settings overrides or resume flags; use Claude directly for these.")
        executable = (shutil.which("claude.exe") or shutil.which("claude.cmd")) if os.name == "nt" else shutil.which("claude")
        if not executable:
            raise SwitcherError("Claude Code is not installed or not on PATH.")
        if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")) and any(any(c in arg for c in '&|<>^%!\r\n"') for arg in arguments):
            raise SwitcherError("Unsafe cmd.exe argument. Start Claude without these shell metacharacters.")
        data = self.build_settings(self._read_settings(), name, profile, helper=False)
        env = {k: v for k, v in os.environ.items() if not owned_env(k)}
        env["CLAUDE_CONFIG_DIR"] = str(self.claude_home)
        if profile.type == "api":
            secret = self.credentials.get(name)
            if not secret:
                raise SwitcherError("Credential unavailable. Set it with 'ccs profile key'.")
            env["ANTHROPIC_API_KEY" if profile.auth_kind == "api_key" else "ANTHROPIC_AUTH_TOKEN"] = secret
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Copy sanitized user customizations and disable project/local merging.
        # Managed organization policy still applies and is never bypassed.
        with tempfile.TemporaryDirectory(prefix="run-", dir=self.root) as temporary:
            path = Path(temporary) / "settings.json"
            write_object(path, data)
            return subprocess.call(
                [executable, "--setting-sources=", "--settings", str(path), *arguments],
                env=env,
            )

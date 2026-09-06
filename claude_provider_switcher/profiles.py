from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .storage import SwitcherError, atomic_write, mutation_lock, read_object, write_object


SCHEMA_VERSION = 2
COMPATIBILITY_ENV = {
    "CLAUDE_CODE_ATTRIBUTION_HEADER",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS",
}


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise SwitcherError("Profile names must be 1-64 letters, digits, underscores or hyphens.")


@dataclass(frozen=True)
class Profile:
    type: str
    base_url: str = ""
    model: str = ""
    auth_kind: str = "api_key"
    env: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if any(not isinstance(value, str) for value in (self.type, self.base_url, self.model, self.auth_kind)):
            raise SwitcherError("Profile fields must be strings.")
        if (
            not isinstance(self.env, dict)
            or set(self.env) - COMPATIBILITY_ENV
            or any(not isinstance(v, str) or v not in {"0", "1"} for v in self.env.values())
        ):
            raise SwitcherError("Profile env allows only documented compatibility flags with string values 0 or 1; credentials must use 'profile key'.")
        if self.type not in {"subscription", "api"}:
            raise SwitcherError("Profile type must be subscription or api.")
        if self.auth_kind not in {"api_key", "auth_token"}:
            raise SwitcherError("Auth kind must be api_key or auth_token.")
        if self.type == "subscription":
            if self.base_url or self.model or self.auth_kind != "api_key" or self.env:
                raise SwitcherError("Subscription profiles cannot specify API settings.")
            return
        try:
            url = urlsplit(self.base_url)
            port = url.port
        except ValueError:
            raise SwitcherError("Invalid provider base URL.") from None
        if (
            url.scheme not in {"https", "http"} or not url.hostname
            or url.username is not None or url.password is not None
            or url.query or url.fragment
            or any(c.isspace() or ord(c) < 32 for c in self.base_url)
            or (port is not None and port == 0)
        ):
            raise SwitcherError("Base URL must be HTTP(S), without credentials, query or fragment.")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SwitcherError("Remote providers require HTTPS; HTTP is allowed only on loopback.")
        if self.base_url.rstrip("/").endswith(("/messages", "/models")):
            raise SwitcherError("Use a provider base URL, not an endpoint URL.")
        if not self.model or len(self.model) > 200 or any(c.isspace() or ord(c) < 32 for c in self.model):
            raise SwitcherError("An API profile requires a model ID without whitespace.")


PRESET_ADDITIONS = {
    2: {
        "apimaster": Profile(
            "api", "https://apimaster.ai", "claude-sonnet-4-6", "auth_token",
            {"CLAUDE_CODE_ATTRIBUTION_HEADER": "0", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"},
        ),
    },
}

DEFAULTS = {
    "official": Profile("subscription"),
    "anthropic": Profile("api", "https://api.anthropic.com", "claude-sonnet-4-6"),
    **PRESET_ADDITIONS[2],
}


class Profiles:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "profiles.json"

    def load(self) -> dict[str, Profile]:
        if not self.path.exists():
            with mutation_lock(self.root):
                if not self.path.exists():
                    self.save(DEFAULTS)
        raw = read_object(self.path)
        result = self._decode(raw)
        if raw["version"] < SCHEMA_VERSION:
            with mutation_lock(self.root):
                raw = read_object(self.path)
                result = self._decode(raw)
                if raw["version"] < SCHEMA_VERSION:
                    # Track migration in the schema so deleted presets stay deleted.
                    for version in range(raw["version"] + 1, SCHEMA_VERSION + 1):
                        for name, profile in PRESET_ADDITIONS.get(version, {}).items():
                            result.setdefault(name, profile)
                    backup = self.root / f"profiles-v{raw['version']}-{uuid.uuid4().hex}.backup.json"
                    atomic_write(backup, self.path.read_bytes())
                    self.save(result)
        return result

    @staticmethod
    def _decode(raw: dict) -> dict[str, Profile]:
        if set(raw) != {"version", "profiles"} or type(raw["version"]) is not int or raw["version"] not in {1, SCHEMA_VERSION}:
            raise SwitcherError("Unsupported profiles file schema; expected version 1 or 2.")
        if not isinstance(raw["profiles"], dict):
            raise SwitcherError("profiles must be a JSON object.")
        result = {}
        for name, fields in raw["profiles"].items():
            validate_name(name)
            if not isinstance(fields, dict) or set(fields) - {"type", "base_url", "model", "auth_kind", "env"}:
                raise SwitcherError("Unknown profile field. Store credentials with 'profile key', not in profiles.json.")
            try:
                profile = Profile(**fields)
            except TypeError:
                raise SwitcherError("Invalid profile fields.") from None
            profile.validate()
            result[name] = profile
        return result

    def save(self, profiles: dict[str, Profile]) -> None:
        for name, profile in profiles.items():
            validate_name(name)
            profile.validate()
        write_object(self.path, {"version": SCHEMA_VERSION, "profiles": {k: asdict(v) for k, v in profiles.items()}})

    def get(self, name: str) -> Profile:
        validate_name(name)
        profiles = self.load()
        if name not in profiles:
            raise SwitcherError("Profile does not exist. Run 'ccs profile list'.")
        return profiles[name]

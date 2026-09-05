from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .storage import SwitcherError, mutation_lock, read_object, write_object


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise SwitcherError("Profile names must be 1-64 letters, digits, underscores or hyphens.")


@dataclass(frozen=True)
class Profile:
    type: str
    base_url: str = ""
    model: str = ""
    auth_kind: str = "api_key"

    def validate(self) -> None:
        if any(not isinstance(value, str) for value in asdict(self).values()):
            raise SwitcherError("Profile fields must be strings.")
        if self.type not in {"subscription", "api"}:
            raise SwitcherError("Profile type must be subscription or api.")
        if self.auth_kind not in {"api_key", "auth_token"}:
            raise SwitcherError("Auth kind must be api_key or auth_token.")
        if self.type == "subscription":
            if self.base_url or self.model or self.auth_kind != "api_key":
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


DEFAULTS = {
    "official": Profile("subscription"),
    "anthropic": Profile("api", "https://api.anthropic.com", "claude-sonnet-4-6"),
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
        if set(raw) != {"version", "profiles"} or type(raw["version"]) is not int or raw["version"] != 1:
            raise SwitcherError("Unsupported profiles file schema; expected version 1.")
        if not isinstance(raw["profiles"], dict):
            raise SwitcherError("profiles must be a JSON object.")
        result = {}
        for name, fields in raw["profiles"].items():
            validate_name(name)
            if not isinstance(fields, dict) or set(fields) - {"type", "base_url", "model", "auth_kind"}:
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
        write_object(self.path, {"version": 1, "profiles": {k: asdict(v) for k, v in profiles.items()}})

    def get(self, name: str) -> Profile:
        validate_name(name)
        profiles = self.load()
        if name not in profiles:
            raise SwitcherError("Profile does not exist. Run 'ccs profile list'.")
        return profiles[name]

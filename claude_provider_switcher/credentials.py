"""Credential providers; no secrets are included in error messages."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from .profiles import validate_name
from .storage import SwitcherError, read_object, write_object


def validate_secret(secret: str) -> None:
    if not isinstance(secret, str) or not secret or len(secret) > 2048:
        raise SwitcherError("Credential must be nonempty and at most 2048 characters.")
    if any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise SwitcherError("Credential must be printable ASCII without whitespace.")


def mask_secret(secret: str | None) -> str:
    if not secret:
        return "missing"
    return "****" if len(secret) <= 12 else secret[:4] + "..." + secret[-4:]


class SystemVault:
    def _windows(self):
        from ctypes import wintypes

        class Credential(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
            ]

        api = ctypes.WinDLL("Advapi32", use_last_error=True)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api, Credential

    def get(self, service: str) -> str | None:
        if os.name == "nt":
            api, credential = self._windows()
            pointer = ctypes.POINTER(credential)()
            if not api.CredReadW(service, 1, 0, ctypes.byref(pointer)):
                return None
            try:
                return ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode("utf-16-le")
            finally:
                api.CredFree(pointer)
        if sys.platform == "darwin":
            result = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-a", "ccs", "-w"],
                capture_output=True, text=True, timeout=15,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        return None

    def set(self, service: str, secret: str) -> bool:
        if os.name == "nt":
            api, credential = self._windows()
            blob = (ctypes.c_ubyte * len(secret.encode("utf-16-le"))).from_buffer_copy(secret.encode("utf-16-le"))
            item = credential()
            item.Type, item.TargetName, item.UserName = 1, service, "ccs"
            item.CredentialBlobSize, item.CredentialBlob, item.Persist = len(blob), blob, 2
            return bool(api.CredWriteW(ctypes.byref(item), 0))
        if sys.platform == "darwin":
            # security -i reads the secret over stdin, not from process arguments.
            import shlex
            command = shlex.join(["add-generic-password", "-U", "-s", service, "-a", "ccs", "-w", secret])
            result = subprocess.run(
                ["security", "-i"], input=command + "\n", capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0 and self.get(service) == secret
        return False

    def delete(self, service: str) -> None:
        if os.name == "nt":
            api, _ = self._windows()
            api.CredDeleteW(service, 1, 0)
        elif sys.platform == "darwin":
            subprocess.run(
                ["security", "delete-generic-password", "-s", service, "-a", "ccs"],
                capture_output=True, timeout=15,
            )


class Credentials:
    def __init__(self, root: Path, vault=None):
        self.root = root
        self.path = root / "credentials.json"
        self.vault = vault if vault is not None else SystemVault()
        # Separate custom/test installations so they cannot replace a user's key.
        import hashlib
        self.namespace = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]

    def service(self, name: str) -> str:
        validate_name(name)
        return f"claude-provider-switcher:{self.namespace}:{name}"

    def _read(self):
        raw = read_object(self.path)
        for name, item in raw.items():
            validate_name(name)
            if not isinstance(item, dict) or item.get("backend") not in {"file", "system"}:
                raise SwitcherError("Invalid credential store.")
            if item["backend"] == "file":
                validate_secret(item.get("secret"))
        return raw

    def get(self, name: str) -> str | None:
        item = self._read().get(name)
        if item is None:
            return None
        if item["backend"] == "file":
            return item["secret"]
        try:
            result = self.vault.get(self.service(name))
            if result:
                validate_secret(result)
            return result
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def backend(self, name: str) -> str:
        return self._read().get(name, {}).get("backend", "missing")

    def set(self, name: str, secret: str) -> str:
        validate_secret(secret)
        service = self.service(name)
        records = self._read()
        try:
            stored = self.vault.set(service, secret)
        except (OSError, ValueError, subprocess.SubprocessError):
            stored = False
        # The backend marker is authoritative: a stale system key never shadows
        # a newer file fallback after the keychain becomes available again.
        records[name] = {"backend": "system"} if stored else {"backend": "file", "secret": secret}
        write_object(self.path, records)
        return records[name]["backend"]

    def delete(self, name: str) -> None:
        records = self._read()
        if name in records:
            del records[name]
            write_object(self.path, records)
        try:
            self.vault.delete(self.service(name))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

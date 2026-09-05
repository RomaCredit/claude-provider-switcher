"""Explicit probes only; never include server response bodies in diagnostics."""

import json
import urllib.error
import urllib.request

from .credentials import validate_secret
from .profiles import Profile
from .storage import SwitcherError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint(base_url: str, path: str) -> str:
    root = base_url.rstrip("/")
    return root + ("" if root.endswith("/v1") else "/v1") + "/" + path


def probe(profile: Profile, secret: str, *, inference=False, timeout=15, opener=None) -> dict:
    profile.validate()
    if profile.type != "api":
        raise SwitcherError("Subscription profiles cannot be API-tested.")
    validate_secret(secret)
    headers = {"anthropic-version": "2023-06-01", "Accept": "application/json"}
    if profile.auth_kind == "api_key":
        headers["x-api-key"] = secret
    else:
        headers["Authorization"] = f"Bearer {secret}"
    body = None
    if inference:
        headers["Content-Type"] = "application/json"
        body = json.dumps({
            "model": profile.model, "max_tokens": 1,
            "messages": [{"role": "user", "content": "."}],
        }).encode()
    request = urllib.request.Request(
        endpoint(profile.base_url, "messages" if inference else "models"),
        data=body, headers=headers,
    )
    opener = opener or urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise SwitcherError("Provider response exceeded the 1 MiB limit.")
            payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError()
        if inference:
            if payload.get("type") != "message" or not isinstance(payload.get("content"), list):
                raise ValueError()
        elif not isinstance(payload.get("data"), list):
            raise ValueError()
        return {
            "ok": True,
            "test": "inference" if inference else "models",
            "note": "A basic probe does not validate streaming, tools, or every Claude Code feature.",
        }
    except urllib.error.HTTPError as exc:
        hints = {
            401: "Credential rejected; check auth_kind.",
            403: "Access denied by provider.",
            404: "Endpoint unavailable; gateways need not support /models.",
            429: "Rate or quota limit reached.",
        }
        message = "Redirect refused to avoid forwarding credentials." if 300 <= exc.code < 400 else hints.get(exc.code, "Provider returned an HTTP error.")
        exc.close()
        raise SwitcherError(f"HTTP {exc.code}: {message}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SwitcherError("Connection failed; check network, proxy, TLS and provider address.") from None
    except (ValueError, UnicodeError):
        raise SwitcherError("Unexpected provider response format; response body omitted.") from None

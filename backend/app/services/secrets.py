"""Resolve and redact secret references without persisting values."""

from __future__ import annotations

import os
import re

SECRET_REF_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "apikey",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "x-access-token",
}
class SecretError(Exception):
    """Raised when a required secret reference cannot be used."""


def resolve_secret(secret_ref: str) -> str:
    if not SECRET_REF_PATTERN.fullmatch(secret_ref):
        raise SecretError("Secret references must be uppercase environment variable names.")
    value = os.getenv(secret_ref)
    if value is None or value == "":
        raise SecretError(f"Required secret '{secret_ref}' is unavailable.")
    return value


def is_sensitive_header(name: str) -> bool:
    lowered = name.strip().casefold()
    return lowered in SENSITIVE_HEADER_NAMES or is_sensitive_name(name)


def is_sensitive_name(name: str) -> bool:
    lowered = name.strip().casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    compact = normalized.replace("_", "")
    tokens = set(normalized.split("_"))
    sensitive_tokens = {"auth", "authorization", "credential", "password", "passwd", "secret", "signature", "token"}
    sensitive_compact = {"apikey", "accesstoken", "authtoken", "clientsecret", "privatekey"}
    return bool(tokens.intersection(sensitive_tokens)) or any(
        marker in compact for marker in sensitive_compact
    )


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {name: "[redacted]" if is_sensitive_header(name) else value for name, value in headers.items()}


def sanitized_url(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = rendered_host
    if parsed.port:
        netloc = f"{rendered_host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))

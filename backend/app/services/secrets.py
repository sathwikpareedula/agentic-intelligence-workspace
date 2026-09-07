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
    return lowered in SENSITIVE_HEADER_NAMES or "token" in lowered or "secret" in lowered or "password" in lowered


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {name: "[redacted]" if is_sensitive_header(name) else value for name, value in headers.items()}


def sanitized_url(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))

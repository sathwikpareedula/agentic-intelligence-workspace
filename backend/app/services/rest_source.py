"""Controlled GET-only REST JSON import with SSRF protections."""

from __future__ import annotations

import ipaddress
import json
import socket
import ssl
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from app.models.datasets import DatasetProvenance
from app.models.sources import DatasetPayload, ImportedDataset, RestSourceConfig
from app.services.datasets import MAX_UPLOAD_BYTES, inspect_dataset, loaded_from_frame, profile_dataset
from app.services.json_adapter import JsonAdapterError, frame_from_json
from app.services.secrets import SecretError, is_sensitive_name, resolve_secret, sanitized_url

MAX_REDIRECTS = 3
BLOCKED_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "kubernetes.default.svc",
    "instance-data",
}
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("2001:db8::/32"),
]
METADATA_NETWORKS = [ipaddress.ip_network("169.254.169.254/32"), ipaddress.ip_network("fd00:ec2::254/128")]


class RestSourceError(Exception):
    """User-facing REST connector failure."""


def import_rest(config: RestSourceConfig, *, allow_private: bool = False) -> ImportedDataset:
    url = _compose_url(config)
    headers = _resolved_headers(config)
    status, content_type, body, final_url = _get(
        url,
        headers,
        config.timeout_seconds,
        allow_private,
        secret_header_names=set(config.header_secret_refs),
    )
    if status >= 400:
        raise RestSourceError(f"The REST source returned HTTP {status}.")
    if not _json_content_type(content_type):
        raise RestSourceError("REST responses must use a JSON content type.")
    if len(body) > MAX_UPLOAD_BYTES:
        raise RestSourceError(f"REST response exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")
    try:
        frame = frame_from_json(body, config.records_key)
    except JsonAdapterError as exc:
        raise RestSourceError(str(exc)) from exc
    safe_url = sanitized_url(final_url)
    provenance = DatasetProvenance(
        source_type="rest",
        identity=f"rest:{safe_url}",
        display_name=urlsplit(safe_url).path.rsplit("/", 1)[-1] or "rest_import",
        retrieved_at=datetime.now(timezone.utc),
        config_fingerprint=_fingerprint(config, safe_url),
        row_count=len(frame),
        details={
            "method": "GET",
            "url": safe_url,
            "status": status,
            "content_type": content_type.split(";")[0].strip(),
            "secret_header_refs": ",".join(sorted(config.header_secret_refs)),
        },
    )
    dataset = loaded_from_frame("rest_import.csv", "csv", frame, provenance)
    content = frame.to_csv(index=False).encode("utf-8")
    import base64

    return ImportedDataset(
        inspection=inspect_dataset(dataset),
        profile=profile_dataset(dataset),
        provenance=provenance,
        dataset=DatasetPayload(
            filename="rest_import.csv",
            media_type="text/csv",
            content_base64=base64.b64encode(content).decode("ascii"),
        ),
    )


def _compose_url(config: RestSourceConfig) -> str:
    parsed = urlsplit(config.url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update(config.query)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(existing), ""))


def _resolved_headers(config: RestSourceConfig) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "agentic-intelligence-workspace/phase2"}
    for name, ref in config.header_secret_refs.items():
        try:
            value = resolve_secret(ref)
        except SecretError as exc:
            raise RestSourceError(str(exc)) from exc
        if "\r" in value or "\n" in value:
            raise RestSourceError(f"Secret reference '{ref}' cannot be used as a single-line HTTP header.")
        headers[name] = value
    return headers


def _get(
    url: str,
    headers: dict[str, str],
    timeout: float,
    allow_private: bool,
    *,
    secret_header_names: set[str] | None = None,
) -> tuple[int, str, bytes, str]:
    current = url
    previous_origin = None
    has_secret_headers = bool(secret_header_names)
    for _ in range(MAX_REDIRECTS + 1):
        parsed = _validate_url(current, allow_private)
        origin = _origin(parsed)
        if previous_origin is not None and origin != previous_origin and has_secret_headers:
            raise RestSourceError("Refusing to follow a cross-origin redirect with secret-bearing headers.")
        hostname = _normalized_hostname(parsed)
        ip = _resolve_safe_ip(hostname, allow_private)
        if parsed.scheme != "https":
            if not allow_private:
                raise RestSourceError("HTTPS is required unless private REST targets are explicitly enabled.")
            if not _is_private_address(ip):
                raise RestSourceError("HTTP is allowed only for explicitly enabled private REST targets.")
        status, response_headers, body, location = _request_pinned(parsed, hostname, ip, headers, timeout)
        if status in {301, 302, 303, 307, 308} and location:
            previous_origin = origin
            current = urljoin(current, location)
            continue
        content_type = response_headers.get("content-type", "")
        return status, content_type, body, current
    raise RestSourceError("Too many HTTP redirects.")


def _validate_url(url: str, allow_private: bool):
    if any(ord(character) < 32 or character.isspace() for character in url):
        raise RestSourceError("REST URLs must not contain whitespace or control characters.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise RestSourceError("Only http and https URLs are allowed.")
    if parsed.username or parsed.password:
        raise RestSourceError("URLs must not contain embedded credentials.")
    if any(is_sensitive_name(name) for name, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise RestSourceError("Secret-like REST query parameters are not accepted; use a secret-referenced header.")
    hostname = _normalized_hostname(parsed)
    if not hostname:
        raise RestSourceError("The REST URL is missing a hostname.")
    if hostname in BLOCKED_METADATA_HOSTS or hostname.endswith(".internal"):
        raise RestSourceError("The REST hostname is not allowed.")
    if hostname in {"localhost", "localhost.localdomain"} and not allow_private:
        raise RestSourceError("Private or loopback REST targets are not allowed.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise RestSourceError("The REST URL contains an invalid port.") from exc
    literal = _parse_ip_literal(hostname)
    if literal is not None:
        assert_ip_allowed(literal, allow_private)
    return parsed


def _normalized_hostname(parsed) -> str:
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise RestSourceError("The REST hostname is invalid.") from exc


def _origin(parsed) -> tuple[str, str, int]:
    scheme = parsed.scheme.casefold()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, _normalized_hostname(parsed), port


def _parse_ip_literal(hostname: str):
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def effective_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Unwrap IPv4-mapped IPv6 addresses before SSRF classification."""

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def assert_ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool) -> None:
    candidate = effective_ip(ip)
    if any(candidate in network or ip in network for network in METADATA_NETWORKS):
        raise RestSourceError("Cloud metadata endpoints are not allowed.")
    if candidate.is_unspecified or candidate.is_multicast:
        raise RestSourceError("Private or loopback REST targets are not allowed.")
    blocked = (
        candidate.is_private
        or candidate.is_loopback
        or candidate.is_link_local
        or candidate.is_reserved
        or any(candidate in network or ip in network for network in BLOCKED_NETWORKS)
    )
    if blocked and not allow_private:
        raise RestSourceError("Private or loopback REST targets are not allowed.")
    if blocked and allow_private and any(candidate in network or ip in network for network in METADATA_NETWORKS):
        raise RestSourceError("Cloud metadata endpoints are not allowed.")


def _resolve_safe_ip(hostname: str, allow_private: bool) -> str:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RestSourceError("Could not resolve the REST hostname.") from exc
    addresses = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise RestSourceError("The REST hostname resolved to an invalid address.") from exc
        assert_ip_allowed(ip, allow_private)
        addresses.append(str(ip))
    if not addresses:
        raise RestSourceError("The REST hostname did not resolve to an allowed address.")
    return addresses[0]


def _request_pinned(parsed, hostname: str, ip: str, headers: dict[str, str], timeout: float):
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    host_header = rendered_host if parsed.port is None else f"{rendered_host}:{parsed.port}"
    request_headers = {**headers, "Host": host_header}
    connection: HTTPConnection | None = None
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.settimeout(timeout)
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=hostname)
        connection = HTTPConnection(hostname, port=port, timeout=timeout)
        connection.sock = sock
        connection.request("GET", path, headers=request_headers)
        response = connection.getresponse()
        content_length = response.getheader("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_UPLOAD_BYTES:
                    raise RestSourceError(f"REST response exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")
            except ValueError:
                pass
        body = response.read(MAX_UPLOAD_BYTES + 1)
        if len(body) > MAX_UPLOAD_BYTES:
            raise RestSourceError(f"REST response exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")
        headers_out = {key.casefold(): value for key, value in response.getheaders()}
        location = response.getheader("location")
        status = response.status
        return status, headers_out, body, location
    except RestSourceError:
        raise
    except (TimeoutError, socket.timeout) as exc:
        raise RestSourceError("The REST request timed out.") from exc
    except (OSError, HTTPException, UnicodeError, ValueError, ssl.SSLError) as exc:
        raise RestSourceError("The REST request failed.") from exc
    finally:
        if connection is not None:
            connection.close()


def _json_content_type(content_type: str) -> bool:
    lowered = content_type.casefold().split(";")[0].strip()
    return lowered in {"application/json", "text/json"} or lowered.endswith("+json")


def _is_private_address(value: str) -> bool:
    ip = effective_ip(ipaddress.ip_address(value))
    return ip.is_private or ip.is_loopback or ip.is_link_local or any(
        ip in network for network in BLOCKED_NETWORKS
    )


def _fingerprint(config: RestSourceConfig, safe_url: str) -> str:
    payload = {
        "url": safe_url,
        "method": "GET",
        "records_key": config.records_key,
        "header_secret_refs": sorted(config.header_secret_refs),
        "query": config.query,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

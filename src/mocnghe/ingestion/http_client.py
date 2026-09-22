from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from base64 import b64decode, b64encode
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Self, cast
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field


class UnsafeUrlError(ValueError):
    pass


class FetchRecord(BaseModel):
    method: str
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: bytes
    retrieved_at: datetime
    latency_ms: int
    from_cache: bool = False

    @property
    def text(self) -> str:
        encoding = "utf-8"
        content_type = self.headers.get("content-type", "")
        if "charset=" in content_type:
            encoding = content_type.rsplit("charset=", 1)[-1].split(";", 1)[0].strip()
        return self.body.decode(encoding or "utf-8", errors="replace")

    @property
    def bytes_received(self) -> int:
        return len(self.body)


DnsResolver = Callable[[str], list[str]]


class SafeHttpClient:
    _REQUEST_HEADER_ALLOWLIST: ClassVar[set[str]] = {"accept", "accept-language", "content-type", "user-agent"}
    _RESPONSE_HEADER_ALLOWLIST: ClassVar[set[str]] = {"content-type", "retry-after"}

    def __init__(
        self,
        cache_dir: str | Path,
        allowed_hosts: set[str],
        *,
        transport: httpx.BaseTransport | None = None,
        dns_resolver: DnsResolver | None = None,
        timeout_seconds: float = 8,
        ttl_seconds: int = 3600,
        max_bytes: int = 2_000_000,
        max_redirects: int = 3,
        per_host_spacing_seconds: float = 0.0,
        trust_env: bool = False,
    ) -> None:
        self.cache_dir: Path = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_hosts: set[str] = {host.lower() for host in allowed_hosts}
        self.dns_resolver: DnsResolver = dns_resolver or self._default_resolver
        self.ttl: timedelta = timedelta(seconds=ttl_seconds)
        self.max_bytes: int = max_bytes
        self.max_redirects: int = max_redirects
        self.per_host_spacing_seconds: float = per_host_spacing_seconds
        self._last_request_by_host: dict[str, float] = {}
        self._blocked_hosts: set[str] = set()
        self._client: httpx.Client = httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
            trust_env=trust_env,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        json_body: object | None = None,
        use_cache: bool = True,
    ) -> FetchRecord:
        method = method.upper()
        current_url = self._validate_url(url)
        host = urlsplit(current_url).hostname or ""
        if host in self._blocked_hosts:
            raise UnsafeUrlError(f"host is circuit-blocked: {host}")
        cache_key = self._cache_key(method, current_url, body, json_body)
        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached.model_copy(update={"from_cache": True, "latency_ms": 0})

        self._respect_spacing(host)

        redirects = 0
        started = time.monotonic()
        while True:
            _ = self._validate_url(current_url)
            self._client.cookies.clear()
            request_headers = self._safe_request_headers(headers)
            with self._client.stream(
                method,
                current_url,
                headers=request_headers,
                content=body,
                json=json_body,
            ) as response:
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > self.max_bytes:
                        raise httpx.ReadError("response exceeded configured byte limit")
                    chunks.append(chunk)
                body_bytes = b"".join(chunks)
                response_headers = self._safe_response_headers(response.headers)
                status_code = response.status_code
                response_url = str(response.url)
            self._client.cookies.clear()
            challenge = self._looks_like_challenge(body_bytes)
            if status_code in {403, 429} or challenge:
                self._blocked_hosts.add(urlsplit(current_url).hostname or "")
            if status_code in {301, 302, 303, 307, 308}:
                redirects += 1
                if redirects > self.max_redirects:
                    raise UnsafeUrlError("redirect limit exceeded")
                location = cast(str | None, response_headers.get("location"))
                if not location:
                    raise UnsafeUrlError("redirect missing location")
                current_url = self._validate_url(urljoin(current_url, location))
                self._respect_spacing(urlsplit(current_url).hostname or "")
                if status_code == 303:
                    method = "GET"
                    body = None
                    json_body = None
                continue
            elapsed_ms = int((time.monotonic() - started) * 1000)
            record = FetchRecord(
                method=method,
                url=url,
                final_url=response_url,
                status_code=status_code,
                headers=response_headers,
                body=body_bytes,
                retrieved_at=datetime.now(UTC),
                latency_ms=elapsed_ms,
            )
            if use_cache and status_code < 400 and not challenge:
                self._write_cache(cache_key, record)
            return record

    def _validate_url(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise UnsafeUrlError("only HTTPS URLs are allowed")
        if parts.username or parts.password:
            raise UnsafeUrlError("URL userinfo is not allowed")
        if parts.fragment:
            raise UnsafeUrlError("URL fragments are not allowed")
        if parts.port not in {None, 443}:
            raise UnsafeUrlError("non-default HTTPS ports are not allowed")
        host = (parts.hostname or "").lower()
        if host not in self.allowed_hosts:
            raise UnsafeUrlError(f"host is not allowlisted: {host}")
        try:
            _ = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise UnsafeUrlError("IP literal URLs are not allowed")
        addresses = self.dns_resolver(host)
        if not addresses:
            raise UnsafeUrlError("DNS resolution returned no addresses")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_reserved or ip.is_multicast:
                raise UnsafeUrlError(f"private or local DNS result rejected: {address}")
        return url

    def _safe_request_headers(self, headers: Mapping[str, str] | None) -> dict[str, str]:
        if headers is None:
            return {}
        return {
            key: value
            for key, value in headers.items()
            if key.lower() in self._REQUEST_HEADER_ALLOWLIST
        }

    def _safe_response_headers(self, headers: httpx.Headers) -> dict[str, str]:
        return {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() in self._RESPONSE_HEADER_ALLOWLIST or key.lower() == "location"
        }

    def _respect_spacing(self, host: str) -> None:
        if self.per_host_spacing_seconds <= 0:
            return
        previous = self._last_request_by_host.get(host)
        now = time.monotonic()
        if previous is not None:
            delay = self.per_host_spacing_seconds - (now - previous)
            if delay > 0:
                time.sleep(delay)
        self._last_request_by_host[host] = time.monotonic()

    def _cache_key(self, method: str, url: str, body: bytes | None, json_body: object | None) -> str:
        payload = body or b""
        if json_body is not None:
            payload = json.dumps(json_body, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(method.encode() + b"\0" + url.encode() + b"\0" + payload).hexdigest()
        return digest

    def _cache_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> FetchRecord | None:
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        try:
            data = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
            if "body_b64" in data:
                data["body"] = b64decode(cast(str, data.pop("body_b64")))
            record = FetchRecord.model_validate(data)
        except (ValueError, OSError, TypeError):
            return None
        if datetime.now(UTC) - record.retrieved_at > self.ttl:
            return None
        return record

    def _write_cache(self, cache_key: str, record: FetchRecord) -> None:
        data = record.model_dump(mode="json", exclude={"body"})
        data["body_b64"] = b64encode(record.body).decode("ascii")
        _ = self._cache_path(cache_key).write_text(json.dumps(data), encoding="utf-8")

    def _default_resolver(self, host: str) -> list[str]:
        return [str(info[4][0]) for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]

    def _looks_like_challenge(self, body: bytes) -> bool:
        lowered = body[:4096].decode("utf-8", errors="ignore").lower()
        challenge_markers = (
            "checking your browser",
            "cf-challenge",
            "g-recaptcha",
            "h-captcha",
            "hcaptcha",
            "<title>just a moment",
        )
        return any(marker in lowered for marker in challenge_markers)

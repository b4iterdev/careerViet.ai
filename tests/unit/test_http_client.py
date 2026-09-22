from pathlib import Path

import httpx
import pytest

from mocnghe.ingestion.http_client import SafeHttpClient, UnsafeUrlError


def test_client_rejects_unsafe_urls(tmp_path: Path) -> None:
    client = SafeHttpClient(cache_dir=tmp_path, allowed_hosts={"itviec.com"})

    unsafe_urls = [
        "http://itviec.com/it-jobs/c-plus-plus/ha-noi",
        "https://itviec.com:444/it-jobs/c-plus-plus/ha-noi",
        "https://user:pass@itviec.com/it-jobs/c-plus-plus/ha-noi",
        "https://itviec.com/it-jobs/c-plus-plus/ha-noi#fragment",
        "https://example.com/jobs",
    ]

    for url in unsafe_urls:
        with pytest.raises(UnsafeUrlError):
            client.fetch("GET", url)


def test_client_rejects_private_dns_results(tmp_path: Path) -> None:
    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        dns_resolver=lambda _host: ["127.0.0.1"],
    )

    with pytest.raises(UnsafeUrlError):
        client.fetch("GET", "https://itviec.com/it-jobs/c-plus-plus/ha-noi")


def test_client_rejects_empty_dns_results(tmp_path: Path) -> None:
    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        dns_resolver=lambda _host: [],
    )

    with pytest.raises(UnsafeUrlError):
        client.fetch("GET", "https://itviec.com/it-jobs/c-plus-plus/ha-noi")


def test_client_validates_redirects_and_uses_persistent_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == "https://itviec.com/start":
            return httpx.Response(302, headers={"location": "https://itviec.com/final"})
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    first = client.fetch("GET", "https://itviec.com/start")
    second = client.fetch("GET", "https://itviec.com/start")

    assert first.status_code == 200
    assert first.final_url == "https://itviec.com/final"
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.retrieved_at == first.retrieved_at
    assert calls == ["https://itviec.com/start", "https://itviec.com/final"]


def test_client_blocks_redirect_to_disallowed_host(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/final"})

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    with pytest.raises(UnsafeUrlError):
        client.fetch("GET", "https://itviec.com/start")


def test_client_does_not_cache_challenge_or_cookie_headers(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                text='<html><title>Just a moment...</title><div id="cf-challenge-running"></div></html>',
                headers={"set-cookie": "session=secret", "content-type": "text/html"},
            )
        return httpx.Response(200, text="ok", headers={"set-cookie": "session=secret"})

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    challenge = client.fetch("GET", "https://itviec.com/it-jobs/c-plus-plus/ha-noi")
    with pytest.raises(UnsafeUrlError):
        client.fetch("GET", "https://itviec.com/it-jobs/c-plus-plus/ha-noi")

    assert challenge.from_cache is False
    assert calls == 1
    assert "set-cookie" not in challenge.headers

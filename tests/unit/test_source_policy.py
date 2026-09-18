from pathlib import Path

import httpx

from careerviet.ingestion.http_client import SafeHttpClient
from careerviet.ingestion.results import IngestionState
from careerviet.ingestion.source_policy import discover_source_policy


def test_policy_discovery_records_robots_terms_and_allowed_state(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://itviec.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"})
        if str(request.url) == "https://itviec.com/it-jobs/c-plus-plus/ha-noi":
            return httpx.Response(
                200,
                text='<html><a href="/terms-and-conditions">Terms</a></html>',
                headers={"content-type": "text/html"},
            )
        if str(request.url) == "https://itviec.com/terms-and-conditions":
            return httpx.Response(200, text="Terms", headers={"content-type": "text/html"})
        raise AssertionError(str(request.url))

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    result = discover_source_policy(client, "https://itviec.com/it-jobs/c-plus-plus/ha-noi")

    assert result.state is IngestionState.SUCCESS
    assert result.schema_validated is True
    assert result.stats.requests == 3
    assert len(result.policy_evidence) == 3
    assert result.policy_evidence[-1].final_url == "https://itviec.com/terms-and-conditions"


def test_policy_discovery_marks_blocked_or_unverified(tmp_path: Path) -> None:
    blocked = SafeHttpClient(
        cache_dir=tmp_path / "blocked",
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(lambda _request: httpx.Response(403, text="Forbidden")),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )
    def unverified_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://itviec.com/blog/terms-and-conditions":
            return httpx.Response(404, text="Not found")
        return httpx.Response(200, text="<html>No terms</html>")

    unverified = SafeHttpClient(
        cache_dir=tmp_path / "unverified",
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(unverified_handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    assert discover_source_policy(blocked, "https://itviec.com/it-jobs/c-plus-plus/ha-noi").state is IngestionState.BLOCKED
    assert discover_source_policy(unverified, "https://itviec.com/it-jobs/c-plus-plus/ha-noi").state is IngestionState.POLICY_UNVERIFIED


def test_policy_discovery_enforces_robots_disallow_before_fetching_page(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == "https://itviec.com/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /it-jobs/",
                headers={"content-type": "text/plain"},
            )
        raise AssertionError(f"robots disallowed page should not be fetched: {request.url}")

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    result = discover_source_policy(client, "https://itviec.com/it-jobs/c-plus-plus/ha-noi")

    assert result.state is IngestionState.BLOCKED
    assert seen == ["https://itviec.com/robots.txt"]


def test_policy_discovery_uses_observed_terms_without_getting_post_only_endpoint(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if str(request.url) == "https://ms.vietnamworks.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"})
        if str(request.url) == "https://www.vietnamworks.com/terms-of-use":
            return httpx.Response(200, text="Terms of use", headers={"content-type": "text/html"})
        raise AssertionError(f"unexpected policy fetch: {request.method} {request.url}")

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"ms.vietnamworks.com", "www.vietnamworks.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    result = discover_source_policy(
        client,
        "https://ms.vietnamworks.com/job-search/v1.0/search",
    )

    assert result.state is IngestionState.SUCCESS
    assert seen == [
        ("GET", "https://ms.vietnamworks.com/robots.txt"),
        ("GET", "https://www.vietnamworks.com/terms-of-use"),
    ]

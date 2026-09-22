import json
from pathlib import Path

import httpx

from mocnghe.ingestion.http_client import SafeHttpClient
from mocnghe.ingestion.results import IngestionState
from mocnghe.ingestion.vietnamworks import (
    AUTHORIZED_SEARCH_URL,
    parse_vietnamworks_search,
    search_vietnamworks,
)


def test_vietnamworks_fixture_parses_full_json_and_keyword_filter() -> None:
    payload = json.loads((Path(__file__).parents[1] / "fixtures" / "http" / "vietnamworks_search_success.json").read_text(encoding="utf-8"))

    result = parse_vietnamworks_search(payload, keyword="C++", location="Hà Nội")

    assert result.state is IngestionState.SUCCESS
    assert result.schema_validated is True
    assert result.stats.parsed_unique_count == 1
    assert result.stats.filtered_count == 2
    assert result.jobs[0].title == "Senior C++/C# Engineer"
    assert str(result.jobs[0].source.original_url) == "https://www.vietnamworks.com/senior-cpp-csharp-engineer-1"
    assert "C++" in result.jobs[0].description
    assert result.jobs[0].salary.kind.value == "negotiable"


def test_vietnamworks_malformed_schema_is_not_empty_success() -> None:
    payload = json.loads((Path(__file__).parents[1] / "fixtures" / "http" / "vietnamworks_malformed_schema.json").read_text(encoding="utf-8"))

    result = parse_vietnamworks_search(payload, keyword="C++")

    assert result.state is IngestionState.SCHEMA_CHANGED
    assert result.schema_validated is False
    assert result.stats.missing_required_fields >= 1


def test_vietnamworks_non_object_records_are_schema_failures() -> None:
    result = parse_vietnamworks_search({"data": [1]}, keyword="C++")

    assert result.state is IngestionState.SCHEMA_CHANGED
    assert result.schema_validated is False
    assert result.stats.rejected_count == 1


def test_vietnamworks_live_without_observed_payload_is_unsupported(tmp_path: Path) -> None:
    result = search_vietnamworks(cache_dir=tmp_path, live=True)

    assert result.state is IngestionState.UNSUPPORTED
    assert result.jobs == []
    assert "payload" in (result.message or "")


def test_vietnamworks_live_posts_explicit_payload_evidence(tmp_path: Path) -> None:
    fixture_payload = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "http" / "vietnamworks_search_success.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_path = tmp_path / "payload-evidence.json"
    evidence_path.write_text(
        json.dumps({"method": "POST", "url": AUTHORIZED_SEARCH_URL, "payload": {"keyword": "C++"}}),
        encoding="utf-8",
    )

    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), json.loads(request.content.decode("utf-8"))))
        return httpx.Response(200, json=fixture_payload)

    client = SafeHttpClient(
        cache_dir=tmp_path / "cache",
        allowed_hosts={"ms.vietnamworks.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    result = search_vietnamworks(
        cache_dir=tmp_path,
        live=True,
        client=client,
        payload_evidence_path=evidence_path,
        keyword="C++",
        location="Hà Nội",
    )

    assert result.state is IngestionState.SUCCESS
    assert result.stats.requests == 1
    assert result.stats.parsed_unique_count == 1
    assert seen == [("POST", AUTHORIZED_SEARCH_URL, {"keyword": "C++"})]

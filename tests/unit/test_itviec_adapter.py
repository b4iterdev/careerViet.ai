from pathlib import Path

import httpx

from careerviet.ingestion.http_client import SafeHttpClient
from careerviet.ingestion.itviec import parse_itviec_search, search_itviec
from careerviet.ingestion.results import IngestionState


def test_itviec_fixture_parses_cards_details_nested_sections_and_next_links(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "http"
    responses = {
        "https://itviec.com/it-jobs/c-plus-plus/ha-noi": fixture_dir.joinpath("itviec_search.html").read_text(encoding="utf-8"),
        "https://itviec.com/it-jobs/senior-cpp-engineer-123": fixture_dir.joinpath("itviec_detail_nested.html").read_text(encoding="utf-8"),
        "https://itviec.com/it-jobs/java-engineer-999": fixture_dir.joinpath("itviec_missing_sections.html").read_text(encoding="utf-8"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=responses[str(request.url)], headers={"content-type": "text/html"})

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    result = search_itviec(client=client, keyword="C++", location="Hà Nội")

    assert result.state is IngestionState.SUCCESS
    assert result.stats.requests == 3
    assert result.stats.parsed_unique_count == 1
    assert result.stats.missing_required_fields == 1
    assert result.jobs[0].title == "Senior C++ Engineer"
    assert result.jobs[0].employer == "Example Tech"
    assert "Templates & entities" in result.jobs[0].description
    assert "C++17" in result.jobs[0].requirements


def test_itviec_parser_marks_challenge_blocked() -> None:
    html = (Path(__file__).parents[1] / "fixtures" / "http" / "itviec_challenge.html").read_text(encoding="utf-8")

    result = parse_itviec_search(html, final_url="https://itviec.com/it-jobs/c-plus-plus/ha-noi")

    assert result.state is IngestionState.BLOCKED
    assert result.jobs == []


def test_itviec_parser_does_not_treat_nav_links_as_job_cards() -> None:
    html = '<html><nav><a href="/it-jobs/c-plus-plus/ha-noi">C++ jobs</a></nav></html>'

    result = parse_itviec_search(html, final_url="https://itviec.com/it-jobs/c-plus-plus/ha-noi")

    assert result.state is IngestionState.SCHEMA_CHANGED
    assert result.jobs == []


def test_itviec_missing_employer_or_location_is_incomplete(tmp_path: Path) -> None:
    html = """
    <article class="job-card">
      <a class="job-title" href="/it-jobs/incomplete-123">Incomplete C++ Job</a>
    </article>
    """
    detail = """
    <html><body>
      <h1>Incomplete C++ Job</h1>
      <h2>Job description</h2><p>Build services with C++.</p>
      <h2>Your skills</h2><p>Modern C++ experience.</p>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://itviec.com/it-jobs/incomplete-123"
        return httpx.Response(200, text=detail, headers={"content-type": "text/html"})

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    result = parse_itviec_search(
        html,
        final_url="https://itviec.com/it-jobs/c-plus-plus/ha-noi",
        client=client,
    )

    assert result.state is IngestionState.PARTIAL
    assert result.jobs == []
    assert result.stats.missing_required_fields == 1


def test_itviec_detail_http_error_is_not_parsed_as_card_fallback(tmp_path: Path) -> None:
    html = """
    <article class="job-card">
      <a class="job-title" href="/it-jobs/error-123">Error C++ Job</a>
    </article>
    """

    client = SafeHttpClient(
        cache_dir=tmp_path,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(lambda _request: httpx.Response(500, text="Server error")),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )

    result = parse_itviec_search(
        html,
        final_url="https://itviec.com/it-jobs/c-plus-plus/ha-noi",
        client=client,
    )

    assert result.state is IngestionState.HTTP_ERROR
    assert result.stats.status_codes == [500]
    assert result.jobs == []

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from ..models.job import EmploymentType, Job, SourceProvenance, hash_job_identity, job_id_from_hash
from .http_client import SafeHttpClient, UnsafeUrlError
from .results import IngestionState, SourceResult, SourceStats
from .vietnamworks import matches_keyword, matches_location, parse_salary_text

SOURCE_ID = "itviec"
AUTHORIZED_SEARCH_URL = "https://itviec.com/it-jobs/c-plus-plus/ha-noi"


def search_itviec(
    *,
    client: SafeHttpClient,
    keyword: str | None = None,
    location: str | None = None,
    request_budget: int = 8,
    source_kind: str = "itviec_http",
) -> SourceResult:
    stats = SourceStats(source_id=SOURCE_ID, source_limits={"request_budget": request_budget, "authorized_search_url": AUTHORIZED_SEARCH_URL})
    if keyword:
        stats.record_filter(f"keyword:{keyword}")
    if location:
        stats.record_filter(f"location:{location}")
    try:
        search_record = client.fetch("GET", AUTHORIZED_SEARCH_URL)
    except TimeoutError:
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.TIMEOUT, stats=stats)
    except (OSError, UnsafeUrlError) as error:
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.NETWORK_ERROR, stats=stats, message=str(error))
    stats.record_http(search_record.status_code, search_record.latency_ms, search_record.bytes_received)
    if search_record.from_cache:
        stats.cache_hits += 1
    if search_record.status_code in {403, 429}:
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.BLOCKED, stats=stats, message=f"HTTP {search_record.status_code}")
    if search_record.status_code >= 400:
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.HTTP_ERROR, stats=stats, message=f"HTTP {search_record.status_code}")
    return parse_itviec_search(
        search_record.text,
        final_url=search_record.final_url,
        client=client,
        stats=stats,
        keyword=keyword,
        location=location,
        request_budget=request_budget,
        source_kind=source_kind,
    )


def parse_itviec_search(
    html: str,
    *,
    final_url: str,
    client: SafeHttpClient | None = None,
    stats: SourceStats | None = None,
    keyword: str | None = None,
    location: str | None = None,
    request_budget: int = 8,
    source_kind: str = "itviec_http",
) -> SourceResult:
    stats = stats or SourceStats(source_id=SOURCE_ID, source_limits={"request_budget": request_budget, "authorized_search_url": AUTHORIZED_SEARCH_URL})
    if _looks_like_challenge(html):
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.BLOCKED, stats=stats, message="challenge page detected")
    soup = BeautifulSoup(html, "html.parser")
    cards = _job_cards(soup)
    if not cards:
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.SCHEMA_CHANGED, stats=stats, message="no job cards found")

    jobs: list[Job] = []
    seen_urls: set[str] = set()
    for card in cards:
        link = _card_link(card)
        if link is None:
            stats.missing_required_fields += 1
            stats.rejected_count += 1
            continue
        href = cast(str, link.get("href", ""))
        detail_url = urljoin(final_url, href)
        if urlsplit(detail_url).hostname != "itviec.com" or not detail_url.startswith("https://"):
            stats.rejected_count += 1
            continue
        if detail_url in seen_urls:
            stats.duplicates += 1
            continue
        seen_urls.add(detail_url)
        if client is not None and stats.requests < request_budget:
            try:
                record = client.fetch("GET", detail_url)
            except TimeoutError:
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.TIMEOUT, stats=stats)
            except (OSError, UnsafeUrlError) as error:
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.NETWORK_ERROR, stats=stats, message=str(error))
            stats.record_http(record.status_code, record.latency_ms, record.bytes_received)
            if record.from_cache:
                stats.cache_hits += 1
            detail_html = record.text
            if record.status_code in {403, 429} or _looks_like_challenge(detail_html):
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.BLOCKED, stats=stats, message="detail blocked")
            if record.status_code >= 400:
                return SourceResult(
                    source_id=SOURCE_ID,
                    state=IngestionState.HTTP_ERROR,
                    stats=stats,
                    message=f"detail HTTP {record.status_code} {record.final_url}",
                )
            parse_url = record.final_url
            retrieved_at = record.retrieved_at
        elif client is not None:
            stats.rejected_count += 1
            return SourceResult(
                source_id=SOURCE_ID,
                state=IngestionState.PARTIAL,
                stats=stats,
                jobs=jobs,
                schema_validated=True,
                message="request budget exhausted before detail retrieval",
            )
        else:
            detail_html = str(card)
            parse_url = detail_url
            retrieved_at = datetime.now(UTC)
        parsed = _parse_detail(
            detail_html,
            fallback_title=link.get_text(" ", strip=True),
            detail_url=parse_url,
            retrieved_at=retrieved_at,
            source_kind=source_kind,
        )
        if parsed is None:
            stats.missing_required_fields += 1
            stats.rejected_count += 1
            continue
        job = parsed
        searchable = f"{job.title}\n{job.description}\n{job.requirements}"
        if keyword and not matches_keyword(searchable, keyword):
            stats.filtered_count += 1
            continue
        if location and not matches_location(job.location, location):
            stats.filtered_count += 1
            continue
        jobs.append(job)
    stats.parsed_unique_count = len(jobs)
    if not jobs and stats.missing_required_fields:
        state = IngestionState.PARTIAL
    else:
        state = IngestionState.SUCCESS if jobs else IngestionState.EMPTY
    return SourceResult(source_id=SOURCE_ID, state=state, stats=stats, jobs=jobs, schema_validated=True)


def fixture_client_for_itviec(fixture_path: str | Path, cache_dir: str | Path) -> SafeHttpClient:
    path = Path(fixture_path)
    directory = path if path.is_dir() else path.parent
    search_path = path if path.is_file() else directory / "itviec_search.html"
    files = {AUTHORIZED_SEARCH_URL: search_path.read_text(encoding="utf-8")}
    for detail_file in directory.glob("itviec_detail*.html"):
        files["https://itviec.com/it-jobs/senior-cpp-engineer-123"] = detail_file.read_text(encoding="utf-8")
    missing = directory / "itviec_missing_sections.html"
    if missing.exists():
        files["https://itviec.com/it-jobs/java-engineer-999"] = missing.read_text(encoding="utf-8")

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        body = files.get(str(request.url))
        if body is None:
            return httpx.Response(404, text="fixture not found")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    return SafeHttpClient(
        cache_dir=cache_dir,
        allowed_hosts={"itviec.com"},
        transport=httpx.MockTransport(handler),
        dns_resolver=lambda _host: ["8.8.8.8"],
    )


def _job_cards(soup: BeautifulSoup) -> list[Tag]:
    return [card for card in soup.select("article, .job-card, [data-testid*='job']") if _card_link(card)]


def _card_link(card: Tag) -> Tag | None:
    scoped = card.select_one("a.job-title[href], h2 a[href], h3 a[href], h4 a[href]")
    if isinstance(scoped, Tag) and "/it-jobs/" in str(scoped.get("href")):
        return scoped
    for anchor in card.find_all("a", href=True):
        if "/it-jobs/" in str(anchor.get("href")) and _looks_like_title_link(anchor):
            return anchor
    return None


def _parse_detail(
    html: str,
    *,
    fallback_title: str,
    detail_url: str,
    retrieved_at: datetime,
    source_kind: str,
) -> Job | None:
    soup = BeautifulSoup(html, "html.parser")
    title = _text_first(soup, "h1") or fallback_title
    employer = _text_first(soup, "a[href*='/companies/']") or _text_first(
        soup, ".company, .company-name, .employer-name, [class*='company']"
    )
    location = _text_first(
        soup, "div.gap-2 span.normal-text, .job-details__overview span.normal-text, .location, [class*='location']"
    )
    if not location:
        for s in soup.select("div.d-flex span.normal-text, div.d-flex div.text-dark-grey"):
            t = s.get_text(" ", strip=True)
            if any(c in t for c in ["Ha Noi", "Hà Nội", "Ho Chi Minh", "Hồ Chí Minh", "Da Nang", "Đà Nẵng"]):
                location = t
                break
    description = _section_after_heading(soup, ("job description", "mô tả"))
    requirements = _section_after_heading(soup, ("your skills", "requirements", "yêu cầu"))
    benefits = _section_after_heading(soup, ("why you'll love", "benefits", "quyền lợi"))
    salary = _text_first(soup, ".salary, [class*='salary']") or "unknown"
    if not title or not employer or not location or not description or not requirements:
        return None
    raw_content = "\n".join([f"Tiêu đề: {title}", f"Công ty: {employer}", f"Địa điểm: {location}", f"Lương: {salary}", "Mô tả:", description, "Yêu cầu:", requirements, "Quyền lợi:", benefits])
    content_hash = hash_job_identity(raw_content)
    return Job(
        job_id=job_id_from_hash(content_hash),
        content_hash=content_hash,
        source=_source(detail_url, retrieved_at=retrieved_at, source_kind=source_kind),
        title=title,
        employer=employer,
        location=location,
        employment_type=EmploymentType.UNKNOWN,
        salary=parse_salary_text(salary),
        description=description,
        requirements=requirements,
        benefits=benefits,
    )


def _text_first(soup: BeautifulSoup, selector: str) -> str:
    element = soup.select_one(selector)
    return element.get_text(" ", strip=True) if element else ""


def _section_after_heading(soup: BeautifulSoup, headings: tuple[str, ...]) -> str:
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = heading.get_text(" ", strip=True).lower()
        if any(candidate in heading_text for candidate in headings):
            parts: list[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h2", "h3", "h4"}:
                    break
                text = sibling.get_text(" ", strip=True)
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
    return ""


def _looks_like_challenge(html: str) -> bool:
    lowered = html[:4096].lower()
    return any(
        marker in lowered
        for marker in (
            "checking your browser",
            "cf-challenge",
            "g-recaptcha",
            "h-captcha",
            "hcaptcha",
            "<title>just a moment",
        )
    )


def _looks_like_title_link(anchor: Tag) -> bool:
    classes = " ".join(str(value).lower() for value in anchor.get("class", []))
    parent_text = " ".join(str(value).lower() for value in anchor.parent.get("class", [])) if isinstance(anchor.parent, Tag) else ""
    return "title" in classes or "job" in classes or "title" in parent_text or anchor.find_parent(["h2", "h3", "h4"]) is not None


def _source(url: str, *, retrieved_at: datetime, source_kind: str) -> SourceProvenance:
    return SourceProvenance.model_validate(
        {
            "source_id": f"{SOURCE_ID}:{url}",
            "source_kind": source_kind,
            "original_uri": url,
            "original_url": url,
            "retrieved_at": retrieved_at,
        }
    )

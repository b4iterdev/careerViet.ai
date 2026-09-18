from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from ..models.job import (
    EmploymentType,
    Job,
    Salary,
    SalaryKind,
    SourceProvenance,
    hash_job_identity,
    job_id_from_hash,
)
from .http_client import SafeHttpClient, UnsafeUrlError
from .results import IngestionState, SourceResult, SourceStats

SOURCE_ID = "vietnamworks"
AUTHORIZED_SEARCH_URL = "https://ms.vietnamworks.com/job-search/v1.0/search"


def search_vietnamworks(
    *,
    cache_dir: str | Path,
    live: bool = False,
    fixture_path: str | Path | None = None,
    client: SafeHttpClient | None = None,
    payload_evidence_path: str | Path | None = None,
    keyword: str | None = None,
    location: str | None = None,
) -> SourceResult:
    cache_path = Path(cache_dir)
    if fixture_path is not None:
        data = cast(object, json.loads(Path(fixture_path).read_text(encoding="utf-8")))
        return parse_vietnamworks_search(
            data,
            keyword=keyword,
            location=location,
            source_kind="vietnamworks_http_fixture",
        )
    if live:
        stats = SourceStats(source_id=SOURCE_ID, source_limits={"authorized_endpoint": AUTHORIZED_SEARCH_URL})
        payload = _load_payload_evidence(payload_evidence_path)
        if payload is None:
            return SourceResult(
                source_id=SOURCE_ID,
                state=IngestionState.UNSUPPORTED,
                stats=stats,
                message="VietnamWorks live POST payload provenance is unavailable; no payload was fabricated.",
            )
        owns_client = client is None
        http_client = client or SafeHttpClient(cache_dir=cache_path, allowed_hosts={"ms.vietnamworks.com"})
        try:
            try:
                record = http_client.fetch("POST", AUTHORIZED_SEARCH_URL, json_body=payload, use_cache=False)
            except TimeoutError:
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.TIMEOUT, stats=stats)
            except (OSError, UnsafeUrlError) as error:
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.NETWORK_ERROR, stats=stats, message=str(error))
            stats.record_http(record.status_code, record.latency_ms, record.bytes_received)
            if record.status_code in {403, 429}:
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.BLOCKED, stats=stats, message=f"HTTP {record.status_code}")
            if record.status_code >= 400:
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.HTTP_ERROR, stats=stats, message=f"HTTP {record.status_code}")
            try:
                data = cast(object, json.loads(record.text))
            except json.JSONDecodeError as error:
                return SourceResult(source_id=SOURCE_ID, state=IngestionState.PARSE_FAILED, stats=stats, message=str(error))
            parsed = parse_vietnamworks_search(
                data,
                keyword=keyword,
                location=location,
                retrieved_at=record.retrieved_at,
                source_kind="vietnamworks_http",
            )
            parsed.stats.requests += stats.requests
            parsed.stats.status_codes = [*stats.status_codes, *parsed.stats.status_codes]
            parsed.stats.latency_ms += stats.latency_ms
            parsed.stats.bytes_received += stats.bytes_received
            return parsed
        finally:
            if owns_client:
                http_client.close()
    return SourceResult(source_id=SOURCE_ID, state=IngestionState.UNSUPPORTED, stats=SourceStats(source_id=SOURCE_ID), message="provide --fixture or explicit --live")


def parse_vietnamworks_search(
    payload: object,
    *,
    keyword: str | None = None,
    location: str | None = None,
    retrieved_at: datetime | None = None,
    source_kind: str = "vietnamworks_http",
) -> SourceResult:
    stats = SourceStats(source_id=SOURCE_ID, source_limits={"authorized_endpoint": AUTHORIZED_SEARCH_URL})
    if keyword:
        stats.record_filter(f"keyword:{keyword}")
    if location:
        stats.record_filter(f"location:{location}")
    extracted = _extract_records(payload)
    if extracted is None:
        stats.missing_required_fields += 1
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.SCHEMA_CHANGED, stats=stats, message="payload did not contain an observed list of jobs")
    records, malformed_count = extracted
    if malformed_count:
        stats.missing_required_fields += malformed_count
        stats.rejected_count += malformed_count
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    for record in records:
        parsed = _parse_record(record)
        if parsed is None:
            stats.missing_required_fields += 1
            stats.rejected_count += 1
            continue
        url, title, employer, job_location, description, requirements, salary_text = parsed
        searchable = f"{title}\n{description}\n{requirements}"
        if keyword and not matches_keyword(searchable, keyword):
            stats.filtered_count += 1
            continue
        if location and not matches_location(job_location, location):
            stats.filtered_count += 1
            continue
        if url in seen_urls:
            stats.duplicates += 1
            continue
        seen_urls.add(url)
        raw_content = _raw_content(title, employer, job_location, description, requirements, salary_text)
        content_hash = hash_job_identity(raw_content)
        jobs.append(
            Job(
                job_id=job_id_from_hash(content_hash),
                content_hash=content_hash,
                source=_source(url, retrieved_at=retrieved_at or datetime.now(UTC), source_kind=source_kind),
                title=title,
                employer=employer,
                location=job_location,
                employment_type=EmploymentType.UNKNOWN,
                salary=parse_salary_text(salary_text),
                description=description,
                requirements=requirements,
            )
        )
    stats.parsed_unique_count = len(jobs)
    if stats.missing_required_fields and not jobs:
        return SourceResult(source_id=SOURCE_ID, state=IngestionState.SCHEMA_CHANGED, stats=stats, message="required job fields missing")
    state = IngestionState.SUCCESS if jobs else IngestionState.EMPTY
    if jobs and stats.missing_required_fields:
        state = IngestionState.PARTIAL
    return SourceResult(source_id=SOURCE_ID, state=state, stats=stats, jobs=jobs, schema_validated=True)


def _extract_records(payload: object) -> tuple[list[dict[str, object]], int] | None:
    if not isinstance(payload, dict):
        return None
    payload_dict = cast(dict[str, object], payload)
    for key in ("data", "jobs", "results"):
        value = payload_dict.get(key)
        if isinstance(value, list):
            return _dict_items(cast(list[object], value))
    nested = payload_dict.get("data")
    if isinstance(nested, dict):
        nested_dict = cast(dict[str, object], nested)
        for key in ("jobs", "items"):
            value = nested_dict.get(key)
            if isinstance(value, list):
                return _dict_items(cast(list[object], value))
    return None


def _parse_record(record: dict[str, object]) -> tuple[str, str, str, str, str, str, str] | None:
    title = _first_text(record, "jobTitle", "title", "name")
    employer = _first_text(record, "companyName", "company", "employer")
    location = _first_text(record, "location", "locationName", "workingLocation")
    description = _first_text(record, "jobDescription")
    requirements = _first_text(record, "jobRequirement")
    url = _first_text(record, "jobUrl", "url")
    salary = _first_text(record, "salary", "salaryText") or "unknown"
    if not all([title, employer, location, description, requirements, url]) or not _safe_vietnamworks_url(url):
        return None
    return url, title, employer, location, description, requirements, salary


def _first_text(record: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return _strip_html(value)
        if isinstance(value, list):
            items = cast(list[object], value)
            joined = ", ".join(str(item).strip() for item in items if str(item).strip())
            if joined:
                return _strip_html(joined)
        if isinstance(value, dict):
            nested_record = cast(dict[str, object], value)
            for nested_key in ("name", "value", "label"):
                nested = nested_record.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return _strip_html(nested)
    return ""


def _dict_items(value: list[object]) -> tuple[list[dict[str, object]], int]:
    records = [cast(dict[str, object], item) for item in value if isinstance(item, dict)]
    return records, len(value) - len(records)


def _strip_html(value: str) -> str:
    if "<" in value and ">" in value:
        from bs4 import BeautifulSoup

        return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return value.strip()


def _safe_vietnamworks_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "www.vietnamworks.com" and not parts.fragment


def _load_payload_evidence(path: str | Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        evidence = cast(dict[str, object], json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if evidence.get("method") != "POST" or evidence.get("url") != AUTHORIZED_SEARCH_URL:
        return None
    payload = evidence.get("payload")
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, object], payload)


def matches_keyword(text: str, keyword: str) -> bool:
    lowered = keyword.lower()
    if lowered in {"c++", "c#"}:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(keyword) + r"(?![A-Za-z0-9])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return lowered in text.lower()


def strip_vietnamese_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def matches_location(job_location: str, query_location: str) -> bool:
    if query_location.lower() in job_location.lower():
        return True
    return strip_vietnamese_diacritics(query_location).lower() in strip_vietnamese_diacritics(job_location).lower()


def _raw_content(title: str, employer: str, location: str, description: str, requirements: str, salary: str) -> str:
    return "\n".join(
        [
            f"Tiêu đề: {title}",
            f"Công ty: {employer}",
            f"Địa điểm: {location}",
            f"Lương: {salary}",
            "Mô tả:",
            description,
            "Yêu cầu:",
            requirements,
        ]
    )


def parse_salary_text(value: str) -> Salary:
    lowered = value.lower().strip()
    if not lowered or lowered in {"unknown", "chưa rõ", "không rõ"}:
        return Salary(kind=SalaryKind.UNKNOWN)
    if "thỏa thuận" in lowered or "thoả thuận" in lowered or "negotiable" in lowered:
        return Salary(kind=SalaryKind.NEGOTIABLE)
    if "ẩn" in lowered or "hidden" in lowered:
        return Salary(kind=SalaryKind.HIDDEN)
    if re.fullmatch(r"0\s*(vnd|vnđ|₫|đồng)(\s*/\s*tháng|\s+tháng|/month|\s+per\s+month)?", lowered):
        return Salary(kind=SalaryKind.ZERO, currency="VND", period="month", minimum=0, maximum=0)
    return Salary(kind=SalaryKind.UNKNOWN)


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

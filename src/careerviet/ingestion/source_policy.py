from __future__ import annotations

import hashlib
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .http_client import SafeHttpClient, UnsafeUrlError
from .results import IngestionState, PolicyEvidence, SourceResult, SourceStats

OBSERVED_TERMS_URLS = {
    "ms.vietnamworks.com": "https://www.vietnamworks.com/terms-of-use",
    "www.vietnamworks.com": "https://www.vietnamworks.com/terms-of-use",
    "itviec.com": "https://itviec.com/blog/terms-and-conditions",
}

POST_ONLY_POLICY_TARGETS = {"https://ms.vietnamworks.com/job-search/v1.0/search"}


def discover_source_policy(client: SafeHttpClient, observed_url: str) -> SourceResult:
    source_id = urlsplit(observed_url).hostname or observed_url
    stats = SourceStats(source_id=source_id)
    evidence: list[PolicyEvidence] = []

    def fetch_evidence(url: str) -> str | None:
        try:
            record = client.fetch("GET", url, use_cache=False)
        except (UnsafeUrlError, OSError, TimeoutError, httpx.HTTPError) as error:
            evidence.append(PolicyEvidence(url=url, final_url=url, state="error", excerpt=str(error)[:500]))
            return str(error)
        text = record.text
        content_type = record.headers.get("content-type", "")
        blocked = record.status_code in {403, 429} or _looks_like_challenge(text)
        stats.record_http(record.status_code, record.latency_ms, record.bytes_received)
        evidence.append(
            PolicyEvidence(
                url=url,
                final_url=record.final_url,
                status_code=record.status_code,
                content_type=record.headers.get("content-type", ""),
                retrieved_at=record.retrieved_at,
                latency_ms=record.latency_ms,
                bytes_received=record.bytes_received,
                state="blocked" if blocked else "observed",
                content_sha256=hashlib.sha256(record.body).hexdigest(),
                excerpt=_excerpt(text, content_type),
            )
        )
        if blocked:
            return "blocked"
        if record.status_code >= 400:
            return None
        if not _acceptable_content_type(url, content_type):
            return None
        return text

    parts = urlsplit(observed_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    robots_text = fetch_evidence(robots_url)
    if robots_text == "blocked":
        return SourceResult(source_id=source_id, state=IngestionState.BLOCKED, stats=stats, policy_evidence=evidence, message="robots blocked")
    if not robots_text:
        return SourceResult(source_id=source_id, state=IngestionState.POLICY_UNVERIFIED, stats=stats, policy_evidence=evidence, message="robots unavailable")
    if not _robots_allows(robots_text, observed_url):
        return SourceResult(source_id=source_id, state=IngestionState.BLOCKED, stats=stats, policy_evidence=evidence, message="robots disallow observed path")

    terms_url = OBSERVED_TERMS_URLS.get(parts.hostname or "")
    if observed_url not in POST_ONLY_POLICY_TARGETS:
        page_text = fetch_evidence(observed_url)
        if page_text == "blocked":
            return SourceResult(source_id=source_id, state=IngestionState.BLOCKED, stats=stats, policy_evidence=evidence, message="observed page blocked")
        if page_text:
            terms_url = _find_terms_link(page_text, observed_url) or terms_url
    if terms_url is None:
        return SourceResult(source_id=source_id, state=IngestionState.POLICY_UNVERIFIED, stats=stats, policy_evidence=evidence, message="terms link not observed")

    terms_text = fetch_evidence(terms_url)
    if terms_text == "blocked":
        return SourceResult(source_id=source_id, state=IngestionState.BLOCKED, stats=stats, policy_evidence=evidence, message="terms blocked")
    if not terms_text:
        return SourceResult(source_id=source_id, state=IngestionState.POLICY_UNVERIFIED, stats=stats, policy_evidence=evidence, message="terms unavailable")
    return SourceResult(source_id=source_id, state=IngestionState.SUCCESS, stats=stats, policy_evidence=evidence, schema_validated=True, message="robots and terms observed")


def _robots_allows(robots_text: str, observed_url: str) -> bool:
    parser = RobotFileParser()
    parser.parse(robots_text.splitlines())
    return parser.can_fetch("careerviet-milestone2", observed_url)


def _acceptable_content_type(url: str, content_type: str) -> bool:
    lowered = content_type.lower()
    if url.endswith("/robots.txt"):
        return "text/plain" in lowered or "text/" in lowered or lowered == ""
    return any(candidate in lowered for candidate in ("text/html", "text/plain", "application/xhtml"))


def _looks_like_challenge(text: str) -> bool:
    lowered = text[:4096].lower()
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


def _excerpt(text: str, content_type: str) -> str:
    if "html" in content_type.lower():
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())[:500]


def _find_terms_link(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True).lower()
        href = str(anchor["href"])
        lowered_href = href.lower()
        if "terms" in text or "terms" in lowered_href or "điều khoản" in text or "dieu-khoan" in lowered_href:
            return urljoin(base_url, href)
    return None

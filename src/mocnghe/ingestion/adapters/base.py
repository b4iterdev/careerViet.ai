from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlparse

import httpx

from ...models.job import Job


class BaseJobAdapter(ABC):
    """Base interface for all site-specific job ingestion adapters."""

    name: str
    domains: tuple[str, ...] = ()

    def supports_url(self, url: str) -> bool:
        """Return True if this adapter supports the given job posting URL."""
        if not self.domains:
            return True
        hostname = (urlparse(url).hostname or "").lower()
        return any(hostname == d or hostname.endswith(f".{d}") for d in self.domains)

    @abstractmethod
    def parse_job(self, content: str, *, url: str) -> Job:
        """Parse raw HTML or JSON content into a normalized Job model."""
        ...

    def fetch_job(
        self,
        url: str,
        *,
        use_browser: bool = False,
        timeout_seconds: float = 15.0,
    ) -> Job:
        """Fetch content using HTTP or headless browser, then parse."""
        if use_browser:
            from .browser import fetch_rendered_html

            html = fetch_rendered_html(url, timeout_seconds=timeout_seconds)
            return self.parse_job(html, url=url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return self.parse_job(response.text, url=url)

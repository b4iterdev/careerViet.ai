from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseJobAdapter
from .generic import GenericAdapter
from .greenhouse import GreenhouseAdapter

if TYPE_CHECKING:
    from ...models.job import Job

# Registered adapters in precedence order (specialized adapters first, fallback last)
_ADAPTERS: list[BaseJobAdapter] = [
    GreenhouseAdapter(),
]
_FALLBACK_ADAPTER = GenericAdapter()


def list_adapters() -> list[BaseJobAdapter]:
    """Return all registered specialized adapters."""
    return list(_ADAPTERS)


def register_adapter(adapter: BaseJobAdapter) -> None:
    """Register a new site adapter."""
    _ADAPTERS.insert(0, adapter)


def find_adapter(url: str) -> BaseJobAdapter:
    """Find the best matching adapter for a given URL, falling back to GenericAdapter."""
    for adapter in _ADAPTERS:
        if adapter.supports_url(url):
            return adapter
    return _FALLBACK_ADAPTER


def fetch_job_from_url(
    url: str,
    *,
    use_browser: bool = False,
    timeout_seconds: float = 15.0,
) -> Job:
    """Find adapter for URL, fetch content (optionally via browser), and return parsed Job."""
    adapter = find_adapter(url)
    return adapter.fetch_job(url, use_browser=use_browser, timeout_seconds=timeout_seconds)

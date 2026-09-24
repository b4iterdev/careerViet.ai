"""Unit tests for the modular job adapter system."""

import pytest

from mocnghe.ingestion.adapters.generic import GenericAdapter
from mocnghe.ingestion.adapters.greenhouse import GreenhouseAdapter
from mocnghe.ingestion.adapters.registry import find_adapter

SAMPLE_GREENHOUSE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Software Engineer (Intern, C#) at Constructor TECH</title>
    <meta property="og:title" content="Software Engineer (Intern, C#)">
</head>
<body>
    <div class="job__header">
        <h1 class="app-title">Software Engineer (Intern, C#)</h1>
        <span class="company-name">Constructor TECH</span>
        <div class="location">Bremen, Germany</div>
    </div>
    <div id="content">
        <p>Our mission is to enable all educational organisations...</p>
        <h2>Required Qualifications:</h2>
        <ul>
            <li>Current Computer Science student</li>
            <li>Experience with C# or C++</li>
        </ul>
        <h2>Good to Have:</h2>
        <ul>
            <li>Basic knowledge of RESTful APIs</li>
        </ul>
    </div>
</body>
</html>
"""


def test_greenhouse_adapter_matches_domains():
    adapter = GreenhouseAdapter()
    assert adapter.supports_url("https://job-boards.eu.greenhouse.io/constructortech/jobs/4772061101")
    assert adapter.supports_url("https://boards.greenhouse.io/airbnb/jobs/12345")
    assert not adapter.supports_url("https://itviec.com/it-jobs/c-sharp")


def test_greenhouse_adapter_parses_html():
    adapter = GreenhouseAdapter()
    url = "https://job-boards.eu.greenhouse.io/constructortech/jobs/4772061101"
    job = adapter.parse_job(SAMPLE_GREENHOUSE_HTML, url=url)

    assert job.title == "Software Engineer (Intern, C#)"
    assert "Constructor" in job.employer
    assert "Bremen" in job.location
    assert "Current Computer Science student" in job.requirements or "Current Computer Science student" in job.freeform_text
    assert str(job.source.original_url) == url
    assert job.source.source_kind == "greenhouse"


def test_generic_adapter_fallback():
    html = """
    <html>
    <head><title>Senior Python Dev at TechCorp</title></head>
    <body>
        <h1>Senior Python Dev</h1>
        <p>We are TechCorp looking for a Python engineer.</p>
    </body>
    </html>
    """
    adapter = GenericAdapter()
    url = "https://example.com/jobs/1"
    assert adapter.supports_url(url)
    job = adapter.parse_job(html, url=url)
    assert "Python" in job.title
    assert job.source.original_uri == url


def test_registry_finds_specific_adapter_then_generic():
    gh_adapter = find_adapter("https://job-boards.eu.greenhouse.io/test/jobs/123")
    assert isinstance(gh_adapter, GreenhouseAdapter)

    gen_adapter = find_adapter("https://unknown-startup.io/careers/456")
    assert isinstance(gen_adapter, GenericAdapter)


def test_browser_not_installed_error_message(monkeypatch):
    """When playwright is not installed, clear actionable error is raised."""
    # Simulate playwright not importable
    import sys

    from mocnghe.ingestion.adapters.browser import fetch_rendered_html
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)

    with pytest.raises(RuntimeError, match="mocnghe\\[browser\\]"):
        fetch_rendered_html("https://example.com")

"""Integration tests for URL crawling and adapter-based JD import."""

from datetime import UTC, datetime
from unittest.mock import patch

from typer.testing import CliRunner

from mocnghe.cli import app
from mocnghe.models.job import Job, SourceProvenance


def _mock_job(url: str) -> Job:
    return Job(
        source=SourceProvenance.model_validate({
            "source_id": f"test:{url}",
            "source_kind": "test",
            "original_uri": url,
            "original_url": url,
            "retrieved_at": datetime.now(UTC),
        }),
        title="Software Engineer (Intern, C#)",
        employer="Constructor TECH",
        location="Bremen, Germany",
        description="Internship details...",
        requirements="C# knowledge",
        freeform_text="Required Qualifications:\n- C# knowledge",
    )


def test_import_jd_via_url(tmp_path):
    ws = tmp_path / "ws"
    runner = CliRunner()
    runner.invoke(app, ["--workspace", str(ws), "init"])

    target_url = "https://job-boards.eu.greenhouse.io/constructortech/jobs/4772061101"

    with patch("mocnghe.ingestion.adapters.registry.fetch_job_from_url", return_value=_mock_job(target_url)):
        result = runner.invoke(app, ["--workspace", str(ws), "import-jd", "--url", target_url])
        assert result.exit_code == 0, result.output
        assert "imported" in result.stdout
        assert "Software Engineer" in result.stdout


def test_import_jd_via_url_with_browser_flag(tmp_path):
    ws = tmp_path / "ws"
    runner = CliRunner()
    runner.invoke(app, ["--workspace", str(ws), "init"])

    target_url = "https://job-boards.eu.greenhouse.io/constructortech/jobs/4772061101"

    with patch("mocnghe.ingestion.adapters.registry.fetch_job_from_url") as mock_fetch:
        mock_fetch.return_value = _mock_job(target_url)
        result = runner.invoke(app, ["--workspace", str(ws), "import-jd", "--url", target_url, "--browser"])
        assert result.exit_code == 0
        mock_fetch.assert_called_once_with(target_url, use_browser=True, timeout_seconds=15.0)


def test_jobs_crawl_command(tmp_path):
    ws = tmp_path / "ws"
    runner = CliRunner()
    runner.invoke(app, ["--workspace", str(ws), "init"])

    target_url = "https://job-boards.eu.greenhouse.io/constructortech/jobs/4772061101"

    with patch("mocnghe.ingestion.adapters.registry.fetch_job_from_url", return_value=_mock_job(target_url)):
        result = runner.invoke(app, ["--workspace", str(ws), "jobs", "crawl", target_url])
        assert result.exit_code == 0, result.output
        assert "imported" in result.stdout

from pathlib import Path

from typer.testing import CliRunner

from mocnghe.cli import app


def test_cli_http_fixture_search_and_ingest_preserves_manual_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    fixture = Path(__file__).parents[1] / "fixtures" / "http" / "itviec_search.html"

    search = runner.invoke(app, ["--workspace", str(workspace), "jobs", "search", "--source", "itviec", "--fixture", str(fixture), "--keyword", "C++"])
    first_ingest = runner.invoke(app, ["--workspace", str(workspace), "jobs", "ingest", "--source", "itviec", "--fixture", str(fixture), "--keyword", "C++"])
    second_ingest = runner.invoke(app, ["--workspace", str(workspace), "jobs", "ingest", "--source", "itviec", "--fixture", str(fixture), "--keyword", "C++"])
    list_result = runner.invoke(app, ["--workspace", str(workspace), "jobs", "list"])
    doctor = runner.invoke(app, ["--workspace", str(workspace), "doctor"])

    assert search.exit_code == 0, search.output
    assert "state: success" in search.output
    assert "parsed: 1" in search.output
    assert first_ingest.exit_code == 0, first_ingest.output
    assert "imported: 1" in first_ingest.output
    assert second_ingest.exit_code == 0, second_ingest.output
    assert "existing: 1" in second_ingest.output
    assert list_result.exit_code == 0, list_result.output
    assert list_result.output.count("Senior C++ Engineer") == 1
    assert "applied=false" in list_result.output
    assert doctor.exit_code == 0
    assert "database: ok" in doctor.output

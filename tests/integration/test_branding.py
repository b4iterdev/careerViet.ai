"""Public package/CLI contract for the Mốc Nghề rename."""
import importlib.util
from importlib import metadata, resources

from typer.testing import CliRunner


def test_mocnghe_public_package_and_branding():
    assert importlib.util.find_spec("mocnghe") is not None
    from mocnghe.cli import app

    distribution = metadata.distribution("mocnghe")
    assert any(ep.name == "mocnghe" and ep.value == "mocnghe.cli:app"
               for ep in distribution.entry_points)
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Mốc Nghề" in result.output
    assert resources.files("mocnghe.assets").joinpath("fonts/NotoSans-Regular.ttf").is_file()
    from mocnghe.assets import runtime_skill_readme

    assert "Mốc Nghề" in runtime_skill_readme()
    assert "mocnghe --workspace" in runtime_skill_readme()
    for args in (["cv", "skill"], ["applications", "skill"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.output
        assert "mocnghe" in result.output


def test_renamed_cli_reuses_existing_legacy_database(tmp_path):
    import sqlite3

    from mocnghe.cli import app
    from mocnghe.ingestion.manual import import_jd_text_with_status
    from mocnghe.storage.repository import CareerRepository

    repository = CareerRepository(tmp_path)
    repository.initialize()
    job, _ = import_jd_text_with_status(
        repository, "Title: Synthetic pre-rename job", source_identity="synthetic"
    )
    legacy_database = tmp_path / "careerviet.sqlite3"
    assert repository.database_path == legacy_database
    with sqlite3.connect(legacy_database) as connection:
        connection.execute("CREATE TABLE legacy_marker (value TEXT)")
        connection.execute("INSERT INTO legacy_marker VALUES ('preserve-me')")
    result = CliRunner().invoke(app, ["--workspace", str(tmp_path), "jobs", "list"])
    assert result.exit_code == 0, result.output
    assert job.job_id in result.output
    assert not (tmp_path / "mocnghe.sqlite3").exists()
    with sqlite3.connect(legacy_database) as connection:
        assert connection.execute("SELECT value FROM legacy_marker").fetchone() == ("preserve-me",)

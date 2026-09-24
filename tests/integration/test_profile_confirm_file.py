"""Tests for `profile confirm-file` command — loads profile.json and saves confirmed profile."""

import json

from typer.testing import CliRunner

from mocnghe.cli import app
from mocnghe.storage.repository import CareerRepository

MINIMAL_PROFILE = {
    "profile_id": "test_confirmfile",
    "version": "1.0",
    "evidence": [
        {
            "evidence_id": "ev_test",
            "status": "candidate_confirmed",
            "summary": "Test evidence",
            "source": "test",
        }
    ],
    "required_facts": [],
}


def _run(runner, workspace, *args):
    result = runner.invoke(app, ["--workspace", str(workspace), *args])
    return result


def test_confirm_file_saves_confirmed_profile(tmp_path):
    """confirm-file reads profile.json, sets confirmed_at, saves to DB."""
    ws = tmp_path / "ws"
    runner = CliRunner()
    _run(runner, ws, "init")

    profile_file = ws / "profile.json"
    profile_file.write_text(json.dumps(MINIMAL_PROFILE), encoding="utf-8")

    result = _run(runner, ws, "profile", "confirm-file")
    assert result.exit_code == 0, result.output + str(result.exception)
    assert "test_confirmfile" in result.stdout
    assert "1.0" in result.stdout

    repo = CareerRepository(ws)
    repo.initialize()
    profile = repo.get_latest_profile()
    assert profile is not None
    assert profile.profile_id == "test_confirmfile"
    assert profile.confirmed_at is not None


def test_confirm_file_missing_profile_json(tmp_path):
    """confirm-file exits non-zero when profile.json absent."""
    ws = tmp_path / "ws"
    runner = CliRunner()
    _run(runner, ws, "init")

    result = _run(runner, ws, "profile", "confirm-file")
    assert result.exit_code != 0


def test_confirm_file_invalid_json(tmp_path):
    """confirm-file exits non-zero on malformed profile.json."""
    ws = tmp_path / "ws"
    runner = CliRunner()
    _run(runner, ws, "init")

    (ws / "profile.json").write_text("{not valid json", encoding="utf-8")

    result = _run(runner, ws, "profile", "confirm-file")
    assert result.exit_code != 0


def test_confirm_file_schema_violation(tmp_path):
    """confirm-file exits non-zero when profile fails Pydantic validation."""
    ws = tmp_path / "ws"
    runner = CliRunner()
    _run(runner, ws, "init")

    bad = {"profile_id": "", "version": "1.0"}  # profile_id too short
    (ws / "profile.json").write_text(json.dumps(bad), encoding="utf-8")

    result = _run(runner, ws, "profile", "confirm-file")
    assert result.exit_code != 0


def test_confirm_file_triage_works_after(tmp_path):
    """After confirm-file, evaluate triage can find the confirmed profile."""
    ws = tmp_path / "ws"
    runner = CliRunner()
    _run(runner, ws, "init")

    jd = tmp_path / "jd.txt"
    jd.write_text("Title: Test Job\nCompany: ACME")
    import_result = _run(runner, ws, "import-jd", "--file", str(jd))
    assert import_result.exit_code == 0
    job_id = import_result.stdout.split()[1]

    (ws / "profile.json").write_text(json.dumps(MINIMAL_PROFILE), encoding="utf-8")
    confirm_result = _run(runner, ws, "profile", "confirm-file")
    assert confirm_result.exit_code == 0

    triage_result = _run(runner, ws, "evaluate", "triage", job_id)
    assert triage_result.exit_code == 0
    assert "verdict" in triage_result.stdout

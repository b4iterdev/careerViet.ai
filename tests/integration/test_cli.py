# pyright: reportMissingTypeStubs=false
from pathlib import Path

from typer.testing import CliRunner

from mocnghe.cli import app


def test_cli_init_import_twice_list_show_profile_doctor(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    jd_file = tmp_path / "jd.txt"
    fixture = Path(__file__).parents[1] / "fixtures" / "synthetic_customer_jd.txt"
    _ = jd_file.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    init_result = runner.invoke(app, ["--workspace", str(workspace), "init"])
    first_import = runner.invoke(app, ["--workspace", str(workspace), "import-jd", "--file", str(jd_file)])
    second_import = runner.invoke(app, ["--workspace", str(workspace), "import-jd", "--file", str(jd_file)])
    list_result = runner.invoke(app, ["--workspace", str(workspace), "jobs", "list"])
    job_id = list_result.output.split()[0]
    show_result = runner.invoke(app, ["--workspace", str(workspace), "jobs", "show", job_id])
    missing_result = runner.invoke(app, ["--workspace", str(workspace), "jobs", "show", "missing-job"])
    profile_result = runner.invoke(app, ["--workspace", str(workspace), "profile", "validation"])
    doctor_result = runner.invoke(app, ["--workspace", str(workspace), "doctor"])

    assert init_result.exit_code == 0, init_result.output
    assert "initialized" in init_result.output
    assert first_import.exit_code == 0, first_import.output
    assert second_import.exit_code == 0, second_import.output
    assert "existing" in second_import.output
    assert list_result.exit_code == 0, list_result.output
    assert list_result.output.count("Nhân viên chăm sóc khách hàng") == 1
    assert show_result.exit_code == 0, show_result.output
    assert "applied: false" in show_result.output
    assert "Hà Nội" in show_result.output
    assert missing_result.exit_code == 1
    assert "Job not found: missing-job" in missing_result.output
    assert profile_result.exit_code == 0, profile_result.output
    assert "No profile found" in profile_result.output
    assert doctor_result.exit_code == 0, doctor_result.output
    assert "database: ok" in doctor_result.output
    assert (Path(workspace) / "careerviet.sqlite3").exists()


def test_cli_profile_validation_validates_profile_json(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _ = (workspace / "profile.json").write_text(
        """
        {
          "profile_id": "profile-synthetic",
          "version": "2026-09-14",
          "evidence": [
            {
              "evidence_id": "ev-synthetic-1",
              "status": "candidate_confirmed",
              "summary": "Synthetic candidate confirmed customer support shift experience.",
              "source": "synthetic test fixture"
            }
          ],
          "required_facts": [
            {
              "fact_id": "fact-missing",
              "label": "Unsupported credential must be rejected",
              "evidence_ids": ["missing-evidence"]
            }
          ],
          "preferences": {
            "wants_internship": false,
            "wants_full_time": true
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--workspace", str(workspace), "profile", "validation"])

    assert result.exit_code == 1
    assert "profile: invalid" in result.output


def test_cli_import_jd_rejects_stdin_paste_with_file(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    jd_file = tmp_path / "non_tech_retail_jd.txt"
    _ = jd_file.write_text(
        """
Tiêu đề: Nhân viên kho
Công ty: Kho vận Ví dụ
Địa điểm: Bình Dương
Lương: Chưa rõ
Mô tả: Sắp xếp hàng trong kho.
Yêu cầu: Cẩn thận và đúng giờ.
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "import-jd",
            "--file",
            str(jd_file),
            "--stdin",
        ],
        input="Tiêu đề: Nhân viên bán hàng\nMô tả: pasted JD",
    )

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()
    assert not (workspace / "careerviet.sqlite3").exists()

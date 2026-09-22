# pyright: reportMissingTypeStubs=false
import json
from pathlib import Path

from typer.testing import CliRunner

from mocnghe.assets import runtime_skill_readme
from mocnghe.cli import app


def test_m3_temp_cli_onboarding_triage_export_import_and_runtime_asset(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace = tmp_path / "workspace"
    draft_id = "draft-cli-synthetic"
    answers = [
        "Synthetic candidate Minh, contact private, based in Ha Noi.",
        "Targets: retail cashier first, warehouse associate second.",
        "Experience: cashier 2021-01 to 2024-01 full-time; volunteered at a food bank.",
        "Education: high school diploma.",
        "License: forklift safety certificate expires 2027-05-01.",
        "Skills: POS, inventory; Languages: Vietnamese native, English basic.",
        "Preferences: Ha Noi, remote no, shifts day, no travel, exclude tobacco industry.",
        "Compensation: full-time floor 9000000 VND/month gross; internship floor unknown.",
        "Availability: current immediate for full-time; future internship unavailable.",
    ]
    for answer in answers:
        result = runner.invoke(
            app,
            ["--workspace", str(workspace), "profile", "answer", "--draft-id", draft_id, "--text", answer],
        )
        assert result.exit_code == 0, result.output

    review = runner.invoke(app, ["--workspace", str(workspace), "profile", "review", "--draft-id", draft_id])
    correction = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "profile",
            "correct",
            "--draft-id",
            draft_id,
            "--field",
            "preferences",
            "--text",
            "Preferences: Ha Noi or Bac Ninh, remote no, shifts day, no travel, exclude tobacco industry.",
        ],
    )
    confirm = runner.invoke(app, ["--workspace", str(workspace), "profile", "confirm", "--draft-id", draft_id])
    assert review.exit_code == 0, review.output
    assert "ready_for_confirmation" in review.output
    assert correction.exit_code == 0, correction.output
    assert confirm.exit_code == 0, confirm.output
    profile_version = confirm.output.strip().split("version=")[1]

    jd_file = tmp_path / "retail_jd.txt"
    jd_file.write_text(
        """
Tiêu đề: Retail Cashier
Công ty: Synthetic Shop
Địa điểm: Ha Noi
Loại hình: Toàn thời gian
Lương: Chưa rõ
Mô tả: Serve shoppers and maintain inventory.
Yêu cầu: Python inventory scripting
Warehouse operations
""".strip(),
        encoding="utf-8",
    )
    imported = runner.invoke(app, ["--workspace", str(workspace), "import-jd", "--file", str(jd_file)])
    assert imported.exit_code == 0, imported.output
    job_id = imported.output.split()[1]

    triage = runner.invoke(app, ["--workspace", str(workspace), "evaluate", "triage", job_id])
    assert triage.exit_code == 0, triage.output
    assert "verdict: evaluate_with_unknowns" in triage.output

    packet_path = tmp_path / "packet.json"
    export = runner.invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "evaluate",
            "export-packet",
            job_id,
            "--profile-version",
            profile_version,
            "--output",
            str(packet_path),
            "--consent",
        ],
    )
    assert export.exit_code == 0, export.output
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert "Synthetic candidate" not in packet_path.read_text(encoding="utf-8")

    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "packet_id": packet["packet_id"],
                "profile_version": packet["profile_version"],
                "job_id": packet["job_id"],
                "jd_content_hash": packet["jd_content_hash"],
                "model": "mock-model",
                "runtime": "cli-import-fixture",
                "verdict": "human_review",
                "confidence": "medium",
                "requirement_judgments": [
                    {
                        "requirement_id": "req_001",
                        "status": "human_review",
                        "evidence_ids": [],
                        "source_quotes": [],
                        "gaps": ["Python inventory scripting needs human review."],
                        "questions": ["Confirm Python inventory scripting depth."],
                    },
                    {
                        "requirement_id": "req_002",
                        "status": "human_review",
                        "evidence_ids": [],
                        "source_quotes": [],
                        "gaps": ["Warehouse operations need human review."],
                        "questions": ["Confirm warehouse operations depth."],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    imported_report = runner.invoke(
        app,
        ["--workspace", str(workspace), "evaluate", "import-report", "--packet", str(packet_path), "--response", str(report_path)],
    )
    doctor = runner.invoke(app, ["--workspace", str(workspace), "doctor"])

    assert imported_report.exit_code == 0, imported_report.output
    assert "stored report" in imported_report.output
    assert "evaluation_reports: 1" in doctor.output
    assert "CLI-agent evaluation skill" in runtime_skill_readme()

import json
from datetime import UTC, datetime

from pypdf import PdfReader
from typer.testing import CliRunner

from mocnghe.cli import app
from mocnghe.models.profile import CandidateEvidence, CandidateProfile
from mocnghe.storage.repository import CareerRepository


def test_m4_full_cli(tmp_path):
    repo = CareerRepository(tmp_path / "workspace")
    repo.save_confirmed_profile(CandidateProfile(
        profile_id="synthetic", version="v1", confirmed_at=datetime.now(UTC),
        identity={"name": "Ứng viên mẫu"}, evidence=[CandidateEvidence(
            evidence_id="ev1", status="candidate_confirmed", source="synthetic",
            summary="Tình nguyện hỗ trợ khách hàng.", provenance="experience")]))
    runner = CliRunner()
    def run(*args):
        result = runner.invoke(app, ["--workspace", str(repo.workspace), *args])
        assert result.exit_code == 0, result.output + str(result.exception)
        return result.output
    cv = json.loads(run("cv", "create", "--profile-version", "v1", "--evidence", "ev1",
                        "--language", "vi", "--identity", "name"))
    reviewed = json.loads(run("cv", "review", cv["id"]))
    run("cv", "approve", cv["id"], "--hash", reviewed["content_hash"])
    run("cv", "export", cv["id"], "--output", str(tmp_path / "pdf"), "--max-pages", "1")
    assert "Ứng viên mẫu" in PdfReader(tmp_path / "pdf/cv.pdf").pages[0].extract_text()
    assert run("cv", "list").strip()
    packet_dir = tmp_path / "packet"
    run("cv", "export-packet", cv["id"], "--output", str(packet_dir), "--consent")
    packet = json.loads((packet_dir / "packet.json").read_text())
    response = tmp_path / "response.json"
    response.write_text(json.dumps({"packet_hash": packet["packet_hash"], "claims": packet["claims"]}))
    revised = json.loads(run("cv", "import-response", cv["id"], "--response", str(response)))
    assert revised["id"] != cv["id"]
    jd = tmp_path / "jd.txt"
    jd.write_text("Tiêu đề: Hỗ trợ khách hàng\nYêu cầu: Giao tiếp")
    run("import-jd", "--file", str(jd))
    job_id = repo.list_jobs()[0].job_id
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps({"questions": ["Start date?"], "answers": {}}))
    draft = json.loads(run("draft", "create", cv["id"], "--job-id", job_id,
                           "--subject", "Exact subject", "--route", "Employer form",
                           "--questions", str(questions)))
    review = json.loads(run("draft", "review", draft["id"]))
    run("draft", "approve", draft["id"], "--hash", review["content_hash"])
    run("draft", "export", draft["id"], "--output", str(tmp_path / "application"))
    assert "UNANSWERED" in (tmp_path / "application/form.txt").read_text()
    assert not repo.get_job(job_id).applied
    assert "m4" in run("cv", "skill").lower()

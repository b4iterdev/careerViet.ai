"""Synthetic M4 CLI smoke; outputs are retained in a new OS temp directory for review."""
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pymupdf

from mocnghe.models.profile import CandidateEvidence, CandidateProfile
from mocnghe.storage.repository import CareerRepository


def main():
    root = Path(tempfile.mkdtemp(prefix="mocnghe-m4-demo-"))
    workspace = root / "workspace"
    repo = CareerRepository(workspace)
    texts = {
        "en": [
            ("experience", "Volunteered at a synthetic community learning centre, helping learners use classroom computers."),
            ("experience", "Completed a synthetic software internship: wrote Python tests and documented reproducible defects."),
            ("education", "Synthetic Bachelor of Information Technology programme, 2024–2028 (in progress)."),
            ("skills", "Python testing, technical documentation and basic Linux troubleshooting."),
        ],
        "vi": [
            ("experience", "Tình nguyện tại trung tâm học tập cộng đồng giả lập, hỗ trợ học viên sử dụng máy tính trong lớp."),
            ("experience", "Hoàn thành kỳ thực tập phần mềm giả lập: viết kiểm thử Python và ghi lại lỗi có thể tái hiện."),
            ("education", "Chương trình Cử nhân Công nghệ thông tin giả lập, 2024–2028 (đang học)."),
            ("skills", "Kiểm thử Python, viết tài liệu kỹ thuật và xử lý sự cố Linux cơ bản."),
        ],
    }
    # Exercise the installed console script in separate processes.
    def cli(*args):
        proc = subprocess.run([str(Path(sys.executable).parent / "mocnghe"),
                               "--workspace", str(workspace), *args],
                              text=True, capture_output=True, timeout=40, check=False)
        if proc.returncode:
            raise RuntimeError(proc.stdout + proc.stderr)
        return proc.stdout
    pdfs = []
    for lang, claims in texts.items():
        profile = CandidateProfile(profile_id="synthetic-demo", version=f"synthetic-{lang}",
            confirmed_at=datetime.now(UTC), identity={"name": "Synthetic Candidate" if lang == "en"
            else "Ứng viên giả lập", "email": "synthetic@example.invalid"}, evidence=[
                CandidateEvidence(evidence_id=f"e{i}", summary=text, source="synthetic-demo",
                                  status="candidate_confirmed", provenance=section, uncertainty="low")
                for i, (section, text) in enumerate(claims)])
        repo.save_confirmed_profile(profile)
        args = ["cv", "create", "--profile-version", profile.version, "--language", lang,
                "--identity", "name", "--identity", "email"]
        for i in range(len(claims)):
            args.extend(["--evidence", f"e{i}"])
        cv = json.loads(cli(*args))
        review = json.loads(cli("cv", "review", cv["id"]))
        cli("cv", "approve", cv["id"], "--hash", review["content_hash"])
        out = root / lang
        cli("cv", "export", cv["id"], "--output", str(out), "--max-pages", "1")
        with pymupdf.open(out / "cv.pdf") as pdf:
            assert len(pdf) == 1
            extracted = " ".join(pdf[0].get_text().split())
            for _, text in claims:
                assert " ".join(text.split()) in extracted
            for block in pdf[0].get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        x0, y0, x1, y1 = span["bbox"]
                        assert 0 <= x0 < x1 <= pdf[0].rect.width
                        assert 0 <= y0 < y1 <= pdf[0].rect.height
            pdf[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(out / "preview.png")
        jd = root / f"jd-{lang}.txt"
        jd.write_text(f"Tiêu đề: Synthetic software intern {lang}\nYêu cầu: Python testing", encoding="utf-8")
        cli("import-jd", "--file", str(jd))
        job_id = repo.list_jobs()[-1].job_id
        questions = root / f"questions-{lang}.json"
        questions.write_text(json.dumps({"questions": ["Relevant experience?", "Start date?"],
                                         "answers": {"0": "e1"}}))
        draft = json.loads(cli("draft", "create", cv["id"], "--job-id", job_id,
            "--subject", f"[SYNTHETIC] Application {lang}", "--route", "Synthetic employer portal",
            "--questions", str(questions)))
        review = json.loads(cli("draft", "review", draft["id"]))
        cli("draft", "approve", draft["id"], "--hash", review["content_hash"])
        cli("draft", "export", draft["id"], "--output", str(root / f"application-{lang}"))
        assert not repo.get_job(job_id).applied
        assert "UNANSWERED" in (root / f"application-{lang}/form.txt").read_text()
        pdfs.append(str(out / "cv.pdf"))
    print(json.dumps({"status": "M4_SYNTHETIC_CLI_SMOKE_OK", "root": str(root), "pdfs": pdfs}, indent=2))


if __name__ == "__main__":
    main()

import json
from datetime import UTC, datetime

import pytest
from pypdf import PdfReader

from careerviet.cv import CVService
from careerviet.cv_render import export_cv
from careerviet.models.profile import CandidateEvidence, CandidateProfile


def test_missing_glyph_fails_instead_of_corrupt_pdf(repo, tmp_path):
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    claims = [c.model_dump() for c in cv.claims]
    claims[0].update(text="Unsupported glyph: 漢", mode="proposed")
    revision = s.revise(cv.id, claims, provenance="human-proposed")
    s.approve(revision.id, s.content_hash(revision))
    with pytest.raises(ValueError, match="glyph"):
        export_cv(s, revision.id, tmp_path / "missing-glyph")
    assert not (tmp_path / "missing-glyph").exists()


def test_tampered_profile_cannot_seed_new_cv(repo):
    with repo.connect() as db:
        db.execute("UPDATE profiles SET payload_json=replace(payload_json, ?, ?)",
                   ("khách hàng", "bệnh nhân"))
    with pytest.raises(ValueError, match="canonical profile"):
        CVService(repo).create("v1", ["ev1"], language="vi")


def test_render_overflow_does_not_publish_and_markup_is_literal(repo, tmp_path):
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    claims = [c.model_dump() for c in cv.claims]
    claims[0].update(text='<img src="file:///etc/passwd"/> #include("secret") & <b>literal</b>',
                     mode="proposed")
    revised = s.revise(cv.id, claims, provenance="human-proposed")
    s.approve(revised.id, s.content_hash(revised))
    export_cv(s, revised.id, tmp_path / "literal")
    text = PdfReader(tmp_path / "literal/cv.pdf").pages[0].extract_text()
    assert '<img src="file:///etc/passwd"/>' in text and '<b>literal</b>' in text
    claims[0]["text"] = "Long synthetic experience sentence. " * 300
    long_cv = s.revise(cv.id, claims, provenance="human-proposed")
    s.approve(long_cv.id, s.content_hash(long_cv))
    with pytest.raises(ValueError, match="page budget"):
        export_cv(s, long_cv.id, tmp_path / "overflow", max_pages=1)
    assert not (tmp_path / "overflow").exists()


@pytest.mark.parametrize("summary,section", [
    ("Developed a synthetic software test suite.", "experience"),
    ("Hỗ trợ khách hàng tại cửa hàng mẫu.", "experience"),
    ("Thực tập hỗ trợ điều dưỡng; chưa có giấy phép hành nghề.", "credentials"),
])
def test_occupations_and_embedded_font(tmp_path, summary, section):
    from careerviet.storage.repository import CareerRepository
    repo = CareerRepository(tmp_path / "workspace")
    repo.save_confirmed_profile(CandidateProfile(profile_id="synthetic", version="v1",
        confirmed_at=datetime.now(UTC), evidence=[CandidateEvidence(evidence_id="e",
        status="candidate_confirmed", summary=summary, provenance=section, source="synthetic")]))
    s = CVService(repo)
    cv = s.create("v1", ["e"], language="vi")
    s.approve(cv.id, s.content_hash(cv))
    export_cv(s, cv.id, tmp_path / "out", max_pages=1)
    reader = PdfReader(tmp_path / "out/cv.pdf")
    assert summary in reader.pages[0].extract_text()
    fonts = reader.pages[0]["/Resources"]["/Font"]
    assert any("/FontFile2" in f.get_object().get("/FontDescriptor", {}) for f in fonts.values())


def test_tampered_cv_hash_and_unknown_profile(repo):
    s = CVService(repo)
    with pytest.raises(ValueError, match="confirmed"):
        s.create("missing", ["ev1"], language="en")
    cv = s.create("v1", ["ev1"], language="en")
    with repo.connect() as db:
        db.execute("UPDATE cv_revisions SET hash=? WHERE id=?", ("0"*64, cv.id))
    with pytest.raises(ValueError, match="hash"):
        s.get(cv.id)


def test_structural_questions_rejected_before_persistence(repo):
    from careerviet.application_drafts import ApplicationDraftService
    from careerviet.ingestion.manual import import_jd_text_with_status
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    s.approve(cv.id, s.content_hash(cv))
    job, _ = import_jd_text_with_status(repo, "Tiêu đề: Synthetic", source_identity="synthetic")
    apps = ApplicationDraftService(s)
    with pytest.raises(ValueError, match="questions"):
        apps.create(cv.id, job.job_id, subject="Subject", route="manual", questions="not a list")


def test_stale_job_blocks_approval(repo):
    from careerviet.ingestion.manual import import_jd_text_with_status
    job, _ = import_jd_text_with_status(repo, "Tiêu đề: Synthetic", source_identity="synthetic")
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en", job_id=job.job_id)
    with repo.connect() as db:
        db.execute("UPDATE jobs SET title=? WHERE job_id=?", ("Changed normalized title", job.job_id))
    with pytest.raises(ValueError, match="stale canonical job"):
        s.approve(cv.id, s.content_hash(cv))


def test_provider_failure_no_new_revision(repo):
    import httpx

    from careerviet.cv_runtime import run_provider
    from careerviet.evaluation_runtime import EvaluationProviderConfig
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    config = EvaluationProviderConfig(endpoint="https://provider.invalid/v1/chat/completions",
                                      model="mock", api_key="DO_NOT_LEAK", max_response_bytes=20)
    for code, body in [(302, "redirect"), (401, "DO_NOT_LEAK"), (429, "error"),
                       (500, "error"), (200, "not json"), (200, "x" * 30)]:
        transport = httpx.MockTransport(lambda req, code=code, body=body: httpx.Response(code, text=body))
        with pytest.raises(RuntimeError) as error:
            run_provider(s, cv.id, config, consent=True, transport=transport)
        assert "DO_NOT_LEAK" not in str(error.value)
    with repo.connect() as db:
        assert db.execute("SELECT count(*) FROM cv_revisions").fetchone()[0] == 1


def test_provider_real_loopback_http(repo):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from careerviet.cv_runtime import run_provider
    from careerviet.evaluation_runtime import EvaluationProviderConfig
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            packet = json.loads(request["messages"][1]["content"])
            seen.append(packet)
            body = json.dumps({"choices": [{"message": {"content": json.dumps({
                "packet_hash": packet["packet_hash"], "claims": packet["claims"]})}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = EvaluationProviderConfig(endpoint=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                         model="synthetic-loopback", api_key="synthetic", allow_loopback_http=True)
        result = run_provider(s, cv.id, config, consent=True)
        assert seen and result.id != cv.id and not s.approved(result.id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_slow_drip_body_cancelled_at_deadline(repo):
    """Provider dripping bytes slowly must not survive past timeout_seconds."""
    import asyncio
    import time

    import httpx

    from careerviet.cv_runtime import _request_with_deadline
    from careerviet.evaluation_runtime import EvaluationProviderConfig

    config = EvaluationProviderConfig(
        endpoint="https://provider.invalid/v1/chat/completions",
        model="x", api_key="x", timeout_seconds=0.15, max_response_bytes=1_000_000,
    )

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(20):
                await asyncio.sleep(0.05)   # 1 byte every 50 ms → 1 s total
                yield b"x"

    class AsyncSlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, stream=SlowStream())

    start = time.monotonic()
    with pytest.raises(RuntimeError, match="time budget"):
        asyncio.run(_request_with_deadline(config, {}, AsyncSlowTransport()))
    elapsed = time.monotonic() - start
    # Must cancel well within 2× the budget, not after full 1 s body
    assert elapsed < 0.5, f"deadline not enforced: took {elapsed:.3f}s"


def test_partial_export_leaves_no_artefact(repo, tmp_path):
    """If export fails mid-way the output directory must not exist."""
    import unittest.mock

    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    s.approve(cv.id, s.content_hash(cv))
    dest = tmp_path / "partial"

    # Patch SimpleDocTemplate.build so it fails during render (before publish_bundle moves files)
    with unittest.mock.patch(
        "reportlab.platypus.SimpleDocTemplate.build",
        side_effect=OSError("simulated disk failure"),
    ), pytest.raises(OSError):
        export_cv(s, cv.id, dest)

    assert not dest.exists(), "failed export must not leave a partial directory"


def test_draft_payload_tampering_detected(repo):
    """Altering a draft's content_hash after creation raises on reload."""
    from careerviet.application_drafts import ApplicationDraftService
    from careerviet.ingestion.manual import import_jd_text_with_status

    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en")
    s.approve(cv.id, s.content_hash(cv))
    job, _ = import_jd_text_with_status(repo, "Tiêu đề: Synthetic", source_identity="synthetic")
    apps = ApplicationDraftService(s)
    draft = apps.create(cv.id, job.job_id, subject="Test subject", route="manual")

    # Tamper with the stored hash
    with repo.connect() as db:
        db.execute(
            "UPDATE application_drafts SET hash=? WHERE id=?",
            ("0" * 64, draft.id),
        )

    with pytest.raises(ValueError, match="hash"):
        apps.get(draft.id)

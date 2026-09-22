import pytest

from mocnghe.cv import CVService
from mocnghe.ingestion.manual import import_jd_text_with_status


def test_application_grounding_persistence_and_export(repo, tmp_path):
    from mocnghe.application_drafts import ApplicationDraftService
    job, _ = import_jd_text_with_status(repo, "Tiêu đề: Hỗ trợ khách hàng\nYêu cầu: Giao tiếp",
                                        source_identity="synthetic")
    cvs = CVService(repo)
    cv = cvs.create("v1", ["ev1"], language="vi", job_id=job.job_id)
    apps = ApplicationDraftService(cvs)
    with pytest.raises(PermissionError):
        apps.create(cv.id, job.job_id, subject="[CS] Exact subject", route="Employer portal")
    cvs.approve(cv.id, cvs.content_hash(cv))
    draft = apps.create(cv.id, job.job_id, subject="[CS] Exact subject", route="Employer portal",
                        questions=["Ngày bắt đầu?", "Kinh nghiệm?"], answers={"1": "ev1"})
    assert draft.subject == "[CS] Exact subject"
    assert draft.answers[0].text is None
    assert draft.answers[1].text == cv.claims[0].text
    assert draft.state == "draft"
    assert ApplicationDraftService(cvs).get(draft.id) == draft
    with pytest.raises(PermissionError):
        apps.export(draft.id, tmp_path / "application")
    apps.approve(draft.id, apps.content_hash(draft))
    apps.export(draft.id, tmp_path / "application")
    assert (tmp_path / "application" / "email.txt").read_text().startswith("[CS] Exact subject")
    assert "UNANSWERED" in (tmp_path / "application" / "form.txt").read_text()
    assert not repo.get_job(job.job_id).applied

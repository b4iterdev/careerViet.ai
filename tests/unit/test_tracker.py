import pytest

from mocnghe.ingestion.manual import import_jd_text_with_status


def test_apply_requires_confirmation_and_preserves_snapshot(repo):
    from mocnghe.applications.tracker import ApplicationTracker
    from mocnghe.cv import CVService
    job, _ = import_jd_text_with_status(repo, 'Title: Synthetic tracking job', source_identity='synthetic')
    tracker = ApplicationTracker(repo)
    cvs = CVService(repo)
    cv = cvs.create('v1', ['ev1'], language='en', job_id=job.job_id)
    tracker.transition(job.job_id, 'shortlisted')
    tracker.transition(job.job_id, 'drafting')
    with pytest.raises(PermissionError):
        tracker.transition(job.job_id, 'ready', cv_id=cv.id)
    cvs.approve(cv.id, cvs.content_hash(cv))
    tracker.transition(job.job_id, 'ready', cv_id=cv.id)
    with pytest.raises(PermissionError):
        tracker.transition(job.job_id, 'applied', cv_id=cv.id)
    applied = tracker.transition(job.job_id, 'applied', cv_id=cv.id, confirm=True)
    assert applied['cv_version'] == cv.id and applied['applied_at']
    assert applied['jd_content_hash'] == job.content_hash
    assert repo.get_job(job.job_id).applied
    assert cvs.approved(cv.id)  # Tracking metadata must not invalidate CV content.
    tracker.transition(job.job_id, 'interviewing')
    assert tracker.get(job.job_id)['applied_at'] == applied['applied_at']
    assert tracker.get(job.job_id)['submission_json'] == applied['submission_json']
    with repo.connect() as db:
        db.execute('UPDATE jobs SET title=? WHERE job_id=?', ('Updated JD', job.job_id))
    assert tracker.get(job.job_id)['submission_json'] == applied['submission_json']
    assert len(tracker.history(job.job_id)) == 5


def test_application_contract_preserves_submission_after_interview():
    from datetime import UTC, datetime

    from mocnghe.models.application import Application
    recorded = datetime.now(UTC)
    record = Application(job_id="synthetic", state="interviewing", applied_at=recorded,
                         cv_version="cv-synthetic", jd_content_hash="a" * 64)
    assert record.applied_at == recorded


def test_transitions_persist_and_reject_invalid(repo):
    from mocnghe.applications.tracker import ApplicationTracker
    job, _ = import_jd_text_with_status(repo, 'Title: Synthetic tracking job', source_identity='synthetic')
    tracker = ApplicationTracker(repo)
    assert tracker.get(job.job_id)['state'] == 'discovered'
    tracker.transition(job.job_id, 'shortlisted')
    assert ApplicationTracker(repo).get(job.job_id)['state'] == 'shortlisted'
    with pytest.raises(ValueError, match='transition'):
        tracker.transition(job.job_id, 'offer')
    assert len(tracker.history(job.job_id)) == 1
    assert not repo.get_job(job.job_id).applied
    assert tracker.list('shortlisted')[0]['job_id'] == job.job_id
    with pytest.raises(ValueError, match='not found'):
        tracker.get('missing')

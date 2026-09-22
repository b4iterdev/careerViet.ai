import pytest

from mocnghe.applications.tracker import ApplicationTracker
from mocnghe.cv import CVService
from mocnghe.ingestion.manual import import_jd_text_with_status


@pytest.mark.parametrize('change', ['profile_hash', 'job_title'])
def test_change_after_validation_is_rejected(repo, monkeypatch, change):
    job, _ = import_jd_text_with_status(repo, 'Title: Synthetic race', source_identity='race')
    cvs = CVService(repo)
    cv = cvs.create('v1', ['ev1'], language='en', job_id=job.job_id)
    cvs.approve(cv.id, cvs.content_hash(cv))
    tracker = ApplicationTracker(repo)
    tracker.transition(job.job_id, 'shortlisted')
    tracker.transition(job.job_id, 'drafting')
    original = CVService.approved

    def racing_approved(self, cv_id):
        result = original(self, cv_id)
        with repo.connect() as db:
            if change == 'profile_hash':
                db.execute("UPDATE profiles SET content_hash=? WHERE version='v1'", ('0' * 64,))
            else:
                db.execute('UPDATE jobs SET title=? WHERE job_id=?', ('Changed', job.job_id))
        return result

    monkeypatch.setattr(CVService, 'approved', racing_approved)
    with pytest.raises(ValueError, match='canonical'):
        tracker.transition(job.job_id, 'ready', cv_id=cv.id)
    assert tracker.get(job.job_id)['state'] == 'drafting'
    assert not repo.get_job(job.job_id).applied


def test_migration_locks_before_column_discovery(repo, monkeypatch):
    original = repo.connect
    inspected = []

    class ConnectionProxy:
        def __init__(self):
            self.connection = original()
        def __enter__(self):
            self.connection.__enter__()
            return self
        def __exit__(self, *args):
            return self.connection.__exit__(*args)
        def execute(self, sql, *args):
            if sql == 'PRAGMA table_info(applications)':
                inspected.append(True)
                assert self.connection.in_transaction, 'migration requires write lock before discovery'
            return self.connection.execute(sql, *args)

    monkeypatch.setattr(repo, 'connect', ConnectionProxy)
    ApplicationTracker(repo)
    assert inspected

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from mocnghe.applications.tracker import ApplicationTracker
from mocnghe.storage.repository import CareerRepository


def test_repository_locks_before_schema_migration(tmp_path, monkeypatch):
    original = CareerRepository._ensure_jobs_columns

    def checked(self, connection):
        assert connection.in_transaction, 'schema discovery requires a write transaction'
        return original(self, connection)

    monkeypatch.setattr(CareerRepository, '_ensure_jobs_columns', checked)
    ApplicationTracker(CareerRepository(tmp_path / 'fresh'))


def test_concurrent_first_use_on_fresh_database(tmp_path):
    for round_number in range(20):
        workspace = tmp_path / str(round_number)
        barrier = Barrier(8)

        def construct(_, workspace=workspace, barrier=barrier):
            repo = CareerRepository(workspace)
            barrier.wait(timeout=10)
            tracker = ApplicationTracker(repo)
            assert tracker.list() == []

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(construct, range(8)))
        repo = CareerRepository(workspace)
        with repo.connect() as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
            assert {'benefits', 'freeform_text'} <= columns
            columns = {row[1] for row in db.execute('PRAGMA table_info(applications)')}
            assert {'submission_json', 'submission_hash'} <= columns

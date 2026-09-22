"""Transactional local state transitions and append-only event history."""
import hashlib
import json
from datetime import UTC, datetime

from ..cv import CVService, digest
from ..models.application import ApplicationState
from ..models.profile import CandidateProfile

TRANSITIONS = {
    "discovered": {"shortlisted", "archived"},
    "shortlisted": {"drafting", "withdrawn", "archived"},
    "drafting": {"ready", "shortlisted", "withdrawn", "archived"},
    "ready": {"drafting", "applied", "withdrawn", "archived"},
    "applied": {"interviewing", "offer", "rejected", "withdrawn", "archived"},
    "interviewing": {"offer", "rejected", "withdrawn", "archived"},
    "offer": {"withdrawn", "archived"},
    "rejected": {"archived"}, "withdrawn": {"archived"}, "archived": set(),
}


class ApplicationTracker:
    def __init__(self, repo):
        self.repo = repo
        repo.initialize()
        with repo.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            columns = {r[1] for r in db.execute("PRAGMA table_info(applications)")}
            for name in ("submission_json", "submission_hash"):
                if name not in columns:
                    db.execute(f"ALTER TABLE applications ADD COLUMN {name} TEXT")
            db.execute("CREATE TABLE IF NOT EXISTS application_events "
                       "(event_id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), "
                       "from_state TEXT NOT NULL, to_state TEXT NOT NULL, recorded_at TEXT NOT NULL)")

    def _row(self, db, job_id):
        rows = db.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchall()
        if not rows:
            raise ValueError("application not found")
        if len(rows) != 1:
            raise ValueError("ambiguous legacy application rows")
        row = dict(rows[0])
        if row["submission_json"] is not None:
            actual = hashlib.sha256(row["submission_json"].encode()).hexdigest()
            if actual != row["submission_hash"]:
                raise ValueError("submission snapshot hash mismatch")
        return row

    def get(self, job_id):
        with self.repo.connect() as db:
            return self._row(db, job_id)

    def list(self, state=None):
        if state is not None:
            ApplicationState(state)
        with self.repo.connect() as db:
            ids = db.execute("SELECT DISTINCT job_id FROM applications ORDER BY job_id").fetchall()
            rows = [self._row(db, row[0]) for row in ids]
        return [row for row in rows if state is None or row["state"] == state]

    def history(self, job_id):
        with self.repo.connect() as db:
            self._row(db, job_id)
            return [dict(row) for row in db.execute(
                "SELECT * FROM application_events WHERE job_id=? ORDER BY event_id", (job_id,))]

    def transition(self, job_id, state, *, cv_id=None, confirm=False):
        if state == "applied" and confirm is not True:
            raise PermissionError("explicit confirmation of manual submission required")
        if state not in {"ready", "applied"} and cv_id is not None:
            raise ValueError("CV selection only allowed for ready/applied")
        snapshot = None
        if state in {"ready", "applied"}:
            if not cv_id:
                raise ValueError("approved CV required")
            cvs = CVService(self.repo)
            cv = cvs.get(cv_id)
            if not cvs.approved(cv_id):
                raise PermissionError("approved CV required")
            job = self.repo.get_job(job_id)
            if job is None or (cv.job_id and cv.job_id != job_id):
                raise ValueError("CV targets a different or missing job")
            # Capture exact rows validated by CVService; compare again under write lock.
            with self.repo.connect() as check:
                profile = dict(check.execute("SELECT * FROM profiles WHERE version=?",
                                             (cv.profile_version,)).fetchone())
            snapshot = json.dumps({"cv": cv.model_dump(mode="json"), "cv_hash": digest(cv),
                                   "job": job.model_dump(mode="json"), "job_hash": digest(job),
                                   "profile_version": cv.profile_version}, sort_keys=True)
        with self.repo.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, job_id)
            if state not in TRANSITIONS.get(row["state"], set()):
                raise ValueError("invalid application transition")
            if snapshot is not None:
                current_job = self.repo._job_from_row(db.execute(
                    "SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())
                stored_cv = db.execute("SELECT payload, hash FROM cv_revisions WHERE id=?", (cv_id,)).fetchone()
                approval = db.execute("SELECT hash FROM cv_approvals WHERE id=?", (cv_id,)).fetchone()
                current_profile = dict(db.execute("SELECT * FROM profiles WHERE version=?",
                                                  (cv.profile_version,)).fetchone())
                canonical_profile = CandidateProfile.model_validate_json(current_profile["payload_json"])
                if (hashlib.sha256(canonical_profile.model_dump_json().encode()).hexdigest()
                        != current_profile["content_hash"] or
                        canonical_profile.confirmed_at is None or digest(canonical_profile) != cv.profile_hash or
                        (cv.job_id is not None and digest(current_job) != cv.job_hash)):
                    raise ValueError("stale canonical profile or targeted job")
                if (digest(current_job) != digest(job) or current_profile != profile or
                        stored_cv is None or stored_cv["payload"] != cv.model_dump_json() or
                        stored_cv["hash"] != digest(cv) or approval is None or approval[0] != digest(cv)):
                    raise ValueError("canonical content changed during transition")
                if state == "applied" and (row["cv_version"] != cv_id or row["submission_json"] != snapshot):
                    raise ValueError("ready selection is stale; return to drafting and review")
                db.execute("UPDATE applications SET cv_version=?, jd_content_hash=?, "
                           "submission_json=?, submission_hash=? WHERE application_id=?",
                           (cv_id, job.content_hash, snapshot, hashlib.sha256(snapshot.encode()).hexdigest(),
                            row["application_id"]))
            if state == "applied":
                db.execute("UPDATE applications SET applied_at=? WHERE application_id=?",
                           (datetime.now(UTC).isoformat(), row["application_id"]))
                db.execute("UPDATE jobs SET applied=1 WHERE job_id=?", (job_id,))
            db.execute("UPDATE applications SET state=? WHERE application_id=?",
                       (state, row["application_id"]))
            db.execute("INSERT INTO application_events(job_id, from_state, to_state, recorded_at) "
                       "VALUES (?, ?, ?, ?)",
                       (job_id, row["state"], state, datetime.now(UTC).isoformat()))
        return self.get(job_id)

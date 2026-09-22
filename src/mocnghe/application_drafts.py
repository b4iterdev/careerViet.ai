"""Drafts are local documents, not submissions or application tracker transitions."""
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .cv import digest
from .cv_render import publish_bundle


class FormAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    evidence_id: str | None = None
    text: str | None = None


class ApplicationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    state: Literal["draft"] = "draft"
    cv_id: str
    cv_hash: str
    profile_version: str
    profile_hash: str
    job_id: str
    job_hash: str
    language: Literal["en", "vi"]
    subject: str = Field(min_length=1, max_length=1000)
    route: str = Field(min_length=1, max_length=4000)
    body: str
    answers: list[FormAnswer] = Field(default_factory=list, max_length=100)
    warning: str = ("Local draft only; confirm route, subject, evidence relevance and unanswered "
                    "questions. No CV attached; no submission performed.")


class ApplicationDraftService:
    content_hash = staticmethod(digest)

    def __init__(self, cvs):
        self.cvs = cvs
        self.repo = cvs.repo
        with self.repo.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS application_drafts "
                       "(id TEXT PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS application_draft_approvals "
                       "(id TEXT PRIMARY KEY REFERENCES application_drafts(id), hash TEXT NOT NULL)")

    def create(self, cv_id, job_id, *, subject, route, questions=(), answers=None):
        if not isinstance(questions, (list, tuple)) or len(questions) > 100:
            raise ValueError("questions must be a list of at most 100 strings")
        if any(not isinstance(q, str) or not q.strip() for q in questions):
            raise ValueError("questions must be nonempty strings")
        if answers is not None and (not isinstance(answers, dict) or
                any(not isinstance(k, str) or not isinstance(v, str) for k, v in answers.items())):
            raise ValueError("questions answers must map string indexes to evidence ids")
        cv = self.cvs.get(cv_id)
        if not self.cvs.approved(cv_id):
            raise PermissionError("approved CV required")
        job = self.repo.get_job(job_id)
        if job is None:
            raise ValueError("job not found")
        if cv.job_id and cv.job_id != job_id:
            raise ValueError("CV targets a different job")
        by_id = {c.evidence_id: c for c in cv.claims}
        answers = answers or {}
        if any(k not in {str(i) for i in range(len(questions))} for k in answers):
            raise ValueError("unknown question index")
        items = []
        for i, question in enumerate(questions):
            evidence_id = answers.get(str(i))
            if evidence_id is not None and evidence_id not in by_id:
                raise ValueError("answer must cite approved CV evidence")
            items.append(FormAnswer(question=question, evidence_id=evidence_id,
                                    text=by_id[evidence_id].text if evidence_id else None))
        greeting, intro, closing = (
            ("Kính gửi bộ phận tuyển dụng,", "Tôi gửi thông tin kinh nghiệm để quý công ty xem xét:",
             "Trân trọng,") if cv.language == "vi" else
            ("Dear hiring team,", "Please consider the following experience for my application:",
             "Kind regards,")
        )
        body = "\n\n".join([greeting, intro, *[c.text for c in cv.claims], closing,
                              cv.identity.get("name", "")]).rstrip()
        draft = ApplicationDraft(id=uuid4().hex, cv_id=cv.id, cv_hash=digest(cv),
                                 profile_version=cv.profile_version, profile_hash=cv.profile_hash,
                                 job_id=job_id, job_hash=digest(job), language=cv.language,
                                 subject=subject, route=route, body=body, answers=items)
        with self.repo.connect() as db:
            db.execute("INSERT INTO application_drafts VALUES (?, ?, ?)",
                       (draft.id, draft.model_dump_json(), digest(draft)))
        return draft

    def get(self, draft_id):
        with self.repo.connect() as db:
            row = db.execute("SELECT payload, hash FROM application_drafts WHERE id=?",
                             (draft_id,)).fetchone()
        if row is None:
            raise ValueError("application draft not found")
        draft = ApplicationDraft.model_validate_json(row["payload"])
        if draft.id != draft_id or digest(draft) != row["hash"]:
            raise ValueError("application draft hash mismatch")
        cv = self.cvs.get(draft.cv_id)
        job = self.repo.get_job(draft.job_id)
        if digest(cv) != draft.cv_hash or job is None or digest(job) != draft.job_hash:
            raise ValueError("stale application draft")
        if not self.cvs.approved(cv.id):
            raise PermissionError("CV approval no longer valid")
        return draft

    def approve(self, draft_id, content_hash):
        draft = self.get(draft_id)
        if digest(draft) != content_hash:
            raise ValueError("approval hash mismatch")
        with self.repo.connect() as db:
            db.execute("INSERT OR REPLACE INTO application_draft_approvals VALUES (?, ?)",
                       (draft_id, content_hash))

    def export(self, draft_id, target):
        draft = self.get(draft_id)
        with self.repo.connect() as db:
            row = db.execute("SELECT hash FROM application_draft_approvals WHERE id=?",
                             (draft_id,)).fetchone()
        if row is None or row["hash"] != digest(draft):
            raise PermissionError("review and approve application draft before export")
        form = "\n\n".join(f"{a.question}\n{a.text if a.text is not None else '[UNANSWERED]'}"
                             for a in draft.answers)
        publish_bundle(Path(target), {
            "application.json": draft.model_dump_json(indent=2).encode(),
            "email.txt": f"{draft.subject}\n\n{draft.body}\n".encode(),
            "form.txt": (form + "\n").encode(),
            "README.txt": f"Route: {draft.route}\n{draft.warning}\n".encode(),
        })

"""Local, immutable CV revisions. Citations validate quotes, not rewritten semantics."""
import hashlib
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .storage.repository import CareerRepository


def digest(value: BaseModel) -> str:
    return hashlib.sha256(json.dumps(value.model_dump(mode="json"), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    source_quote: str = Field(min_length=1, max_length=12000)
    text: str = Field(min_length=1, max_length=12000)
    section: Literal["experience", "education", "skills", "credentials", "other"] = "other"
    mode: Literal["extractive", "proposed"] = "extractive"
    uncertainty: str
    status: str


class CV(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    profile_version: str
    profile_hash: str
    job_id: str | None = None
    job_hash: str | None = None
    language: Literal["en", "vi"]
    identity: dict[str, str] = Field(default_factory=dict)
    claims: list[Claim] = Field(min_length=1, max_length=100)
    provenance: str = "local-extractive"
    warning: str = "Original evidence language retained; translations/rewrites need human review."


class CVService:
    def __init__(self, repository: CareerRepository):
        self.repo = repository
        repository.initialize()
        with repository.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cv_revisions "
                       "(id TEXT PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS cv_approvals "
                       "(id TEXT PRIMARY KEY REFERENCES cv_revisions(id), hash TEXT NOT NULL)")

    content_hash = staticmethod(digest)

    def _profile(self, version):
        profile = self.repo.get_profile_version(version)
        if profile is not None:
            with self.repo.connect() as db:
                row = db.execute("SELECT content_hash FROM profiles WHERE version=?",
                                 (version,)).fetchone()
            actual = hashlib.sha256(profile.model_dump_json().encode()).hexdigest()
            if row is None or row["content_hash"] != actual:
                raise ValueError("stale canonical profile: stored integrity hash mismatch")
        return profile

    def create(self, version, evidence_ids, *, language, job_id=None, identity_keys=()):
        profile = self._profile(version)
        if profile is None or profile.confirmed_at is None:
            raise ValueError("confirmed profile required")
        evidence = {e.evidence_id: e for e in profile.evidence}
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("select unique evidence ids")
        if any(i not in evidence for i in evidence_ids):
            raise ValueError("unknown evidence id")
        if any(k not in profile.identity for k in identity_keys):
            raise ValueError("unknown identity key")
        job = self.repo.get_job(job_id) if job_id else None
        if job_id and job is None:
            raise ValueError("job not found")
        claims = []
        for key in evidence_ids:
            e = evidence[key]
            if e.provenance == "identity" or key.startswith("ev_identity"):
                raise ValueError("identity evidence must not be used as a CV claim")
            quote = e.source_quote or e.summary
            section = e.provenance if e.provenance in {
                "experience", "education", "skills", "credentials"} else "other"
            claims.append(Claim(evidence_id=key, source_quote=quote, text=quote,
                                section=section, uncertainty=e.uncertainty, status=e.status.value))
        cv = CV(id=uuid4().hex, profile_version=version, profile_hash=digest(profile),
                job_id=job_id, job_hash=digest(job) if job else None,
                language=language, claims=claims,
                identity={k: profile.identity[k] for k in identity_keys})
        self._save(cv)
        return cv

    def validate(self, cv):
        profile = self._profile(cv.profile_version)
        if profile is None or profile.confirmed_at is None or digest(profile) != cv.profile_hash:
            raise ValueError("stale canonical profile")
        job = self.repo.get_job(cv.job_id) if cv.job_id else None
        if (digest(job) if job else None) != cv.job_hash or (cv.job_id and job is None):
            raise ValueError("stale canonical job")
        evidence = {e.evidence_id: e for e in profile.evidence}
        ids = [c.evidence_id for c in cv.claims]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate evidence ids")
        for c in cv.claims:
            e = evidence.get(c.evidence_id)
            if e is None or e.provenance == "identity" or c.evidence_id.startswith("ev_identity"):
                raise ValueError("unknown or private evidence")
            if c.source_quote != (e.source_quote or e.summary):
                raise ValueError("noncanonical quote")
            if c.uncertainty != e.uncertainty or c.status != e.status.value:
                raise ValueError("noncanonical evidence status")
            if c.mode == "extractive" and c.text != c.source_quote:
                raise ValueError("extractive text must equal canonical quote")
        if any(profile.identity.get(k) != v for k, v in cv.identity.items()):
            raise ValueError("noncanonical identity")

    def _save(self, cv):
        self.validate(cv)
        with self.repo.connect() as db:
            db.execute("INSERT INTO cv_revisions VALUES (?, ?, ?)",
                       (cv.id, cv.model_dump_json(), digest(cv)))

    def get(self, cv_id):
        with self.repo.connect() as db:
            row = db.execute("SELECT payload, hash FROM cv_revisions WHERE id=?", (cv_id,)).fetchone()
        if row is None:
            raise ValueError("CV not found")
        cv = CV.model_validate_json(row["payload"])
        if cv.id != cv_id or digest(cv) != row["hash"]:
            raise ValueError("CV content hash mismatch")
        self.validate(cv)
        return cv

    def revise(self, cv_id, claims, *, provenance):
        old = self.get(cv_id)
        payload = old.model_dump()
        payload.update(id=uuid4().hex, claims=claims, provenance=provenance)
        cv = CV.model_validate(payload)
        self._save(cv)
        return cv

    def approve(self, cv_id, content_hash):
        cv = self.get(cv_id)
        if digest(cv) != content_hash:
            raise ValueError("approval hash does not match reviewed content")
        with self.repo.connect() as db:
            db.execute("INSERT OR REPLACE INTO cv_approvals VALUES (?, ?)", (cv_id, content_hash))

    def approved(self, cv_id):
        cv = self.get(cv_id)
        with self.repo.connect() as db:
            row = db.execute("SELECT hash FROM cv_approvals WHERE id=?", (cv_id,)).fetchone()
        return row is not None and row["hash"] == digest(cv)

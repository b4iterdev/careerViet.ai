from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class EvidenceStatus(str, Enum):
    CANDIDATE_CONFIRMED = "candidate_confirmed"
    DOCUMENT_VERIFIED = "document_verified"
    PUBLIC_VERIFIED = "public_verified"
    UNKNOWN = "unknown"


class CandidateEvidence(BaseModel):
    evidence_id: str = Field(min_length=1)
    status: EvidenceStatus
    summary: str = Field(min_length=1)
    source: str = Field(min_length=1)
    observed_on: date | None = None


class FactRequirement(BaseModel):
    fact_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def require_grounding(cls, value: list[str]) -> list[str]:
        if not value or any(not evidence_id.strip() for evidence_id in value):
            raise ValueError("required facts must cite at least one evidence id")
        return value


class WorkPreferences(BaseModel):
    wants_internship: bool | None = None
    wants_full_time: bool | None = None
    preferred_locations: list[str] = Field(default_factory=list)
    remote_from_vietnam: bool | None = None
    weekly_availability_hours: int | None = Field(default=None, ge=0, le=168)


class CandidateProfile(BaseModel):
    profile_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    required_facts: list[FactRequirement] = Field(default_factory=list)
    preferences: WorkPreferences = Field(default_factory=WorkPreferences)

    @model_validator(mode="after")
    def required_facts_must_reference_existing_evidence(self) -> "CandidateProfile":
        evidence_ids = {item.evidence_id for item in self.evidence}
        missing = [
            evidence_id
            for fact in self.required_facts
            for evidence_id in fact.evidence_ids
            if evidence_id not in evidence_ids
        ]
        if missing:
            raise ValueError(f"required facts reference missing evidence ids: {', '.join(missing)}")
        return self

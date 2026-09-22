from datetime import date, datetime
from enum import Enum
from typing import Literal

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
    source_quote: str | None = Field(default=None, min_length=1)
    provenance: str | None = Field(default=None, min_length=1)
    uncertainty: Literal["low", "medium", "high", "unknown"] = "unknown"
    observed_on: date | None = None


class RankedTarget(BaseModel):
    rank: int = Field(ge=1)
    occupation_family: str = Field(min_length=1)
    title: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ProfileExperience(BaseModel):
    title: str = Field(min_length=1)
    start: str | None = None
    end: str | None = None
    engagement_type: Literal["full_time", "internship", "part_time", "contract", "volunteer", "unknown"] = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)


class ProfileCredential(BaseModel):
    label: str = Field(min_length=1)
    expires_on: date | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class CompensationFloor(BaseModel):
    amount: int | None = Field(default=None, ge=0)
    currency: str | None = None
    period: str | None = None
    gross_net: Literal["gross", "net", "unknown"] = "unknown"

    @model_validator(mode="after")
    def require_units_when_amount_known(self) -> "CompensationFloor":
        if self.amount is None:
            return self
        if not self.currency or not self.period:
            raise ValueError("known compensation floors require currency and period")
        return self


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
    shifts: list[str] = Field(default_factory=list)
    travel: str | None = None
    industry_exclusions: list[str] = Field(default_factory=list)
    internship_compensation_floor: CompensationFloor | None = None
    full_time_compensation_floor: CompensationFloor | None = None
    availability_current: str | None = None
    availability_future: str | None = None


class CandidateProfile(BaseModel):
    profile_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    confirmed_at: datetime | None = None
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    required_facts: list[FactRequirement] = Field(default_factory=list)
    preferences: WorkPreferences = Field(default_factory=WorkPreferences)
    identity: dict[str, str] = Field(default_factory=dict)
    ranked_targets: list[RankedTarget] = Field(default_factory=list)
    experience: list[ProfileExperience] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    licenses_credentials: list[ProfileCredential] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_facts_must_reference_existing_evidence(self) -> "CandidateProfile":
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("duplicate evidence ids are not allowed")
        missing = [
            evidence_id
            for fact in self.required_facts
            for evidence_id in fact.evidence_ids
            if evidence_id not in evidence_ids
        ]
        if missing:
            raise ValueError(f"required facts reference missing evidence ids: {', '.join(missing)}")
        return self

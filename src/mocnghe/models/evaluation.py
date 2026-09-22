from pydantic import BaseModel, Field, model_validator


class RequirementMatch(BaseModel):
    requirement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    status: str = Field(min_length=1)


class Evaluation(BaseModel):
    evaluation_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    requirement_matches: list[RequirementMatch] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommendation: str = Field(min_length=1)
    confidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def supported_matches_need_evidence(self) -> "Evaluation":
        ungrounded = [
            match.requirement
            for match in self.requirement_matches
            if match.status == "supported" and not match.evidence_ids
        ]
        if ungrounded:
            raise ValueError("supported requirement matches must cite evidence")
        return self

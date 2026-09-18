from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ApplicationState(str, Enum):
    DISCOVERED = "discovered"
    SHORTLISTED = "shortlisted"
    DRAFTING = "drafting"
    READY = "ready"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ARCHIVED = "archived"


class Application(BaseModel):
    job_id: str = Field(min_length=1)
    state: ApplicationState = ApplicationState.DISCOVERED
    cv_version: str | None = None
    jd_content_hash: str | None = None
    applied_at: datetime | None = None

    @model_validator(mode="after")
    def applied_state_requires_timestamp(self) -> "Application":
        if self.state is ApplicationState.APPLIED and self.applied_at is None:
            raise ValueError("applied applications require applied_at")
        if self.state is not ApplicationState.APPLIED and self.applied_at is not None:
            raise ValueError("applied_at is only valid for applied applications")
        return self

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models.job import Job


class IngestionState(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    POLICY_UNVERIFIED = "policy_unverified"
    UNSUPPORTED = "unsupported"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    SCHEMA_CHANGED = "schema_changed"
    PARSE_FAILED = "parse_failed"


class PolicyEvidence(BaseModel):
    url: str
    final_url: str
    status_code: int | None = None
    content_type: str = ""
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: int = 0
    bytes_received: int = 0
    state: str = "observed"
    content_sha256: str | None = None
    excerpt: str = ""


class SourceStats(BaseModel):
    source_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requests: int = 0
    status_codes: list[int] = Field(default_factory=list)
    latency_ms: int = 0
    bytes_received: int = 0
    parsed_unique_count: int = 0
    rejected_count: int = 0
    missing_required_fields: int = 0
    duplicates: int = 0
    cache_hits: int = 0
    filtered_count: int = 0
    filters: list[str] = Field(default_factory=list)
    source_limits: dict[str, int | str] = Field(default_factory=dict)

    def record_http(self, status_code: int | None, latency_ms: int, bytes_received: int) -> None:
        self.requests += 1
        if status_code is not None:
            self.status_codes.append(status_code)
        self.latency_ms += latency_ms
        self.bytes_received += bytes_received

    def record_filter(self, filter_name: str) -> None:
        self.filters.append(filter_name)


class SourceResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    source_id: str
    state: IngestionState
    stats: SourceStats
    jobs: list[Job] = Field(default_factory=list)
    schema_validated: bool = False
    message: str | None = None
    policy_evidence: list[PolicyEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_schema_for_success_states(self) -> SourceResult:
        if self.state in {IngestionState.SUCCESS, IngestionState.EMPTY} and not self.schema_validated:
            raise ValueError("success and empty states require validated schema evidence")
        return self


class ImportSummary(BaseModel):
    source_id: str
    state: IngestionState
    imported: int = 0
    existing: int = 0
    skipped: int = 0

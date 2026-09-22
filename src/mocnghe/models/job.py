from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    INTERNSHIP = "internship"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


class SalaryKind(str, Enum):
    UNKNOWN = "unknown"
    HIDDEN = "hidden"
    NEGOTIABLE = "negotiable"
    ZERO = "zero"
    RANGE = "range"
    FIXED = "fixed"


class Salary(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(use_enum_values=False)

    kind: SalaryKind
    currency: str | None = None
    period: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    gross_net: Literal["gross", "net", "unknown"] = "unknown"

    @field_validator("currency", "period")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("salary currency and period cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_coherent_variant(self) -> "Salary":
        if self.minimum is not None and self.minimum < 0:
            raise ValueError("salary minimum cannot be negative")
        if self.maximum is not None and self.maximum < 0:
            raise ValueError("salary maximum cannot be negative")

        if self.kind in {SalaryKind.UNKNOWN, SalaryKind.HIDDEN, SalaryKind.NEGOTIABLE}:
            if self.currency or self.period or self.minimum is not None or self.maximum is not None:
                raise ValueError(f"{self.kind.value} salary cannot include amount details")
            if self.gross_net != "unknown":
                raise ValueError(f"{self.kind.value} salary cannot specify gross/net")
            return self

        if self.kind is SalaryKind.ZERO:
            if not self.currency or not self.period:
                raise ValueError("zero salary requires currency and period")
            if self.minimum != 0 or self.maximum != 0:
                raise ValueError("zero salary must have minimum and maximum equal to 0")
            return self

        if self.kind is SalaryKind.FIXED:
            if not self.currency or not self.period or self.minimum is None:
                raise ValueError("fixed salary requires currency, period, and minimum")
            if self.minimum == 0:
                raise ValueError("fixed salary with zero amount must use zero kind")
            if self.maximum is not None:
                raise ValueError("fixed salary cannot include maximum")
            return self

        if self.kind is SalaryKind.RANGE:
            if not self.currency or not self.period or self.minimum is None or self.maximum is None:
                raise ValueError("range salary requires currency, period, minimum, and maximum")
            if self.minimum == 0 and self.maximum == 0:
                raise ValueError("range salary with zero amounts must use zero kind")
            if self.minimum > self.maximum:
                raise ValueError("salary minimum cannot exceed maximum")
            return self

        return self


class SourceProvenance(BaseModel):
    source_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    original_uri: str = Field(min_length=1)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    original_url: HttpUrl | None = None


class Job(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(use_enum_values=False)

    source: SourceProvenance
    title: str = Field(min_length=1)
    employer: str = Field(min_length=1)
    location: str = "unknown"
    workplace_policy: str = "unknown"
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    salary: Salary = Field(default_factory=lambda: Salary(kind=SalaryKind.UNKNOWN))
    description: str = Field(min_length=1)
    requirements: str = "unknown"
    benefits: str = ""
    freeform_text: str = ""
    content_hash: str | None = None
    job_id: str | None = None
    applied: bool = False

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("content_hash must be a lowercase sha256 hex digest")
        return value

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("job_"):
            raise ValueError("job_id must start with job_")
        return value


def normalize_job_content(content: str) -> str:
    normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
    return normalized


def hash_job_identity(content: str) -> str:
    return sha256(normalize_job_content(content).encode()).hexdigest()


def job_id_from_hash(content_hash: str) -> str:
    return f"job_{content_hash[:16]}"

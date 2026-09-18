# pyright: reportMissingTypeStubs=false
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from careerviet.models.application import Application, ApplicationState
from careerviet.models.evaluation import Evaluation, RequirementMatch
from careerviet.models.job import EmploymentType, Job, Salary, SalaryKind, SourceProvenance
from careerviet.models.profile import (
    CandidateEvidence,
    CandidateProfile,
    EvidenceStatus,
    FactRequirement,
    WorkPreferences,
)


def test_models_preserve_text_and_unknown_salary() -> None:
    job = Job(
        source=SourceProvenance(
            source_id="manual:fixture",
            source_kind="manual_file",
            original_uri="fixture-jd.txt",
            retrieved_at=datetime(2026, 9, 14, tzinfo=UTC),
        ),
        title="Lập trình viên C++/C#",
        employer="Công ty Ví dụ",
        location="Đà Nẵng",
        employment_type=EmploymentType.FULL_TIME,
        salary=Salary(kind=SalaryKind.UNKNOWN),
        description="Phát triển phần mềm bằng C++ và C# cho khách hàng Việt Nam.",
        requirements="Có kinh nghiệm C++/C#, giao tiếp tiếng Việt tốt.",
    )

    assert job.salary.kind is SalaryKind.UNKNOWN
    assert "Đà Nẵng" in job.location
    assert "C++" in job.description
    assert "C#" in job.requirements
    assert job.applied is False


def test_job_rejects_malformed_url() -> None:
    with pytest.raises(ValidationError):
        _ = SourceProvenance.model_validate(
            {
                "source_id": "manual:bad",
                "source_kind": "manual_file",
                "original_url": "not a url",
                "original_uri": "fixture-jd.txt",
                "retrieved_at": datetime.now(UTC),
            }
        )


def test_profile_rejects_ungrounded_required_fact() -> None:
    evidence = CandidateEvidence(
        evidence_id="ev-1",
        status=EvidenceStatus.CANDIDATE_CONFIRMED,
        summary="Đã làm ca tối tại cửa hàng bán lẻ.",
        source="candidate testimony",
        observed_on=date(2025, 5, 1),
    )

    with pytest.raises(ValidationError):
        _ = CandidateProfile(
            profile_id="profile-1",
            version="2026-09-14",
            evidence=[evidence],
            required_facts=[
                FactRequirement(
                    fact_id="fact-1",
                    label="Có chứng chỉ kế toán trưởng",
                    evidence_ids=["missing-evidence"],
                )
            ],
            preferences=WorkPreferences(wants_internship=True, wants_full_time=False),
        )


def test_preferences_keep_internship_and_full_time_separate() -> None:
    profile = CandidateProfile(
        profile_id="profile-2",
        version="2026-09-14",
        evidence=[],
        required_facts=[],
        preferences=WorkPreferences(wants_internship=True, wants_full_time=False),
    )

    assert profile.preferences.wants_internship is True
    assert profile.preferences.wants_full_time is False


def test_evaluation_and_application_reference_real_entities() -> None:
    evaluation = Evaluation(
        evaluation_id="eval-1",
        job_id="job-1",
        profile_version="2026-09-14",
        requirement_matches=[
            RequirementMatch(
                requirement="C++ experience",
                evidence_ids=["ev-1"],
                status="supported",
            )
        ],
        missing_evidence=["salary expectation"],
        recommendation="review",
        confidence="medium",
    )
    application = Application(job_id="job-1", state=ApplicationState.DISCOVERED)

    assert evaluation.requirement_matches[0].evidence_ids == ["ev-1"]
    assert application.state is ApplicationState.DISCOVERED
    assert application.applied_at is None


def test_profile_model_validate_rejects_missing_blank_and_nonexistent_evidence_ids() -> None:
    base_profile = {
        "profile_id": "profile-regression",
        "version": "2026-09-14",
        "evidence": [
            {
                "evidence_id": "ev-confirmed-1",
                "status": "candidate_confirmed",
                "summary": "Confirmed customer-facing shift work.",
                "source": "candidate testimony",
            }
        ],
        "preferences": {"wants_internship": False, "wants_full_time": True},
    }
    invalid_required_facts = [
        {"fact_id": "fact-missing-field", "label": "Missing evidence_ids must be invalid"},
        {
            "fact_id": "fact-blank-id",
            "label": "Blank evidence IDs must be invalid",
            "evidence_ids": [""],
        },
        {
            "fact_id": "fact-nonexistent-id",
            "label": "Unknown evidence IDs must be invalid",
            "evidence_ids": ["ev-does-not-exist"],
        },
    ]

    for required_fact in invalid_required_facts:
        with pytest.raises(ValidationError):
            _ = CandidateProfile.model_validate(
                {**base_profile, "required_facts": [required_fact]}
            )


def test_salary_rejects_invalid_or_contradictory_variants() -> None:
    invalid_salaries = [
        {"kind": "fixed", "currency": "VND", "period": "month", "minimum": -1},
        {"kind": "range", "currency": "VND", "period": "month", "minimum": 20, "maximum": 10},
        {"kind": "range", "currency": "VND", "period": "month", "minimum": 10},
        {"kind": "fixed", "currency": "VND", "period": "month", "minimum": 10, "maximum": 20},
        {"kind": "negotiable", "currency": "VND", "period": "month", "minimum": 10},
        {"kind": "unknown", "currency": "VND"},
        {"kind": "zero", "currency": "VND", "period": "month", "minimum": 1},
    ]

    for salary_data in invalid_salaries:
        with pytest.raises(ValidationError):
            _ = Salary.model_validate(salary_data)

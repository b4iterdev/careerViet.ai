# pyright: reportMissingTypeStubs=false
from datetime import UTC, datetime

from mocnghe.models.job import EmploymentType, Job, Salary, SalaryKind, SourceProvenance
from mocnghe.models.profile import (
    CandidateEvidence,
    CandidateProfile,
    CompensationFloor,
    EvidenceStatus,
    ProfileCredential,
    RankedTarget,
    WorkPreferences,
)
from mocnghe.triage import triage_job


def test_triage_separates_hard_violations_unknowns_and_conditionals() -> None:
    profile = CandidateProfile(
        profile_id="profile_retail",
        version="v20260919T010000Z-retail",
        evidence=[
            CandidateEvidence(
                evidence_id="ev_target",
                status=EvidenceStatus.CANDIDATE_CONFIRMED,
                summary="Targets retail cashier roles.",
                source="synthetic_fixture",
                source_quote="Targets retail cashier roles.",
            ),
            CandidateEvidence(
                evidence_id="ev_forklift",
                status=EvidenceStatus.CANDIDATE_CONFIRMED,
                summary="Forklift safety certificate expires 2027-05-01.",
                source="synthetic_fixture",
                source_quote="Forklift safety certificate expires 2027-05-01.",
            ),
        ],
        ranked_targets=[RankedTarget(rank=1, occupation_family="retail", title="cashier", evidence_ids=["ev_target"])],
        licenses_credentials=[ProfileCredential(label="Forklift safety certificate", evidence_ids=["ev_forklift"])],
        preferences=WorkPreferences(
            wants_full_time=True,
            wants_internship=False,
            preferred_locations=["Ha Noi"],
            full_time_compensation_floor=CompensationFloor(amount=9_000_000, currency="VND", period="month", gross_net="gross"),
        ),
    )
    job = Job(
        job_id="job_retail_low_salary",
        content_hash="a" * 64,
        source=SourceProvenance(
            source_id="manual:triage",
            source_kind="manual_text",
            original_uri="synthetic",
            retrieved_at=datetime(2026, 9, 19, tzinfo=UTC),
        ),
        title="Retail Cashier",
        employer="Synthetic Shop",
        location="Ha Noi",
        employment_type=EmploymentType.FULL_TIME,
        salary=Salary(kind=SalaryKind.RANGE, currency="VND", period="month", minimum=7_000_000, maximum=8_000_000, gross_net="gross"),
        description="Serve shoppers.",
        requirements="Must have forklift safety certificate. Good customer service.",
    )

    result = triage_job(profile, job)

    assert result.verdict == "do_not_evaluate_until_constraints_reviewed"
    assert [violation.constraint for violation in result.known_violations] == ["full_time_compensation_floor"]
    assert result.known_violations[0].evidence == "job maximum 8000000 VND/month gross below profile floor 9000000 VND/month gross"
    assert result.unknowns == []
    assert result.satisfied_constraints == ["employment_type", "location", "mandatory_credentials"]


def test_triage_treats_missing_salary_as_unknown_not_rejection() -> None:
    profile = CandidateProfile(
        profile_id="profile_intern",
        version="v20260919T010100Z-intern",
        preferences=WorkPreferences(
            wants_internship=True,
            internship_compensation_floor=CompensationFloor(amount=2_000_000, currency="VND", period="month", gross_net="gross"),
        ),
    )
    job = Job(
        job_id="job_unknown_salary",
        content_hash="b" * 64,
        source=SourceProvenance(source_id="manual:triage", source_kind="manual_text", original_uri="synthetic"),
        title="Marketing Intern",
        employer="Synthetic Agency",
        location="unknown",
        employment_type=EmploymentType.INTERNSHIP,
        salary=Salary(kind=SalaryKind.UNKNOWN),
        description="Assist campaigns.",
        requirements="No mandatory credential stated.",
    )

    result = triage_job(profile, job)

    assert result.known_violations == []
    assert [unknown.constraint for unknown in result.unknowns] == ["salary"]
    assert result.verdict == "evaluate_with_unknowns"

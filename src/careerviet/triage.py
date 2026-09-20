from typing import Literal

from pydantic import BaseModel, Field

from .models.job import EmploymentType, Job, SalaryKind
from .models.profile import CandidateProfile, CompensationFloor


class ConstraintFinding(BaseModel):
    constraint: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class TriageResult(BaseModel):
    verdict: Literal["evaluate", "evaluate_with_unknowns", "do_not_evaluate_until_constraints_reviewed"]
    known_violations: list[ConstraintFinding] = Field(default_factory=list)
    unknowns: list[ConstraintFinding] = Field(default_factory=list)
    conditional: list[ConstraintFinding] = Field(default_factory=list)
    satisfied_constraints: list[str] = Field(default_factory=list)


def triage_job(profile: CandidateProfile, job: Job) -> TriageResult:
    known_violations: list[ConstraintFinding] = []
    unknowns: list[ConstraintFinding] = []
    conditional: list[ConstraintFinding] = []
    satisfied: list[str] = []

    _check_engagement(profile, job, known_violations, unknowns, satisfied)
    _check_location(profile, job, unknowns, satisfied)
    _check_salary(profile, job, known_violations, unknowns)
    _check_mandatory_credentials(profile, job, known_violations, satisfied)

    if known_violations:
        verdict = "do_not_evaluate_until_constraints_reviewed"
    elif unknowns or conditional:
        verdict = "evaluate_with_unknowns"
    else:
        verdict = "evaluate"
    return TriageResult(
        verdict=verdict,
        known_violations=known_violations,
        unknowns=unknowns,
        conditional=conditional,
        satisfied_constraints=satisfied,
    )


def _check_engagement(
    profile: CandidateProfile,
    job: Job,
    known_violations: list[ConstraintFinding],
    unknowns: list[ConstraintFinding],
    satisfied: list[str],
) -> None:
    if job.employment_type is EmploymentType.UNKNOWN:
        unknowns.append(ConstraintFinding(constraint="employment_type", evidence="job employment type unknown"))
        return
    if job.employment_type is EmploymentType.INTERNSHIP and profile.preferences.wants_internship is False:
        known_violations.append(ConstraintFinding(constraint="employment_type", evidence="profile does not want internship roles"))
        return
    if job.employment_type is EmploymentType.FULL_TIME and profile.preferences.wants_full_time is False:
        known_violations.append(ConstraintFinding(constraint="employment_type", evidence="profile does not want full-time roles"))
        return
    satisfied.append("employment_type")


def _check_location(
    profile: CandidateProfile,
    job: Job,
    unknowns: list[ConstraintFinding],
    satisfied: list[str],
) -> None:
    if not profile.preferences.preferred_locations:
        return
    if job.location == "unknown":
        unknowns.append(ConstraintFinding(constraint="location", evidence="job location unknown"))
        return
    if any(location.lower() in job.location.lower() for location in profile.preferences.preferred_locations):
        satisfied.append("location")


def _check_salary(
    profile: CandidateProfile,
    job: Job,
    known_violations: list[ConstraintFinding],
    unknowns: list[ConstraintFinding],
) -> None:
    floor = _relevant_floor(profile, job.employment_type)
    if floor is None or floor.amount is None:
        return
    if job.salary.kind in {SalaryKind.UNKNOWN, SalaryKind.HIDDEN, SalaryKind.NEGOTIABLE}:
        unknowns.append(ConstraintFinding(constraint="salary", evidence=f"job salary is {job.salary.kind.value}"))
        return
    if job.salary.currency != floor.currency or job.salary.period != floor.period:
        unknowns.append(ConstraintFinding(constraint="salary_units", evidence="job salary units do not match profile floor units"))
        return
    conservative_maximum = job.salary.maximum if job.salary.maximum is not None else job.salary.minimum
    if conservative_maximum is None:
        unknowns.append(ConstraintFinding(constraint="salary", evidence="job salary amount missing"))
        return
    if conservative_maximum < floor.amount:
        known_violations.append(
            ConstraintFinding(
                constraint=_floor_name(job.employment_type),
                evidence=(
                    f"job maximum {conservative_maximum} {job.salary.currency}/{job.salary.period} "
                    f"{job.salary.gross_net} below profile floor {floor.amount} "
                    f"{floor.currency}/{floor.period} {floor.gross_net}"
                ),
            )
        )


def _check_mandatory_credentials(
    profile: CandidateProfile,
    job: Job,
    known_violations: list[ConstraintFinding],
    satisfied: list[str],
) -> None:
    requirements = job.requirements.lower()
    mandatory_credentials = []
    if "must have" in requirements and "forklift" in requirements:
        mandatory_credentials.append("forklift")
    if "registered nurse" in requirements or "nursing license" in requirements:
        mandatory_credentials.append("nursing")
    if not mandatory_credentials:
        return
    credential_labels = "\n".join(credential.label.lower() for credential in profile.licenses_credentials)
    missing = [credential for credential in mandatory_credentials if credential not in credential_labels]
    if missing:
        known_violations.append(
            ConstraintFinding(
                constraint="mandatory_credentials",
                evidence=f"profile lacks mandatory credential(s): {', '.join(missing)}",
            )
        )
        return
    satisfied.append("mandatory_credentials")


def _relevant_floor(profile: CandidateProfile, employment_type: EmploymentType) -> CompensationFloor | None:
    if employment_type is EmploymentType.INTERNSHIP:
        return profile.preferences.internship_compensation_floor
    if employment_type is EmploymentType.FULL_TIME:
        return profile.preferences.full_time_compensation_floor
    return None


def _floor_name(employment_type: EmploymentType) -> str:
    if employment_type is EmploymentType.INTERNSHIP:
        return "internship_compensation_floor"
    return "full_time_compensation_floor"

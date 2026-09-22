# pyright: reportMissingTypeStubs=false
import hashlib
from pathlib import Path

from mocnghe.models.job import EmploymentType, Job, Salary, SalaryKind, SourceProvenance
from mocnghe.onboarding import OnboardingAnswer, ProfileOnboarding
from mocnghe.storage.repository import CareerRepository
from mocnghe.triage import triage_job


def test_three_synthetic_occupations_onboarding_and_triage(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()

    # 1. Healthcare / Clinic Assistant
    healthcare_session = ProfileOnboarding.start(repository, draft_id="draft-healthcare")
    healthcare_answers = [
        "Synthetic candidate Huong, based in Da Nang, contact private.",
        "Targets: clinic assistant first, patient care coordinator second.",
        "Experience: dental assistant 2022-01 to 2024-01 full-time; volunteer first aid instructor.",
        "Education: associate degree in nursing.",
        "License: basic life support certification expires 2026-12-31.",
        "Skills: patient intake, medical record management; Languages: Vietnamese native.",
        "Preferences: Da Nang, remote no, shifts rotating day, no travel, exclude sales.",
        "Compensation: full-time floor 8500000 VND/month gross; internship floor unknown.",
        "Availability: immediate for full-time; internship unavailable.",
    ]
    for ans in healthcare_answers:
        healthcare_session.answer(OnboardingAnswer(text=ans, answered_by="synthetic_fixture"))
    healthcare_profile = healthcare_session.confirm(confirmed_by="synthetic_fixture")
    assert healthcare_profile.profile_id.startswith("profile_")

    clinic_job = Job(
        job_id="job_clinic_danang",
        content_hash=hashlib.sha256(b"clinic").hexdigest(),
        source=SourceProvenance(source_id="manual:clinic", source_kind="manual_text", original_uri="synthetic"),
        title="Clinic Assistant",
        employer="Da Nang Medical Center",
        location="Da Nang",
        employment_type=EmploymentType.FULL_TIME,
        salary=Salary(kind=SalaryKind.RANGE, currency="VND", period="month", minimum=9_000_000, maximum=11_000_000, gross_net="gross"),
        description="Support patient intake and records.",
        requirements="Basic Life Support certification required. Good communication.",
    )
    triage_clinic = triage_job(healthcare_profile, clinic_job)
    assert triage_clinic.verdict == "evaluate"
    assert triage_clinic.known_violations == []

    # 2. Trades / Manufacturing (CNC Operator)
    trades_session = ProfileOnboarding.start(repository, draft_id="draft-trades")
    trades_answers = [
        "Synthetic candidate Duc, based in Binh Duong, contact private.",
        "Targets: CNC machine operator first, mechanical technician second.",
        "Experience: apprentice machinist 2020-06 to 2023-12 full-time.",
        "Education: vocational college technical diploma.",
        "License: industrial safety level 2 certification expires 2028-01-01.",
        "Skills: CNC lathe operation, technical drawing reading; Languages: Vietnamese native.",
        "Preferences: Binh Duong or Ho Chi Minh, remote no, shifts night acceptable, exclude chemical plants.",
        "Compensation: full-time floor 11000000 VND/month gross; internship floor unknown.",
        "Availability: 2 weeks notice for full-time; internship unavailable.",
    ]
    for ans in trades_answers:
        trades_session.answer(OnboardingAnswer(text=ans, answered_by="synthetic_fixture"))
    trades_profile = trades_session.confirm(confirmed_by="synthetic_fixture")
    assert trades_profile.profile_id.startswith("profile_")

    cnc_job = Job(
        job_id="job_cnc_binhduong",
        content_hash=hashlib.sha256(b"cnc").hexdigest(),
        source=SourceProvenance(source_id="manual:cnc", source_kind="manual_text", original_uri="synthetic"),
        title="CNC Machine Operator",
        employer="Precision Engineering VN",
        location="Binh Duong",
        employment_type=EmploymentType.FULL_TIME,
        salary=Salary(kind=SalaryKind.RANGE, currency="VND", period="month", minimum=12_000_000, maximum=15_000_000, gross_net="gross"),
        description="Operate CNC milling and lathe machines.",
        requirements="Industrial safety certification. Technical drawing literacy.",
    )
    triage_cnc = triage_job(trades_profile, cnc_job)
    assert triage_cnc.verdict == "evaluate"
    assert triage_cnc.known_violations == []

    # 3. Tech / Software Developer
    tech_session = ProfileOnboarding.start(repository, draft_id="draft-tech")
    tech_answers = [
        "Synthetic candidate Thai, based in Ha Noi, contact private.",
        "Targets: software engineer first, backend developer second.",
        "Experience: student developer 2023-01 to 2024-06 part-time; open source contributor.",
        "Education: university computer science undergraduate.",
        "License: AWS Certified Cloud Practitioner expires 2027-08-01.",
        "Skills: Python, C++, FastAPI, Docker; Languages: Vietnamese native, English professional.",
        "Preferences: Ha Noi or remote, remote yes, shifts flexible, no travel.",
        "Compensation: full-time floor 15000000 VND/month gross; internship floor 5000000 VND/month gross.",
        "Availability: immediate for full-time or internship.",
    ]
    for ans in tech_answers:
        tech_session.answer(OnboardingAnswer(text=ans, answered_by="synthetic_fixture"))
    tech_profile = tech_session.confirm(confirmed_by="synthetic_fixture")
    assert tech_profile.profile_id.startswith("profile_")

    tech_job = Job(
        job_id="job_python_dev",
        content_hash=hashlib.sha256(b"tech").hexdigest(),
        source=SourceProvenance(source_id="manual:tech", source_kind="manual_text", original_uri="synthetic"),
        title="Junior Python Developer",
        employer="Tech Solutions VN",
        location="Ha Noi",
        employment_type=EmploymentType.FULL_TIME,
        salary=Salary(kind=SalaryKind.RANGE, currency="VND", period="month", minimum=16_000_000, maximum=20_000_000, gross_net="gross"),
        description="Develop REST APIs using FastAPI and Python.",
        requirements="Python programming, Docker knowledge, Git.",
    )
    triage_tech = triage_job(tech_profile, tech_job)
    assert triage_clinic.verdict == "evaluate"
    assert triage_tech.verdict == "evaluate"
    assert triage_tech.known_violations == []

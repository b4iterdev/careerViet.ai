"""Tests for structured requirement extraction from freeform JD text."""

from datetime import UTC, datetime

from mocnghe.evaluation_runtime import _requirements_from_job
from mocnghe.models.job import Job, SourceProvenance

_SOURCE = SourceProvenance(
    source_id="manual:test",
    source_kind="manual_text",
    original_uri="synthetic",
    retrieved_at=datetime(2026, 9, 22, tzinfo=UTC),
)


def _job(requirements: str = "unknown", freeform_text: str = "") -> Job:
    return Job(
        title="Test Job",
        employer="ACME",
        description="A test job description.",
        source=_SOURCE,
        requirements=requirements,
        freeform_text=freeform_text,
    )


# ── explicit requirements field ───────────────────────────────────────────────

def test_explicit_requirements_field_used_when_present():
    job = _job(requirements="Python scripting\nSQL knowledge")
    reqs = _requirements_from_job(job)
    assert [r.requirement_id for r in reqs] == ["req_001", "req_002"]
    assert "Python scripting" in reqs[0].text
    assert "SQL knowledge" in reqs[1].text


# ── freeform fallback ─────────────────────────────────────────────────────────

GREENHOUSE_JD = """
Our mission
Constructor's mission is to enable ...

Required Qualifications:
- Current Computer Science / Software Engineering student
- Experience with at least one programming language (C#, Java, Python, JavaScript, C++, or similar)
- Basic understanding of object-oriented programming concepts
- Interest in backend development and distributed systems

Good to Have (but not required):
- Basic knowledge of C# and .NET
- Familiarity with RESTful APIs
- Experience using Git or other version control systems
"""


def test_freeform_extracts_required_bullets():
    job = _job(freeform_text=GREENHOUSE_JD)
    reqs = _requirements_from_job(job)
    texts = [r.text for r in reqs]
    assert any("Computer Science" in t for t in texts)
    assert any("programming language" in t for t in texts)
    assert any("object-oriented" in t for t in texts)
    assert any("backend development" in t for t in texts)


def test_freeform_required_status_required():
    job = _job(freeform_text=GREENHOUSE_JD)
    reqs = _requirements_from_job(job)
    required = [r for r in reqs if r.required_status == "required"]
    assert len(required) >= 3


def test_freeform_preferred_status_nice_to_have():
    job = _job(freeform_text=GREENHOUSE_JD)
    reqs = _requirements_from_job(job)
    preferred = [r for r in reqs if r.required_status == "preferred"]
    assert any("RESTful" in r.text for r in preferred)
    assert any("Git" in r.text for r in preferred)


def test_freeform_requirement_ids_sequential():
    job = _job(freeform_text=GREENHOUSE_JD)
    reqs = _requirements_from_job(job)
    assert len(reqs) >= 4
    for i, r in enumerate(reqs, start=1):
        assert r.requirement_id == f"req_{i:03d}"


def test_freeform_empty_falls_back_to_single_unknown():
    job = _job(freeform_text="")
    reqs = _requirements_from_job(job)
    assert len(reqs) == 1
    assert reqs[0].required_status == "unknown"


def test_freeform_no_heading_no_extraction():
    """Plain prose without heading → single unknown entry, not spurious bullets."""
    job = _job(freeform_text="We are a great company. We do great things. Join us!")
    reqs = _requirements_from_job(job)
    assert len(reqs) == 1


ITVIEC_STYLE = """
Yêu cầu:
- Sinh viên ngành Công nghệ thông tin
- Có kinh nghiệm với Python hoặc JavaScript
- Hiểu biết về REST API

Phúc lợi:
- Thưởng theo dự án
"""


def test_freeform_vietnamese_required_heading():
    job = _job(freeform_text=ITVIEC_STYLE)
    reqs = _requirements_from_job(job)
    required = [r for r in reqs if r.required_status == "required"]
    assert any("Python" in r.text for r in required)
    assert any("REST API" in r.text for r in required)
    # Benefits section should not be extracted
    assert not any("Thưởng" in r.text for r in reqs)

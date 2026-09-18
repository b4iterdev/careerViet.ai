from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..models.job import (
    EmploymentType,
    Job,
    Salary,
    SalaryKind,
    SourceProvenance,
    hash_job_identity,
    job_id_from_hash,
)

if TYPE_CHECKING:
    from ..storage.repository import CareerRepository


def import_jd_file(repository: CareerRepository, file_path: str | Path) -> Job:
    job, _ = import_jd_file_with_status(repository, file_path)
    return job


def import_jd_file_with_status(repository: CareerRepository, file_path: str | Path) -> tuple[Job, bool]:
    path = Path(file_path).expanduser().resolve()
    content = path.read_text(encoding="utf-8")
    return import_jd_text_with_status(repository, content, source_identity=str(path))


def import_jd_text(
    repository: CareerRepository,
    content: str,
    source_identity: str,
) -> Job:
    job, _ = import_jd_text_with_status(repository, content, source_identity)
    return job


def import_jd_text_with_status(
    repository: CareerRepository,
    content: str,
    source_identity: str,
) -> tuple[Job, bool]:
    if not content.strip():
        raise ValueError("JD content is empty")
    content_hash = hash_job_identity(content)
    fields = _parse_labeled_fields(content)
    job = Job(
        job_id=job_id_from_hash(content_hash),
        content_hash=content_hash,
        source=SourceProvenance(
            source_id=f"manual:{source_identity}",
            source_kind="manual_file" if Path(source_identity).suffix else "manual_text",
            original_uri=source_identity,
            retrieved_at=datetime.now(UTC),
        ),
        title=fields.get("title", "Unknown title"),
        employer=fields.get("employer", "Unknown employer"),
        location=fields.get("location", "unknown"),
        employment_type=_parse_employment_type(fields.get("employment_type", "")),
        salary=_parse_salary(fields.get("salary", "")),
        description=fields.get("description", content.strip()),
        requirements=fields.get("requirements", "unknown"),
        benefits=fields.get("benefits", ""),
        freeform_text=fields.get("freeform_text", ""),
        applied=False,
    )
    return repository.upsert_job(job, source_identity=source_identity, raw_content=content)


def _parse_labeled_fields(content: str) -> dict[str, str]:
    labels = {
        "tiêu đề": "title",
        "tieu de": "title",
        "title": "title",
        "công ty": "employer",
        "cong ty": "employer",
        "company": "employer",
        "địa điểm": "location",
        "dia diem": "location",
        "location": "location",
        "loại hình": "employment_type",
        "loai hinh": "employment_type",
        "employment type": "employment_type",
        "lương": "salary",
        "luong": "salary",
        "salary": "salary",
        "mô tả": "description",
        "mô tả công việc": "description",
        "mo ta": "description",
        "mo ta cong viec": "description",
        "description": "description",
        "job description": "description",
        "yêu cầu": "requirements",
        "yêu cầu công việc": "requirements",
        "yeu cau": "requirements",
        "yeu cau cong viec": "requirements",
        "requirements": "requirements",
        "quyền lợi": "benefits",
        "quyen loi": "benefits",
        "phúc lợi": "benefits",
        "phuc loi": "benefits",
        "benefits": "benefits",
    }
    parsed: dict[str, str] = {}
    current_key: str | None = None

    def append_value(key: str, value: str) -> None:
        if parsed.get(key):
            parsed[key] = f"{parsed[key]}\n{value}".strip()
            return
        parsed[key] = value.strip()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, separator, value = line.partition(":")
        normalized_label = label.strip().lower()
        if separator and normalized_label in labels:
            current_key = labels[normalized_label]
            parsed[current_key] = value.strip()
            continue
        if separator:
            append_value("freeform_text", line)
            current_key = None
            continue
        if current_key is not None:
            append_value(current_key, line)
            continue
        append_value("freeform_text", line)
    return parsed


def _parse_employment_type(value: str) -> EmploymentType:
    lowered = value.lower()
    if "thực tập" in lowered or "intern" in lowered:
        return EmploymentType.INTERNSHIP
    if "toàn thời gian" in lowered or "full" in lowered:
        return EmploymentType.FULL_TIME
    if "bán thời gian" in lowered or "part" in lowered:
        return EmploymentType.PART_TIME
    if "hợp đồng" in lowered or "contract" in lowered:
        return EmploymentType.CONTRACT
    return EmploymentType.UNKNOWN


def _parse_salary(value: str) -> Salary:
    lowered = value.lower().strip()
    if not lowered or lowered in {"unknown", "chưa rõ", "không rõ"}:
        return Salary(kind=SalaryKind.UNKNOWN)
    if "thỏa thuận" in lowered or "thoả thuận" in lowered or "negotiable" in lowered:
        return Salary(kind=SalaryKind.NEGOTIABLE)
    if "ẩn" in lowered or "hidden" in lowered:
        return Salary(kind=SalaryKind.HIDDEN)
    if re.fullmatch(r"0\s*(vnd|vnđ|₫|đồng)(\s*/\s*tháng|\s+tháng|/month|\s+per\s+month)?", lowered):
        return Salary(
            kind=SalaryKind.ZERO,
            currency="VND",
            period="month",
            minimum=0,
            maximum=0,
        )
    return Salary(kind=SalaryKind.UNKNOWN)

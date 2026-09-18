from __future__ import annotations

from ..storage.repository import CareerRepository
from .results import ImportSummary, SourceResult


def import_source_result(repository: CareerRepository, result: SourceResult) -> ImportSummary:
    summary = ImportSummary(source_id=result.source_id, state=result.state)
    for job in result.jobs:
        raw_content = "\n".join(
            [
                f"Tiêu đề: {job.title}",
                f"Công ty: {job.employer}",
                f"Địa điểm: {job.location}",
                "Mô tả:",
                job.description,
                "Yêu cầu:",
                job.requirements,
                "Quyền lợi:",
                job.benefits,
            ]
        )
        source_identity = str(job.source.original_url or job.source.original_uri)
        _, created = repository.upsert_job(
            job,
            source_identity=source_identity,
            raw_content=raw_content,
            dedupe_by_source_identity=True,
        )
        if created:
            summary.imported += 1
        else:
            summary.existing += 1
    return summary

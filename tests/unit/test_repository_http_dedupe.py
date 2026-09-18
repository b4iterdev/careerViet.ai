from datetime import UTC, datetime

from careerviet.ingestion.results import IngestionState, SourceResult, SourceStats
from careerviet.ingestion.service import import_source_result
from careerviet.models.job import (
    EmploymentType,
    Job,
    Salary,
    SalaryKind,
    SourceProvenance,
    hash_job_identity,
    job_id_from_hash,
)
from careerviet.storage.repository import CareerRepository


def _job(title: str, description: str, url: str) -> Job:
    content_hash = hash_job_identity(f"{title}\n{description}")
    return Job(
        job_id=job_id_from_hash(content_hash),
        content_hash=content_hash,
        source=SourceProvenance(
            source_id=f"itviec:{url}",
            source_kind="itviec_http",
            original_uri=url,
            original_url=url,
            retrieved_at=datetime.now(UTC),
        ),
        title=title,
        employer="Example Tech",
        location="Hà Nội",
        employment_type=EmploymentType.FULL_TIME,
        salary=Salary(kind=SalaryKind.UNKNOWN),
        description=description,
        requirements="C++",
    )


def test_http_import_dedupes_by_canonical_source_identity_across_changed_content(tmp_path) -> None:
    repository = CareerRepository(tmp_path / "workspace")
    repository.initialize()
    url = "https://itviec.com/it-jobs/senior-cpp-engineer-123"
    first = _job("Senior C++ Engineer", "Initial content", url)
    changed = _job("Senior C++ Engineer", "Changed content", url)

    first_result = import_source_result(
        repository,
        SourceResult(source_id="itviec", state=IngestionState.SUCCESS, stats=SourceStats(source_id="itviec"), jobs=[first], schema_validated=True),
    )
    second_result = import_source_result(
        repository,
        SourceResult(source_id="itviec", state=IngestionState.SUCCESS, stats=SourceStats(source_id="itviec"), jobs=[changed], schema_validated=True),
    )

    jobs = repository.list_jobs()
    with repository.connect() as connection:
        application_count = connection.execute("select count(*) from applications").fetchone()[0]
        observation_count = connection.execute("select count(*) from job_source_observations").fetchone()[0]

    assert first_result.imported == 1
    assert second_result.existing == 1
    assert len(jobs) == 1
    assert jobs[0].applied is False
    assert application_count == 1
    assert observation_count == 2

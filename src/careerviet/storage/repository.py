import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast

from ..models.job import Job


class CareerRepository:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace: Path = self._safe_workspace(Path(workspace))
        self.database_path: Path = self.workspace / "careerviet.sqlite3"
        self.profile_path: Path = self.workspace / "profile.json"

    def initialize(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            _ = connection.execute(
                """
                create table if not exists jobs (
                    job_id text primary key,
                    content_hash text not null,
                    source_id text not null,
                    source_identity text not null,
                    source_kind text not null,
                    original_uri text not null,
                    original_url text,
                    retrieved_at text not null,
                    title text not null,
                    employer text not null,
                    location text not null,
                    workplace_policy text not null,
                    employment_type text not null,
                    salary_json text not null,
                    description text not null,
                    requirements text not null,
                    applied integer not null check (applied in (0, 1)),
                    raw_content text not null,
                    created_at text not null default current_timestamp,
                    unique (content_hash, source_identity)
                )
                """
            )
            self._ensure_jobs_columns(connection)
            _ = connection.execute(
                """
                create table if not exists applications (
                    application_id integer primary key,
                    job_id text not null references jobs(job_id) on delete cascade,
                    state text not null,
                    cv_version text,
                    jd_content_hash text,
                    applied_at text,
                    created_at text not null default current_timestamp
                )
                """
            )
            _ = connection.execute(
                """
                create table if not exists job_source_observations (
                    observation_id integer primary key,
                    job_id text not null references jobs(job_id) on delete cascade,
                    content_hash text not null,
                    source_id text not null,
                    source_identity text not null,
                    source_kind text not null,
                    original_uri text not null,
                    original_url text,
                    retrieved_at text not null,
                    raw_content text not null,
                    created_at text not null default current_timestamp,
                    unique (job_id, source_identity, retrieved_at, raw_content)
                )
                """
            )
            self._migrate_existing_source_observations(connection)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        _ = connection.execute("pragma foreign_keys = on")
        return connection

    def upsert_job(
        self,
        job: Job,
        source_identity: str,
        raw_content: str,
        *,
        dedupe_by_source_identity: bool = False,
    ) -> tuple[Job, bool]:
        if job.job_id is None or job.content_hash is None:
            raise ValueError("job_id and content_hash are required for persistence")
        with self.connect() as connection:
            if dedupe_by_source_identity:
                existing_by_source = cast(
                    sqlite3.Row | None,
                    connection.execute(
                        "select * from jobs where source_identity = ? order by created_at, job_id limit 1",
                        (source_identity,),
                    ).fetchone(),
                )
                if existing_by_source is not None:
                    existing_job = self._job_from_row(existing_by_source)
                    observed_job = job.model_copy(update={"job_id": existing_job.job_id})
                    self._insert_source_observation(connection, observed_job, source_identity, raw_content)
                    return existing_job, False
            existing = cast(
                sqlite3.Row | None,
                connection.execute(
                    "select * from jobs where content_hash = ? order by created_at, job_id limit 1",
                    (job.content_hash,),
                ).fetchone(),
            )
            if existing is not None:
                existing_job = self._job_from_row(existing)
                observed_job = job.model_copy(
                    update={"job_id": existing_job.job_id, "content_hash": existing_job.content_hash}
                )
                self._insert_source_observation(connection, observed_job, source_identity, raw_content)
                return existing_job, False
            _ = connection.execute(
                """
                insert into jobs (
                    job_id, content_hash, source_id, source_identity, source_kind, original_uri,
                    original_url, retrieved_at, title, employer, location, workplace_policy,
                    employment_type, salary_json, description, requirements, benefits, freeform_text,
                    applied, raw_content
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.content_hash,
                    job.source.source_id,
                    source_identity,
                    job.source.source_kind,
                    job.source.original_uri,
                    str(job.source.original_url) if job.source.original_url else None,
                    job.source.retrieved_at.isoformat(),
                    job.title,
                    job.employer,
                    job.location,
                    job.workplace_policy,
                    job.employment_type.value,
                    job.salary.model_dump_json(),
                    job.description,
                    job.requirements,
                    job.benefits,
                    job.freeform_text,
                    1 if job.applied else 0,
                    raw_content,
                ),
            )
            self._insert_source_observation(connection, job, source_identity, raw_content)
            _ = connection.execute(
                "insert into applications (job_id, state, jd_content_hash) values (?, ?, ?)",
                (job.job_id, "discovered", job.content_hash),
            )
            return job, True

    def list_jobs(self) -> list[Job]:
        with self.connect() as connection:
            rows = cast(
                list[sqlite3.Row],
                connection.execute("select * from jobs order by created_at, job_id").fetchall(),
            )
        return [self._job_from_row(row) for row in rows]

    def get_job(self, job_id: str) -> Job | None:
        with self.connect() as connection:
            row = cast(
                sqlite3.Row | None,
                connection.execute("select * from jobs where job_id = ?", (job_id,)).fetchone(),
            )
        if row is None:
            return None
        return self._job_from_row(row)

    def doctor(self) -> dict[str, str]:
        self.initialize()
        with self.connect() as connection:
            foreign_keys_row = cast(sqlite3.Row, connection.execute("pragma foreign_keys").fetchone())
            job_count_row = cast(sqlite3.Row, connection.execute("select count(*) from jobs").fetchone())
            foreign_keys = cast(int, foreign_keys_row[0])
            job_count = cast(int, job_count_row[0])
        return {
            "database": "ok",
            "foreign_keys": "on" if foreign_keys == 1 else "off",
            "jobs": str(job_count),
        }

    def profile_exists(self) -> bool:
        return self.profile_path.exists()

    def _job_from_row(self, row: sqlite3.Row) -> Job:
        from ..models.job import EmploymentType, Salary, SourceProvenance

        salary_data = cast(object, json.loads(cast(str, row["salary_json"])))
        original_url = cast(str | None, row["original_url"])
        retrieved_at = datetime.fromisoformat(cast(str, row["retrieved_at"]))
        return Job(
            job_id=cast(str, row["job_id"]),
            content_hash=cast(str, row["content_hash"]),
            source=SourceProvenance.model_validate(
                {
                    "source_id": cast(str, row["source_id"]),
                    "source_kind": cast(str, row["source_kind"]),
                    "original_uri": cast(str, row["original_uri"]),
                    "original_url": original_url,
                    "retrieved_at": retrieved_at,
                }
            ),
            title=cast(str, row["title"]),
            employer=cast(str, row["employer"]),
            location=cast(str, row["location"]),
            workplace_policy=cast(str, row["workplace_policy"]),
            employment_type=EmploymentType(cast(str, row["employment_type"])),
            salary=Salary.model_validate(salary_data),
            description=cast(str, row["description"]),
            requirements=cast(str, row["requirements"]),
            benefits=cast(str, row["benefits"]),
            freeform_text=cast(str, row["freeform_text"]),
            applied=bool(cast(int, row["applied"])),
        )

    def _ensure_jobs_columns(self, connection: sqlite3.Connection) -> None:
        rows = cast(list[sqlite3.Row], connection.execute("pragma table_info(jobs)").fetchall())
        columns = {cast(str, row["name"]) for row in rows}
        if "benefits" not in columns:
            _ = connection.execute("alter table jobs add column benefits text not null default ''")
        if "freeform_text" not in columns:
            _ = connection.execute("alter table jobs add column freeform_text text not null default ''")

    def _migrate_existing_source_observations(self, connection: sqlite3.Connection) -> None:
        _ = connection.execute(
            """
            insert or ignore into job_source_observations (
                job_id, content_hash, source_id, source_identity, source_kind, original_uri,
                original_url, retrieved_at, raw_content
            )
            select
                job_id, content_hash, source_id, source_identity, source_kind, original_uri,
                original_url, retrieved_at, raw_content
            from jobs
            """
        )

    def _insert_source_observation(
        self,
        connection: sqlite3.Connection,
        job: Job,
        source_identity: str,
        raw_content: str,
    ) -> None:
        if job.job_id is None or job.content_hash is None:
            raise ValueError("job_id and content_hash are required for source observations")
        _ = connection.execute(
            """
            insert or ignore into job_source_observations (
                job_id, content_hash, source_id, source_identity, source_kind, original_uri,
                original_url, retrieved_at, raw_content
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.content_hash,
                job.source.source_id,
                source_identity,
                job.source.source_kind,
                job.source.original_uri,
                str(job.source.original_url) if job.source.original_url else None,
                job.source.retrieved_at.isoformat(),
                raw_content,
            ),
        )

    def _safe_workspace(self, workspace: Path) -> Path:
        expanded = workspace.expanduser()
        if expanded.exists() and not expanded.is_dir():
            raise ValueError("workspace must be a directory")
        resolved_parent = expanded.parent.resolve()
        return resolved_parent / expanded.name

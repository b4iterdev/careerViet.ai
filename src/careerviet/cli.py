import json
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError

from .ingestion.itviec import fixture_client_for_itviec, search_itviec
from .ingestion.manual import import_jd_file_with_status, import_jd_text_with_status
from .ingestion.results import SourceResult
from .ingestion.service import import_source_result
from .ingestion.vietnamworks import search_vietnamworks
from .models.profile import CandidateProfile
from .storage.repository import CareerRepository

app = typer.Typer(no_args_is_help=True)
jobs_app = typer.Typer(no_args_is_help=True)
profile_app = typer.Typer(no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")
app.add_typer(profile_app, name="profile")


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace directory")] = "data",
) -> None:
    ctx.obj = {"repository": CareerRepository(Path(workspace))}


def repository_from_context(ctx: typer.Context) -> CareerRepository:
    return cast(CareerRepository, cast(dict[str, object], ctx.obj)["repository"])


@app.command()
def init(ctx: typer.Context) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    typer.echo(f"initialized workspace: {repository.workspace}")


@app.command("import-jd")
def import_jd(
    ctx: typer.Context,
    file: Annotated[Path | None, typer.Option("--file", exists=True, dir_okay=False)] = None,
    stdin: Annotated[bool, typer.Option("--stdin", help="Read JD text from standard input")] = False,
) -> None:
    if file is not None and stdin:
        typer.echo("--file and --stdin are mutually exclusive", err=True)
        raise typer.Exit(1)
    if file is None and not stdin:
        typer.echo("provide exactly one JD source: --file or --stdin", err=True)
        raise typer.Exit(1)
    repository = repository_from_context(ctx)
    repository.initialize()
    if stdin:
        content = typer.get_text_stream("stdin").read()
        job, created = import_jd_text_with_status(repository, content, source_identity="stdin")
    else:
        if file is None:
            raise RuntimeError("validated import source missing")
        job, created = import_jd_file_with_status(repository, file)
    status = "imported" if created else "existing"
    typer.echo(f"{status} {job.job_id} {job.title}")


@jobs_app.command("list")
def jobs_list(ctx: typer.Context) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    jobs = repository.list_jobs()
    if not jobs:
        typer.echo("No jobs found")
        return
    for job in jobs:
        typer.echo(f"{job.job_id} {job.title} | {job.employer} | {job.location} | applied={str(job.applied).lower()}")


@jobs_app.command("show")
def jobs_show(ctx: typer.Context, job_id: str) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    job = repository.get_job(job_id)
    if job is None:
        typer.echo(f"Job not found: {job_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"job_id: {job.job_id}")
    typer.echo(f"title: {job.title}")
    typer.echo(f"employer: {job.employer}")
    typer.echo(f"location: {job.location}")
    typer.echo(f"employment_type: {job.employment_type.value}")
    typer.echo(f"salary: {job.salary.kind.value}")
    typer.echo(f"applied: {str(job.applied).lower()}")
    typer.echo(f"source_id: {job.source.source_id}")
    typer.echo("description:")
    typer.echo(job.description)
    typer.echo("requirements:")
    typer.echo(job.requirements)
    if job.benefits:
        typer.echo("benefits:")
        typer.echo(job.benefits)
    if job.freeform_text:
        typer.echo("unparsed_freeform_text:")
        typer.echo(job.freeform_text)


@jobs_app.command("search")
def jobs_search(
    ctx: typer.Context,
    source: Annotated[str, typer.Option("--source", help="Source id: itviec or vietnamworks")],
    fixture: Annotated[Path | None, typer.Option("--fixture", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live", help="Opt into bounded public HTTP")] = False,
    payload_evidence: Annotated[Path | None, typer.Option("--payload-evidence", exists=True)] = None,
    keyword: Annotated[str | None, typer.Option("--keyword")] = None,
    location: Annotated[str | None, typer.Option("--location")] = None,
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    result = _run_source_search(repository, source, fixture, live, payload_evidence, keyword, location)
    _echo_source_result(result)


@jobs_app.command("ingest")
def jobs_ingest(
    ctx: typer.Context,
    source: Annotated[str, typer.Option("--source", help="Source id: itviec or vietnamworks")],
    fixture: Annotated[Path | None, typer.Option("--fixture", exists=True)] = None,
    live: Annotated[bool, typer.Option("--live", help="Opt into bounded public HTTP")] = False,
    payload_evidence: Annotated[Path | None, typer.Option("--payload-evidence", exists=True)] = None,
    keyword: Annotated[str | None, typer.Option("--keyword")] = None,
    location: Annotated[str | None, typer.Option("--location")] = None,
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    result = _run_source_search(repository, source, fixture, live, payload_evidence, keyword, location)
    summary = import_source_result(repository, result)
    _echo_source_result(result)
    typer.echo(f"imported: {summary.imported}")
    typer.echo(f"existing: {summary.existing}")
    typer.echo(f"skipped: {summary.skipped}")


def _run_source_search(
    repository: CareerRepository,
    source: str,
    fixture: Path | None,
    live: bool,
    payload_evidence: Path | None,
    keyword: str | None,
    location: str | None,
) -> SourceResult:
    cache_dir = repository.workspace / ".http-cache"
    normalized = source.lower()
    if normalized == "itviec":
        if live and fixture is None:
            from .ingestion.http_client import SafeHttpClient

            client = SafeHttpClient(cache_dir=cache_dir, allowed_hosts={"itviec.com"})
        elif fixture is not None:
            client = fixture_client_for_itviec(fixture, cache_dir=cache_dir)
        else:
            raise typer.BadParameter("itviec search requires --fixture unless --live is set")
        source_kind = "itviec_http_fixture" if fixture is not None else "itviec_http"
        return search_itviec(client=client, keyword=keyword, location=location, source_kind=source_kind)
    if normalized == "vietnamworks":
        return search_vietnamworks(
            cache_dir=cache_dir,
            live=live,
            fixture_path=fixture,
            payload_evidence_path=payload_evidence,
            keyword=keyword,
            location=location,
        )
    raise typer.BadParameter("source must be itviec or vietnamworks")


def _echo_source_result(result: SourceResult) -> None:
    typer.echo(f"state: {result.state.value}")
    if result.message:
        typer.echo(f"message: {result.message}")
    typer.echo(f"requests: {result.stats.requests}")
    typer.echo(f"bytes: {result.stats.bytes_received}")
    typer.echo(f"parsed: {result.stats.parsed_unique_count}")
    typer.echo(f"rejected: {result.stats.rejected_count}")
    typer.echo(f"missing_fields: {result.stats.missing_required_fields}")
    typer.echo(f"duplicates: {result.stats.duplicates}")
    typer.echo(f"cache_hits: {result.stats.cache_hits}")
    typer.echo(f"filtered: {result.stats.filtered_count}")
    for job in result.jobs:
        typer.echo(f"job: {job.job_id} {job.title} | {job.employer} | {job.location}")


@profile_app.command("validation")
def profile_validation(ctx: typer.Context) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    profile_path = repository.workspace / "profile.json"
    if not profile_path.exists():
        typer.echo("No profile found. Add a local profile.json in the workspace when ready.")
        return
    try:
        profile_data = cast(object, json.loads(profile_path.read_text(encoding="utf-8")))
        profile = CandidateProfile.model_validate(profile_data)
    except (json.JSONDecodeError, ValidationError) as error:
        typer.echo("profile: invalid", err=True)
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo(f"profile: valid {profile.profile_id} version={profile.version}")


@app.command()
def doctor(ctx: typer.Context) -> None:
    repository = repository_from_context(ctx)
    status = repository.doctor()
    typer.echo(f"database: {status['database']}")
    typer.echo(f"foreign_keys: {status['foreign_keys']}")
    typer.echo(f"jobs: {status['jobs']}")

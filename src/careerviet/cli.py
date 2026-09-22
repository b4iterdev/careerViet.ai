import json
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError

from .cv_cli import cv_app, draft_app
from .ingestion.itviec import fixture_client_for_itviec, search_itviec
from .ingestion.manual import import_jd_file_with_status, import_jd_text_with_status
from .ingestion.results import SourceResult
from .ingestion.service import import_source_result
from .ingestion.vietnamworks import search_vietnamworks
from .models.profile import CandidateProfile
from .storage.repository import CareerRepository
from .tracker_cli import applications_app, apply, track

app = typer.Typer(no_args_is_help=True)
jobs_app = typer.Typer(no_args_is_help=True)
profile_app = typer.Typer(no_args_is_help=True)
evaluate_app = typer.Typer(no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")
app.add_typer(profile_app, name="profile")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(cv_app, name="cv")
app.add_typer(draft_app, name="draft")
app.add_typer(applications_app, name="applications")
app.command("track")(track)
app.command("apply")(apply)


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


@profile_app.command("answer")
def profile_answer(
    ctx: typer.Context,
    draft_id: Annotated[str, typer.Option("--draft-id", help="Profile draft id")],
    text: Annotated[str, typer.Option("--text", help="Answer text")],
    author: Annotated[str, typer.Option("--author", help="Who answered")] = "candidate",
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    from .onboarding import OnboardingAnswer, ProfileOnboarding

    session = ProfileOnboarding.resume(repository, draft_id)
    session.answer(OnboardingAnswer(text=text, answered_by=author))
    typer.echo(f"saved answer for draft: {draft_id}")


@profile_app.command("review")
def profile_review(
    ctx: typer.Context,
    draft_id: Annotated[str, typer.Option("--draft-id", help="Profile draft id")],
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    from .onboarding import ProfileOnboarding

    session = ProfileOnboarding.resume(repository, draft_id)
    review_result = session.review()
    typer.echo(f"status: {review_result.status}")
    if review_result.missing_fields:
        typer.echo(f"missing_fields: {', '.join(review_result.missing_fields)}")
    typer.echo(review_result.summary)


@profile_app.command("correct")
def profile_correct(
    ctx: typer.Context,
    draft_id: Annotated[str, typer.Option("--draft-id", help="Profile draft id")],
    field: Annotated[str, typer.Option("--field", help="Field to correct")],
    text: Annotated[str, typer.Option("--text", help="Corrected text")],
    author: Annotated[str, typer.Option("--author", help="Who corrected")] = "candidate",
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    from .onboarding import OnboardingAnswer, ProfileOnboarding

    session = ProfileOnboarding.resume(repository, draft_id)
    session.correct(field, OnboardingAnswer(text=text, answered_by=author))
    typer.echo(f"corrected {field} for draft: {draft_id}")


@profile_app.command("confirm")
def profile_confirm(
    ctx: typer.Context,
    draft_id: Annotated[str, typer.Option("--draft-id", help="Profile draft id")],
    author: Annotated[str, typer.Option("--author", help="Who confirmed")] = "candidate",
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    from .onboarding import ProfileOnboarding

    session = ProfileOnboarding.resume(repository, draft_id)
    profile = session.confirm(confirmed_by=author)
    typer.echo(f"confirmed profile {profile.profile_id} version={profile.version}")


@evaluate_app.command("triage")
def evaluate_triage(
    ctx: typer.Context,
    job_id: str,
    profile_version: Annotated[str | None, typer.Option("--profile-version")] = None,
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    job = repository.get_job(job_id)
    if job is None:
        typer.echo(f"Job not found: {job_id}", err=True)
        raise typer.Exit(1)
    if profile_version is not None:
        profile = repository.get_profile_version(profile_version)
    else:
        profile = repository.get_latest_profile()
    if profile is None:
        typer.echo("No confirmed profile found", err=True)
        raise typer.Exit(1)
    from .triage import triage_job

    result = triage_job(profile, job)
    typer.echo(f"verdict: {result.verdict}")
    if result.known_violations:
        typer.echo("known_violations:")
        for v in result.known_violations:
            typer.echo(f"  - {v.constraint}: {v.evidence}")
    if result.unknowns:
        typer.echo("unknowns:")
        for u in result.unknowns:
            typer.echo(f"  - {u.constraint}: {u.evidence}")
    if result.conditional:
        typer.echo("conditional:")
        for c in result.conditional:
            typer.echo(f"  - {c.constraint}: {c.evidence}")


@evaluate_app.command("export-packet")
def evaluate_export_packet(
    ctx: typer.Context,
    job_id: str,
    profile_version: Annotated[str, typer.Option("--profile-version")],
    output: Annotated[Path, typer.Option("--output")],
    consent: Annotated[bool, typer.Option("--consent", help="Explicit consent for packet export")] = False,
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    from .evaluation_runtime import create_evaluation_packet

    try:
        packet = create_evaluation_packet(repository, profile_version, job_id, export_consent=consent)
    except Exception as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    output.write_text(packet.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"exported packet: {packet.packet_id} to {output}")


@evaluate_app.command("import-report")
def evaluate_import_report(
    ctx: typer.Context,
    packet: Annotated[Path, typer.Option("--packet", exists=True)],
    response: Annotated[Path, typer.Option("--response", exists=True)],
) -> None:
    repository = repository_from_context(ctx)
    repository.initialize()
    from .evaluation_runtime import EvaluationPacket, validate_evaluation_response

    packet_data = cast(dict[str, object], json.loads(packet.read_text(encoding="utf-8")))
    eval_packet = EvaluationPacket.model_validate(packet_data)
    response_data = cast(dict[str, object], json.loads(response.read_text(encoding="utf-8")))
    try:
        report = validate_evaluation_response(repository, eval_packet, response_data)
    except Exception as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    repository.save_evaluation_report(
        report_id=f"rep_{report.packet_id[7:]}",
        profile_version=report.profile_version,
        job_id=report.job_id,
        jd_content_hash=report.jd_content_hash,
        runtime=report.runtime,
        model=report.model,
        payload_json=report.model_dump_json(),
    )
    typer.echo(f"stored report: {report.packet_id}")


@app.command()
def doctor(ctx: typer.Context) -> None:
    repository = repository_from_context(ctx)
    status = repository.doctor()
    typer.echo(f"database: {status['database']}")
    typer.echo(f"foreign_keys: {status['foreign_keys']}")
    typer.echo(f"jobs: {status['jobs']}")
    if "profile_drafts" in status:
        typer.echo(f"profile_drafts: {status['profile_drafts']}")
    if "profiles" in status:
        typer.echo(f"profiles: {status['profiles']}")
    if "evaluation_reports" in status:
        typer.echo(f"evaluation_reports: {status['evaluation_reports']}")
